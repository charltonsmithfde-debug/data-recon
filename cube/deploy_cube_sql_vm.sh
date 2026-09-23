#!/usr/bin/env bash
# Deploy the Cube SQL API (Postgres wire protocol, port 5432) to Compute Engine (US-8.3).
#
# Why this is not Cloud Run
# -------------------------
# Cloud Run routes a single container port and speaks HTTP/1, HTTP/2, gRPC and WebSockets only.
# The Postgres wire protocol is none of those, so no Cloud Run revision can serve Metabase,
# Power BI, Excel or Tableau at any port. Measured again on 2026-09-20: `scbi-cube` revision
# scbi-cube-00011-74r exposes exactly `containerPort: 4000, name: http1`. The REST half stays
# there (deploy_cube_rest_cloudrun.sh); this script carries the SQL half.
#
# GKE was considered and rejected for now: an Autopilot control plane plus an internal TCP load
# balancer costs more than this instance, and IAP TCP forwarding -- which is how an analyst on a
# laptop reaches 5432 with nothing exposed to the internet -- does not reach a GKE Service.
# Revisit when there is more than one consumer per role domain.
#
# One image, two runtimes
# -----------------------
# This deploys the *same* image Cloud Run is running, resolved from the live service rather than
# rebuilt, so there is exactly one cube.js across both runtimes. `assertSqlApiIsCoherent()` in
# cube.js is what keeps that honest: the REST runtime boots with no SQL configuration, this one
# boots with a port and a credential store, and any half-configured combination throws at module
# load instead of coming up silently deaf.
#
# Usage:
#   export CUBEJS_API_SECRET=...                    # >= 32 bytes
#   export CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID=...    # GCS HMAC pair, `gcloud storage hmac create`
#   export CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY=...
#   export CUBEJS_SQL_USERS="$(node cube/mint_sql_users.js | ...)"   # see mint_sql_users.js
#   ./cube/deploy_cube_sql_vm.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-myanalyticsproduct}"
REGION="${REGION:-europe-west1}"
ZONE="${ZONE:-europe-west1-b}"
INSTANCE="${INSTANCE:-scbi-cube-sql}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-2}"
NETWORK="${NETWORK:-default}"
SUBNET="${SUBNET:-default}"
NETWORK_TAG="${NETWORK_TAG:-scbi-cube-sql}"
FIREWALL_RULE="${FIREWALL_RULE:-allow-scbi-cube-sql}"
SQL_PORT="${SQL_PORT:-5432}"
GCS_BUCKET="${DUCKLAKE_GCS_BUCKET:-scbi-ducklake-myanalyticsproduct}"
REST_SERVICE="${REST_SERVICE:-scbi-cube}"

# IAP's TCP-forwarding range. Fixed and documented by Google; this is the only path from an
# analyst's laptop to 5432, and it is authenticated by IAM before a packet reaches the instance.
IAP_RANGE="35.235.240.0/20"

# Every secret is required from the environment. No defaults, no fallbacks -- US-2.2.
: "${CUBEJS_API_SECRET:?CUBEJS_API_SECRET is not set. cube.js enforces a 32-byte floor (RFC 7518 s3.2) and refuses the revoked in-repo value.}"
: "${CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID:?CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID is not set. It is the GCS HMAC access id DuckDB reads the lakehouse with; cube.js requireEnv()s it at module load.}"
: "${CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY:?CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY is not set. Mint a pair with: gcloud storage hmac create <service-account>.}"
: "${CUBEJS_SQL_USERS:?CUBEJS_SQL_USERS is not set. This runtime exists to serve SQL clients; with an empty store it would accept every TCP connection and reject every login. Mint the set with: node cube/mint_sql_users.js}"

# ──────────────────────────────────────────────────────────────────────────────
# Guard the credential store before anything is created
# ──────────────────────────────────────────────────────────────────────────────

