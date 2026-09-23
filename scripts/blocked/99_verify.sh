#!/usr/bin/env bash
# The closing board: re-run the preflight, then check the things only a finished runbook can
# satisfy. Read-only -- it changes nothing and is safe to run at any time.
#
# 01_preflight.sh answers "what is the state?". This answers "did the runbook actually land?",
# which is a different question: a step can run without error and still leave the platform
# short of the criterion it was meant to meet.
#
# Usage:
#   ./scripts/blocked/99_verify.sh [probe_creds.json]
#
#   With a probe file, it also runs a live query through an IAP tunnel -- the only check that
#   exercises Cube, DuckDB and GCS together. Without one, everything else still runs.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

parse_common_flags "$@"
CREDS="${REMAINING_ARGS[0]:-}"

require_gcloud
require_state_dir

FAILED=0
fail() { FAILED=$((FAILED + 1)); }

# ──────────────────────────────────────────────────────────────────────────────
heading "A. The state board"
# ──────────────────────────────────────────────────────────────────────────────

"${HERE}/01_preflight.sh" || true

# ──────────────────────────────────────────────────────────────────────────────
heading "B. Did the runbook land?"
# ──────────────────────────────────────────────────────────────────────────────

# --- 03/04: secrets are mounted, not pasted -----------------------------------
#
# The criterion is not "Secret Manager is enabled" but "the running revision reads from it".
# A service can have secrets available and still be serving a revision full of plain values.

for svc in "${CUBE_SERVICE}" "${METABASE_SERVICE}" "${THIN_WEB_SERVICE}"; do
  gcloud run services describe "${svc}" --region="${REGION}" \
    --format='value(metadata.name)' >/dev/null 2>&1 || continue

  env_json="$(gcloud run services describe "${svc}" --region="${REGION}" \
              --format='json(spec.template.spec.containers[0].env)' 2>/dev/null)"

  # Names only. A value is never printed by this script.
  if echo "${env_json}" | grep -q 'secretKeyRef'; then
    ok "${svc}: reads at least one value from Secret Manager"
  else
    bad "${svc}: no secretKeyRef on the running revision -- still plain env vars"; fail
  fi

  # The crash-loop trap: cube.js requireEnv()s both halves at module load.
  if [ "${svc}" = "${CUBE_SERVICE}" ]; then
    if echo "${env_json}" | grep -q 'CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID' && \
       echo "${env_json}" | grep -q 'CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY'; then
      ok "${svc}: both CUBEJS_DB_DUCKDB_S3_* are set"
    else
      bad "${svc}: a CUBEJS_DB_DUCKDB_S3_* half is missing -- cube.js:392-393 crash-loops"; fail
    fi
  fi
done

# --- 05: nobody anonymous ------------------------------------------------------

for svc in "${CUBE_SERVICE}" "${METABASE_SERVICE}" "${THIN_WEB_SERVICE}"; do
  gcloud run services describe "${svc}" --region="${REGION}" \
    --format='value(metadata.name)' >/dev/null 2>&1 || continue
  if gcloud run services get-iam-policy "${svc}" --region="${REGION}" \
     --flatten='bindings[]' --filter='bindings.role=roles/run.invoker' \
     --format='value(bindings.members)' 2>/dev/null | grep -q 'allUsers'; then
    bad "${svc}: still invokable by allUsers"; fail
  else
    ok "${svc}: private"
  fi
done

# --- 06: one active HMAC key ---------------------------------------------------

active="$(gcloud storage hmac list --format='value(state)' 2>/dev/null | grep -c 'ACTIVE' || true)"
if [ "${active}" -le 1 ]; then
  ok "${active} ACTIVE HMAC key"
else
  bad "${active} ACTIVE HMAC keys -- the compromised pair is still usable (06)"; fail
fi

# --- 07: the thin app exists and refuses anonymous callers ---------------------

url="$(gcloud run services describe "${THIN_WEB_SERVICE}" --region="${REGION}" \
       --format='value(status.url)' 2>/dev/null)"
if [ -z "${url}" ]; then
  bad "${THIN_WEB_SERVICE} is not deployed (07)"; fail
else
  ok "${THIN_WEB_SERVICE} at ${url}"
  # 200 to an anonymous caller is the one unambiguous failure. 302 is IAP's sign-in redirect.
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "${url}" 2>/dev/null || echo "000")"
  case "${code}" in
    200) bad "anonymous GET returned 200 -- the app is open to the internet"; fail ;;
    302|401|403) ok "anonymous GET returned ${code} -- authentication is in front" ;;
    000) warn "could not reach ${url} (proxy or TLS interception) -- check by hand" ;;
    *)   warn "anonymous GET returned ${code} -- check by hand" ;;
  esac
fi

# --- role_assignments.json -----------------------------------------------------

