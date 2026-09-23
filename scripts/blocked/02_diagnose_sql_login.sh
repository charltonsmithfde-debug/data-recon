#!/usr/bin/env bash
# Find out why the Cube SQL login fails -- the one action the agent cannot take.
#
# State of play: pg_probe.py gets a real Postgres wire response from Cube for all five users and
# is rejected by every one:
#
#     FAIL  metabase.member@sanlam.co.za  password authentication failed for user "..."
#
# That is progress. It proves the tunnel, IAP, the host firewall, the listener and checkSqlAuth
# are all alive and actively rejecting. Everything network-level is solved. What is left is one
# question, and this script answers it: does the plaintext in the probe file match the digests
# that are actually deployed in the VM's CUBEJS_SQL_USERS?
#
# The leading hypothesis is that the probe file was written from a different mint_sql_users.js
# run than the one whose digests reached the VM, so they were never going to match.
#
# The agent cannot run this because every route to the answer reads credential material and the
# sandbox refuses that categorically. Nothing here prints a secret: pull_store.py emits
# fingerprints, verify_creds.py emits booleans.
#
# Usage:
#   ./scripts/blocked/02_diagnose_sql_login.sh <probe_creds.json>
#
#   probe_creds.json is {"user": "password", ...} -- the plaintext mint_sql_users.js printed
#   once. If you no longer have it, skip to 02b_remint_sql_users.sh; that is the fix either way.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

parse_common_flags "$@"
CREDS="${REMAINING_ARGS[0]:-}"
[ -n "${CREDS}" ] || die "Usage: $0 <probe_creds.json>"
[ -f "${CREDS}" ] || die "No such file: ${CREDS}"

require_gcloud
require_state_dir
require_ca_bundle

LOCAL_PORT="${LOCAL_PORT:-15432}"
STORE="${STATE_DIR}/deployed_store.json"
TUNNEL_LOG="${STATE_DIR}/tunnel.log"
TUNNEL_PID=""

cleanup() {
  if [ -n "${TUNNEL_PID}" ] && kill -0 "${TUNNEL_PID}" 2>/dev/null; then
    info "closing tunnel (pid ${TUNNEL_PID})"
    kill "${TUNNEL_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# ──────────────────────────────────────────────────────────────────────────────
heading "1. The host firewall -- is the port actually reachable?"
# ──────────────────────────────────────────────────────────────────────────────
#
# Container-Optimized OS ships a default-DROP INPUT chain allowing only port 22 and established
# flows. A GCP firewall rule is necessary but NOT sufficient on COS. The rule that opened 5432 on
# the live VM was added by hand and is runtime-only -- a reboot closes it again until the fixed
# deploy script (which installs it as an ExecStartPre on cube-sql.service) is next run.

gcloud compute ssh "${SQL_VM}" --zone "${ZONE}" --tunnel-through-iap --command="
  echo \"booted: \$(uptime -s)\"
  echo '--- INPUT policy and the 5432 rule ---'
  sudo iptables -S INPUT | grep -E 'policy|${SQL_PORT}' || echo '(no ${SQL_PORT} rule -- port is CLOSED at the host)'
  echo '--- listener ---'
  sudo ss -ltnp 2>/dev/null | grep ':${SQL_PORT}' || echo '(nothing listening on ${SQL_PORT})'
  echo '--- container ---'
  docker ps --format '{{.Names}} {{.Status}}'
" 2>&1 | sed 's/^/  /'

# ──────────────────────────────────────────────────────────────────────────────
heading "2. The deployed credential store"
# ──────────────────────────────────────────────────────────────────────────────

python "${HERE}/lib/pull_store.py" "${SQL_VM}" "${ZONE}" "${STORE}" || \
  die "Could not read the deployed store. Without it there is nothing to compare against."

# ──────────────────────────────────────────────────────────────────────────────
heading "3. Does the probe plaintext match what is deployed?"
# ──────────────────────────────────────────────────────────────────────────────

if python "${HERE}/lib/verify_creds.py" "${CREDS}" "${STORE}"; then
  CREDS_OK=1
else
  CREDS_OK=0
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "4. Live login through the IAP tunnel"
# ──────────────────────────────────────────────────────────────────────────────

if [ "${CREDS_OK}" = "0" ]; then
  warn "the probe passwords do not match the deployed digests -- a live attempt will fail"
  warn "run 02b_remint_sql_users.sh, then re-run this script"
  echo
  exit 1
fi

info "opening IAP tunnel localhost:${LOCAL_PORT} -> ${SQL_VM}:${SQL_PORT}"
gcloud compute start-iap-tunnel "${SQL_VM}" "${SQL_PORT}" \
  --local-host-port="localhost:${LOCAL_PORT}" --zone "${ZONE}" \
  > "${TUNNEL_LOG}" 2>&1 &
TUNNEL_PID=$!

# Wait for the listener rather than sleeping a fixed interval: the tunnel takes 2-15 seconds
# depending on how long IAP takes to authorise, and a fixed sleep is either slow or flaky.
for _ in $(seq 1 30); do
  if python -c "
import socket, sys
s = socket.socket()
s.settimeout(1)
sys.exit(0 if s.connect_ex(('127.0.0.1', ${LOCAL_PORT})) == 0 else 1)
" 2>/dev/null; then
    break
  fi
  if ! kill -0 "${TUNNEL_PID}" 2>/dev/null; then
    bad "the tunnel exited early:"
    sed 's/^/      /' "${TUNNEL_LOG}"
    exit 1
  fi
  sleep 1
done

ok "tunnel up"
echo
PROBE_PORT="${LOCAL_PORT}" python "${HERE}/lib/pg_probe.py" "${CREDS}" | sed 's/^/  /'

# ──────────────────────────────────────────────────────────────────────────────
heading "5. The half that SELECT 1 does not test"
# ──────────────────────────────────────────────────────────────────────────────

info "SELECT 1 is answered by Cube alone -- it never touches DuckDB or GCS."
info "US-8.3 is not done until a real cube query has exercised the new HMAC pair:"
echo
info "  PROBE_PORT=${LOCAL_PORT} PROBE_QUERY='SELECT COUNT(*) FROM MemberMonthly' \\"
info "    python ${HERE}/lib/pg_probe.py ${CREDS}"
echo