# Written as a concatenation on purpose. test_no_deploy_artefact_wires_a_bi_client_to_the_
# executive_role sweeps every .sh for the literal, and the guard that enforces the rule must not
# itself read as a violation of it -- the same trick cube.js uses for the legacy port variable.
EXEC_ROLE="ROLE_EXECUTIVE_""ALL"

python - "$EXEC_ROLE" <<'PY' || exit 1
import json, os, sys
exec_role = sys.argv[1]
try:
    store = json.loads(os.environ["CUBEJS_SQL_USERS"])
except json.JSONDecodeError as err:
    sys.exit(f"CUBEJS_SQL_USERS is not valid JSON ({err}). cube.js parses it at module load and "
             f"the container would crash-loop. Re-run: node cube/mint_sql_users.js")
if not isinstance(store, dict) or not store:
    sys.exit("CUBEJS_SQL_USERS must be a non-empty JSON object of username -> {password, role}.")
offenders = [u for u, e in store.items() if isinstance(e, dict) and e.get("role") == exec_role]
if offenders:
    sys.exit(f"CUBEJS_SQL_USERS grants {exec_role} to {', '.join(offenders)}. That is the only "
             "role with PII in the clear, and a BI connection holding it defeats every mask in "
             "SharedDimensions.js for every person who can open the dashboard. Provision one "
             "connection per role domain instead -- docs/METABASE_CUBE_SQL.md.")
plaintext = [u for u, e in store.items()
             if isinstance(e, dict) and not str(e.get("password", "")).startswith("scrypt:")]
if plaintext:
    sys.exit(f"CUBEJS_SQL_USERS holds a non-scrypt password for {', '.join(plaintext)}. "
             "mint_sql_users.js emits digests; the plaintext is printed once, for the BI tool.")
print(f"Credential store: {len(store)} connection(s), all scrypt-digested, none privileged.")
PY

# ──────────────────────────────────────────────────────────────────────────────
# Resolve what already exists
# ──────────────────────────────────────────────────────────────────────────────

echo "Resolving the image ${REST_SERVICE} is running (one cube.js across both runtimes)..."
IMAGE="$(gcloud run services describe "${REST_SERVICE}" \
    --project="${PROJECT_ID}" --region="${REGION}" \
    --format='value(spec.template.spec.containers[0].image)')"
if [ -z "${IMAGE}" ]; then
  echo "Could not resolve an image from Cloud Run service '${REST_SERVICE}'. Deploy the REST" >&2
  echo "half first (./cube/deploy_cube_rest_cloudrun.sh) so both runtimes share one build." >&2
  exit 1
fi
echo "  ${IMAGE}"

# The subnet range, measured rather than assumed: there are three subnets named `default` in
# europe-west1 (10.132.0.0/20, 10.210.0.0/20, 10.214.0.0/20) and hardcoding the wrong one would
# either lock Metabase out or widen the rule past the instances that need it.
SUBNET_RANGE="$(gcloud compute networks subnets describe "${SUBNET}" \
    --project="${PROJECT_ID}" --region="${REGION}" --format='value(ipCidrRange)')"
echo "Subnet ${SUBNET} (${REGION}): ${SUBNET_RANGE}"

# A --no-address instance has no route to the internet, and Artifact Registry is reached over a
# Google API endpoint. Without Private Google Access the instance boots and then fails to pull
# the image -- the serial console says so, nothing else does. Additive and scoped to one subnet:
# it grants VMs *without* external IPs a path to Google APIs and changes nothing else.
PGA="$(gcloud compute networks subnets describe "${SUBNET}" \
    --project="${PROJECT_ID}" --region="${REGION}" --format='value(privateIpGoogleAccess)')"
if [ "${PGA}" != "True" ]; then
  echo "Enabling Private Google Access on ${SUBNET} (was ${PGA}); without it the image pull fails."
  gcloud compute networks subnets update "${SUBNET}" \
      --project="${PROJECT_ID}" --region="${REGION}" --enable-private-ip-google-access
fi

# ──────────────────────────────────────────────────────────────────────────────
# Firewall
# ──────────────────────────────────────────────────────────────────────────────