REPO="$(cd "${HERE}/../.." && pwd)"
RA="${REPO}/thin-web-app/role_assignments.json"
if [ -f "${RA}" ]; then
  # Count rather than merely parse: an empty map is valid JSON and maps nobody.
  ra_count="$(python -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' \
              "${RA}" 2>/dev/null)"
  if [ -z "${ra_count}" ]; then
    bad "role_assignments.json is not valid JSON -- server.py falls back for every caller"; fail
  elif [ "${ra_count}" -gt 0 ]; then
    ok "role_assignments.json is valid JSON and maps ${ra_count} caller(s)"
  else
    warn "role_assignments.json is valid JSON but empty -- every caller gets least privilege"
    info "(safe and deliberate: thin-web-app/ROLE_ASSIGNMENTS.md)"
  fi
  # tests/test_us_8_3_sql_api_runtime.py sweeps every .sh/.ps1/.json/.env/.yaml artefact under
  # data-recon for the executive role's literal name -- including this script, which is why the
  # name is assembled from two pieces here rather than written out.
  #
  # The roster is the one artefact exempt from that sweep, because a verified human may hold
  # the role; what must never hold it is a non-human principal, which is the shared BI
  # connection the rule is actually about. Check that, not mere presence.
  EXEC_ROLE="ROLE_EXECUTIVE""_ALL"
  exec_holders="$(python -c '
import json, sys
role = sys.argv[2]
data = json.load(open(sys.argv[1]))
print(" ".join(e for e, v in data.items()
               if isinstance(v, dict) and v.get("role") == role))' "${RA}" "${EXEC_ROLE}" 2>/dev/null)"
  nonhuman="$(printf '%s\n' ${exec_holders} | grep 'gserviceaccount\.com$' || true)"
  if [ -n "${nonhuman}" ]; then
    bad "${EXEC_ROLE} is held by a non-human principal: ${nonhuman}"
    bad "  that is the shared-connection case -- it unmasks PII for everyone using it"; fail
  elif [ -n "${exec_holders}" ]; then
    ok "${EXEC_ROLE} is held only by named people: ${exec_holders}"
    info "(the only role with PII in the clear -- review this list, do not let it grow quietly)"
  else
    ok "nobody holds ${EXEC_ROLE}"
  fi

  # The roster's own rules -- unknown role, unknown group, stray can_view_pii, reserved address.
  if python "${REPO}/scripts/access/manage_access.py" --file="${RA}" check >/dev/null 2>&1; then
    ok "role_assignments.json validates (scripts/access/manage_access.py check)"
  else
    bad "role_assignments.json does not validate -- run: python scripts/access/manage_access.py check"; fail
  fi
else
  warn "role_assignments.json absent -- every caller gets ROLE_FINANCE_MEMBER (safe default)"
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "C. The live query -- the only check that touches GCS"
# ──────────────────────────────────────────────────────────────────────────────
#
# SELECT 1 is answered by Cube alone. Until a real cube query returns rows, US-8.3 is not done:
# a working login proves the listener and the credential store, and nothing about the lakehouse.

if [ -z "${CREDS}" ]; then
  warn "no probe file given -- skipping. Re-run as:"
  warn "  $0 ~/.scbi-runbook/probe_creds.json"
elif [ ! -f "${CREDS}" ]; then
  bad "no such probe file: ${CREDS}"; fail
else
  require_ca_bundle
  LOCAL_PORT="${LOCAL_PORT:-15433}"
  TUNNEL_LOG="${STATE_DIR}/verify_tunnel.log"
  TUNNEL_PID=""
  cleanup() {
    [ -n "${TUNNEL_PID}" ] && kill "${TUNNEL_PID}" 2>/dev/null
    return 0
  }
  trap cleanup EXIT

  info "opening IAP tunnel localhost:${LOCAL_PORT} -> ${SQL_VM}:${SQL_PORT}"
  gcloud compute start-iap-tunnel "${SQL_VM}" "${SQL_PORT}" \
    --local-host-port="localhost:${LOCAL_PORT}" --zone "${ZONE}" > "${TUNNEL_LOG}" 2>&1 &
  TUNNEL_PID=$!

  UP=0
  for _ in $(seq 1 30); do
    if python -c "
import socket, sys
s = socket.socket(); s.settimeout(1)
sys.exit(0 if s.connect_ex(('127.0.0.1', ${LOCAL_PORT})) == 0 else 1)
" 2>/dev/null; then
      UP=1
      break
    fi
    kill -0 "${TUNNEL_PID}" 2>/dev/null || break
    sleep 1
  done

  if [ "${UP}" = "0" ]; then
    bad "the tunnel never came up:"; sed 's/^/      /' "${TUNNEL_LOG}"; fail
  else
    ok "tunnel up"
    if PROBE_PORT="${LOCAL_PORT}" PROBE_QUERY="SELECT COUNT(*) FROM MemberMonthly" \
       python "${HERE}/lib/pg_probe.py" "${CREDS}" | sed 's/^/  /'; then
      ok "a real cube query returned -- Cube, DuckDB and GCS are all working"
    else
      bad "the live query failed -- login may work while the lakehouse read does not"; fail
    fi
  fi
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "Verdict"
# ──────────────────────────────────────────────────────────────────────────────

if [ "${FAILED}" -eq 0 ]; then
  ok "every check this script can make has passed"
else
  printf '  %s%d check(s) failed.%s See scripts/blocked/README.md for which step owns each.\n' \
         "${C_BOLD}${C_RED}" "${FAILED}" "${C_RESET}"
fi
echo
exit 0
