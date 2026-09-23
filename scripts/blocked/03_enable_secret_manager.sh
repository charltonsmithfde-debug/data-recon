#!/usr/bin/env bash
# Enable Secret Manager and create the secret containers -- US-2.2, the no-downtime half.
#
# Nothing in this script touches a running service. It enables an API, creates four empty
# secrets, and grants the runtime service account read access to them. No value is written here
# and no deployment is changed, so there is nothing to roll back beyond deleting the secrets.
#
# 04_rotate_and_mount_secrets.sh is the step that fills them and switches the services over, and
# that one does cause downtime. They are separate on purpose: this half can be run now, in
# working hours, and reviewed before the half that bites.
#
# Measured 2026-09-20: secretmanager.googleapis.com is SERVICE_DISABLED on this project, so every
# credential the platform holds is today a plain --set-env-vars value, readable by anyone with
# `gcloud run services describe` (deploy_cube_rest_cloudrun.sh:71-73 says so in its own output).
#
# WHICH VALUES BECOME SECRETS, AND WHICH DO NOT
#
# The GCS HMAC *access id* stays a plain environment variable. It is an identifier, not a
# credential -- it is the username half of the pair, it appears in bucket audit logs, and
# `gcloud storage hmac list` prints it to anyone with read access on the project. Only the
# secret half is a secret. Treating identifiers as secrets makes a rotation harder to reason
# about for no gain.
#
# Usage:
#   ./scripts/blocked/03_enable_secret_manager.sh [--yes] [--dry-run]
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

parse_common_flags "$@"
require_gcloud

# name:purpose. The value is NOT created here -- an empty secret is a container with no versions,
# which is exactly what 04 adds to.
SECRETS=(
  "scbi-cube-api-secret:CUBEJS_API_SECRET -- signs Cube's JWTs, >= 32 bytes per RFC 7518 s3.2"
  "scbi-gcs-hmac-secret:CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY -- DuckDB's read key for the lakehouse"
  "scbi-ducklake-catalog-password:DUCKLAKE_CATALOG_PASSWORD -- Cloud SQL ducklake_admin"
  "scbi-metabase-db-password:Metabase's Cloud SQL metabase_admin password"
)

# ──────────────────────────────────────────────────────────────────────────────
heading "1. Enable the API"
# ──────────────────────────────────────────────────────────────────────────────

if gcloud services list --enabled --filter='config.name:secretmanager.googleapis.com' \
   --format='value(config.name)' 2>/dev/null | grep -q secretmanager; then
  ok "secretmanager.googleapis.com is already enabled"
else
  info "enabling secretmanager.googleapis.com (no effect on running services)"
  run gcloud services enable secretmanager.googleapis.com --project="${PROJECT_ID}" \
    || die "Could not enable Secret Manager. This needs roles/serviceusage.serviceUsageAdmin."
  # Enablement propagates asynchronously; the first create can 403 for a few seconds after.
  for _ in $(seq 1 12); do
    gcloud secrets list --limit=1 >/dev/null 2>&1 && break
    sleep 5
  done
  ok "enabled"
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "2. Create the secret containers"
# ──────────────────────────────────────────────────────────────────────────────

for entry in "${SECRETS[@]}"; do
  name="${entry%%:*}"
  purpose="${entry#*:}"
  if gcloud secrets describe "${name}" >/dev/null 2>&1; then
    versions="$(gcloud secrets versions list "${name}" --filter='state=ENABLED' \
                --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')"
    ok "${name} exists (${versions} enabled version(s))"
  else
    info "creating ${name} -- ${purpose}"
    run gcloud secrets create "${name}" \
      --replication-policy=automatic \
      --labels=component=scbi,managed-by=runbook \
      || warn "could not create ${name}"
  fi
done

# ──────────────────────────────────────────────────────────────────────────────
heading "3. Grant the runtime service account read access"
# ──────────────────────────────────────────────────────────────────────────────
#
# Granted per secret rather than project-wide: roles/secretmanager.secretAccessor at project
# level would also grant every secret created later, by anyone, for any purpose.

info "service account: ${COMPUTE_SA}"

for entry in "${SECRETS[@]}"; do
  name="${entry%%:*}"
  gcloud secrets describe "${name}" >/dev/null 2>&1 || continue
  run gcloud secrets add-iam-policy-binding "${name}" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role=roles/secretmanager.secretAccessor \
    --condition=None \
    >/dev/null || warn "could not grant accessor on ${name}"
  ok "${name}: accessor granted to the runtime SA"
done

# ──────────────────────────────────────────────────────────────────────────────
heading "Done -- nothing is live yet"
# ──────────────────────────────────────────────────────────────────────────────

info "The secrets exist and are empty. Every service still reads its plain env vars,"
info "exactly as before this ran."
echo
info "Next: 04_rotate_and_mount_secrets.sh fills them and switches the services over."
info "      That step DOES take Cube and Metabase down for a redeploy. Read its header first."
echo