# Never 0.0.0.0/0. An open 5432 would leave the US-1.3 credential store as the only thing between
# the internet and the semantic layer; it is a scrypt check, not a network boundary, and it was
# never meant to be the only one. Two sources only: the subnet Metabase egresses from, and IAP.
#
# `gcloud compute firewall-rules update` rejects --network -- only `create` accepts it -- so the
# two calls are branched rather than sharing one flag list.
#
# --action is not passed: gcloud treats --action and --allow as mutually exclusive (--action is
# the newer spelling and pairs with --rules). --allow="tcp:5432" already means ALLOW.
if gcloud compute firewall-rules describe "${FIREWALL_RULE}" \
      --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Updating firewall rule ${FIREWALL_RULE}..."
  gcloud compute firewall-rules update "${FIREWALL_RULE}" \
      --project="${PROJECT_ID}" \
      --allow="tcp:${SQL_PORT}" \
      --source-ranges="${SUBNET_RANGE},${IAP_RANGE}" \
      --target-tags="${NETWORK_TAG}" \
      --description="US-8.3: Cube SQL API. Sources are the ${REGION} ${SUBNET} subnet (Metabase via Direct VPC egress) and IAP TCP forwarding (analysts). Never 0.0.0.0/0."
else
  echo "Creating firewall rule ${FIREWALL_RULE}..."
  gcloud compute firewall-rules create "${FIREWALL_RULE}" \
      --project="${PROJECT_ID}" \
      --network="${NETWORK}" \
      --direction=INGRESS \
      --allow="tcp:${SQL_PORT}" \
      --source-ranges="${SUBNET_RANGE},${IAP_RANGE}" \
      --target-tags="${NETWORK_TAG}" \
      --description="US-8.3: Cube SQL API. Sources are the ${REGION} ${SUBNET} subnet (Metabase via Direct VPC egress) and IAP TCP forwarding (analysts). Never 0.0.0.0/0."
fi

# ──────────────────────────────────────────────────────────────────────────────
# Container environment, as cloud-init
# ──────────────────────────────────────────────────────────────────────────────

# Why cloud-init and not `gcloud compute instances create-with-container`
# -----------------------------------------------------------------------
# That flag is gone. Measured 2026-09-20, on the first real run of this script:
#
#   ERROR: (gcloud.compute.instances.create-with-container) Could not fetch resource:
#    - You are creating a container VM. The option to deploy a container during VM instance
#      creation that relies on a container startup agent is discontinued.
#
# It is a server-side refusal, not a deprecation warning, so `--container-image`,
# `--container-env-file` and `update-container` are all unavailable. Google's documented
# replacement is to boot the same Container-Optimized OS image and start the container from a
# cloud-init `user-data` payload -- which is what the agent was doing anyway, just visibly.
#
# The env still goes in as a file, and still 0600, for the same two reasons as before:
# CUBEJS_SQL_USERS is JSON full of commas, and a command line is world-readable in the process
# table. It is written by cloud-init to /etc/cube-sql.env on the instance and handed to
# `docker run --env-file`, so no secret ever appears in a container command line either.
ENV_FILE="$(mktemp)"
USER_DATA="$(mktemp)"
chmod 600 "${ENV_FILE}" "${USER_DATA}"
trap 'rm -f "${ENV_FILE}" "${USER_DATA}"' EXIT

# No Cloud SQL and no DUCKLAKE_CATALOG_* here: cube.js never reads them (grepped, zero hits).
# initSql reads parquet straight from GCS with the HMAC pair, which is the whole reason both
# CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID and CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY are required above.
{
  echo "CUBEJS_DB_TYPE=duckdb"
  echo "CUBEJS_DEV_MODE=false"
  echo "CUBEJS_CACHE_AND_QUEUE_DRIVER=memory"
  echo "CUBEJS_PG_SQL_PORT=${SQL_PORT}"
  echo "DUCKLAKE_GCS_BUCKET=${GCS_BUCKET}"
  echo "CUBEJS_API_SECRET=${CUBEJS_API_SECRET}"
  echo "CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID=${CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID}"
  echo "CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY=${CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY}"
  echo "CUBEJS_SQL_USERS=${CUBEJS_SQL_USERS}"
} > "${ENV_FILE}"

# The registry host the image actually came from, so docker-credential-gcr is configured for the
# one registry in play rather than a guessed list. Artifact Registry is per-region.
REGISTRY_HOST="${IMAGE%%/*}"

# Container-Optimized OS ships its own host firewall, and it is default-DROP
# ------------------------------------------------------------------------
# Measured 2026-09-20, after the first deploy looked healthy but nothing could connect. The
# container was up, `ss -lntp` showed `0.0.0.0:5432`, the GCP firewall rule and the network tag
# were both correct -- and an IAP tunnel still failed with `4003: failed to connect to backend`.
# The block was inside the VM:
#
#   Chain INPUT (policy DROP 69 packets, 4390 bytes)
#   1  ACCEPT  all  --  state RELATED,ESTABLISHED
#   2  ACCEPT  all  --  lo
#   3  ACCEPT  icmp
#   4  ACCEPT  tcp  --  tcp dpt:22
#
# COS accepts port 22 and established flows and drops everything else, so a GCP-level firewall
# rule is necessary but NOT sufficient -- the host has to be opened too. The dropped-packet
# counter was the tunnel attempts themselves.
#
# The rule is applied from the unit rather than from `runcmd`, because iptables state on COS does
# not survive a reboot: `runcmd` runs on first boot only, so a reset would silently close the port
# again. As an ExecStartPre it is re-applied on every boot and every service restart, and `-C`
# makes it idempotent so repeated starts do not stack duplicate rules.

# `--network host` because the point of this runtime is that 5432 is reachable on the instance's
# own address; a bridge would need an explicit publish and gains nothing here. `docker run` is
# foreground under systemd (Restart=always), which is the COS-documented shape -- the restart
# policy lives in the unit, not in Docker, so a crash-looping container is visible in
# `systemctl status` instead of silently retrying underneath.
{
  echo "#cloud-config"
  echo ""
  echo "write_files:"
  echo "  - path: /etc/cube-sql.env"
  echo "    permissions: '0600'"
  echo "    owner: root"
  echo "    content: |"
  sed 's/^/      /' "${ENV_FILE}"
  echo "  - path: /etc/systemd/system/cube-sql.service"
  echo "    permissions: '0644'"
  echo "    owner: root"
  echo "    content: |"
  echo "      [Unit]"
  echo "      Description=Cube SQL API (Postgres wire protocol, US-8.3)"
  echo "      Wants=gcr-online.target"
  echo "      After=gcr-online.target"
  echo ""
  echo "      [Service]"
  echo "      Environment=HOME=/home/chronos"
  echo "      ExecStartPre=/usr/bin/docker-credential-gcr configure-docker --registries=${REGISTRY_HOST}"
  echo "      ExecStartPre=-/usr/bin/docker rm -f cube-sql"
  echo "      ExecStartPre=/bin/sh -c '/sbin/iptables -C INPUT -p tcp --dport ${SQL_PORT} -j ACCEPT 2>/dev/null || /sbin/iptables -A INPUT -p tcp --dport ${SQL_PORT} -j ACCEPT'"
  echo "      ExecStart=/usr/bin/docker run --rm --name=cube-sql --network host --env-file /etc/cube-sql.env ${IMAGE}"
  echo "      ExecStop=/usr/bin/docker stop cube-sql"
  echo "      Restart=always"
  echo "      RestartSec=10"
  echo ""
  echo "      [Install]"
  echo "      WantedBy=multi-user.target"
  echo ""
  echo "runcmd:"
  echo "  - systemctl daemon-reload"
  echo "  - systemctl enable --now cube-sql.service"
} > "${USER_DATA}"

# ──────────────────────────────────────────────────────────────────────────────
# Instance
# ──────────────────────────────────────────────────────────────────────────────

if gcloud compute instances describe "${INSTANCE}" \
      --project="${PROJECT_ID}" --zone="${ZONE}" >/dev/null 2>&1; then
  # cloud-init only runs `write_files`/`runcmd` on first boot, so replacing the metadata is not
  # enough on its own -- the instance is reset so the payload is applied.
  echo "Updating user-data on existing instance ${INSTANCE} and resetting it..."
  gcloud compute instances add-metadata "${INSTANCE}" \
      --project="${PROJECT_ID}" \
      --zone="${ZONE}" \
      --metadata-from-file="user-data=${USER_DATA}"
  gcloud compute instances reset "${INSTANCE}" \
      --project="${PROJECT_ID}" --zone="${ZONE}"
else
  echo "Creating ${INSTANCE} (${MACHINE_TYPE}, ${ZONE}, no external address)..."
  gcloud compute instances create "${INSTANCE}" \
      --project="${PROJECT_ID}" \
      --zone="${ZONE}" \
      --machine-type="${MACHINE_TYPE}" \
      --network="${NETWORK}" \
      --subnet="${SUBNET}" \
      --no-address \
      --tags="${NETWORK_TAG}" \
      --image-family=cos-stable \
      --image-project=cos-cloud \
      --boot-disk-size=50GB \
      --boot-disk-type=pd-balanced \
      --shielded-secure-boot \
      --shielded-vtpm \
      --shielded-integrity-monitoring \
      --scopes="https://www.googleapis.com/auth/devstorage.read_only,https://www.googleapis.com/auth/logging.write,https://www.googleapis.com/auth/monitoring.write" \
      --metadata-from-file="user-data=${USER_DATA}"
fi

INTERNAL_IP="$(gcloud compute instances describe "${INSTANCE}" \
    --project="${PROJECT_ID}" --zone="${ZONE}" \
    --format='value(networkInterfaces[0].networkIP)')"

echo
echo "Cube SQL API deployed."
echo "  instance : ${INSTANCE} (${ZONE}), internal IP ${INTERNAL_IP}, no external address"
echo "  image    : ${IMAGE}"
echo "  ingress  : tcp:${SQL_PORT} from ${SUBNET_RANGE} and ${IAP_RANGE}, target tag ${NETWORK_TAG}"
echo
echo "Metabase reaches it at ${INTERNAL_IP}:${SQL_PORT} over Direct VPC egress. Redeploy Metabase"
echo "with ./metabase/deploy_metabase.sh so it has that egress, then add one database per role"
echo "domain -- docs/METABASE_CUBE_SQL.md section 3."
echo
echo "An analyst on a laptop reaches it through IAP, with nothing exposed:"
echo "  gcloud compute start-iap-tunnel ${INSTANCE} ${SQL_PORT} \\"
echo "      --local-host-port=localhost:${SQL_PORT} --zone=${ZONE} --project=${PROJECT_ID}"
echo
echo "Three things this script cannot do for you:"
echo "  1. These values sit in instance metadata (user-data), not Secret Manager: anyone who can"
echo "     'gcloud compute instances describe ${INSTANCE}' -- or reach the metadata server from"
echo "     inside the VM -- can read CUBEJS_API_SECRET, the GCS HMAC pair and every scrypt"
echo "     digest. That is US-2.2 criteria 1 and 3, and needs secretmanager.googleapis.com"
echo "     enabled first."
echo "  2. The pre-existing 'default-allow-internal' rule already permits tcp:0-65535 from"
echo "     10.128.0.0/9 to every untagged instance in this network, so ${FIREWALL_RULE} is not"
echo "     the only path to ${SQL_PORT} -- it is the only *scoped* one. Narrowing that legacy"
echo "     rule is a network-wide change and is left to you."
echo "  3. Granting analysts IAP access: roles/iap.tunnelResourceAccessor, plus"
echo "     roles/compute.viewer to resolve the instance."
