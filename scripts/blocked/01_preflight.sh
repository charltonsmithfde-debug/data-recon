#!/usr/bin/env bash
# Read-only state report. Changes nothing; run it before and after anything else in this
# directory. Every line it prints is measured, not assumed -- the whole reason this file exists
# is that three sessions in a row inherited claims about GCP that had never been checked.
#
# Usage:  ./scripts/blocked/01_preflight.sh
set -uo pipefail          # deliberately not -e: a failing probe is a finding, not an abort

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

require_gcloud

FINDINGS=0
note_open() { FINDINGS=$((FINDINGS + 1)); }

# ──────────────────────────────────────────────────────────────────────────────
heading "Compute -- the Cube SQL runtime"
# ──────────────────────────────────────────────────────────────────────────────

vm_status="$(gcloud compute instances describe "${SQL_VM}" --zone "${ZONE}" \
             --format='value(status)' 2>/dev/null)"
if [ "${vm_status}" = "RUNNING" ]; then
  ok "${SQL_VM} is RUNNING in ${ZONE}"
else
  bad "${SQL_VM} is '${vm_status:-absent}', expected RUNNING"; note_open
fi

# The GCP firewall rule is necessary but not sufficient: Container-Optimized OS ships a
# default-DROP host firewall that allows only port 22 and established flows. A rule here with a
# closed host firewall is exactly the state that made the port look open for a whole session.
if gcloud compute firewall-rules describe allow-scbi-cube-sql --format='value(name)' >/dev/null 2>&1; then
  ok "firewall rule allow-scbi-cube-sql exists (GCP layer only -- see 02 for the host layer)"
else
  bad "firewall rule allow-scbi-cube-sql is missing"; note_open
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "Cloud Run -- what is deployed and who can invoke it"
# ──────────────────────────────────────────────────────────────────────────────

services="$(gcloud run services list --region "${REGION}" --format='value(metadata.name)' 2>/dev/null)"
info "services: $(echo "${services}" | tr '\n' ' ')"

for svc in "${CUBE_SERVICE}" "${METABASE_SERVICE}"; do
  if ! echo "${services}" | grep -qx "${svc}"; then
    warn "${svc} not deployed"
    continue
  fi
  members="$(gcloud run services get-iam-policy "${svc}" --region "${REGION}" \
             --flatten='bindings[]' --filter='bindings.role=roles/run.invoker' \
             --format='value(bindings.members)' 2>/dev/null)"
  if echo "${members}" | grep -q 'allUsers'; then
    bad "${svc}: roles/run.invoker includes allUsers -- open to the internet"; note_open
  else
    ok "${svc}: no allUsers on roles/run.invoker"
  fi
done

if echo "${services}" | grep -qx "${THIN_WEB_SERVICE}"; then
  ok "${THIN_WEB_SERVICE} is deployed"
else
  bad "${THIN_WEB_SERVICE} does not exist -- the thin app's 26-test auth gate protects nothing"; note_open
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "Secrets"
# ──────────────────────────────────────────────────────────────────────────────

if gcloud services list --enabled --filter='config.name:secretmanager.googleapis.com' \
   --format='value(config.name)' 2>/dev/null | grep -q secretmanager; then
  ok "secretmanager.googleapis.com is enabled"
  secrets="$(gcloud secrets list --format='value(name)' 2>/dev/null | tr '\n' ' ')"
  info "secrets: ${secrets:-(none)}"
else
  bad "secretmanager.googleapis.com is SERVICE_DISABLED -- secrets are plain env vars"; note_open
fi

# Access ids are identifiers, not secrets -- the secret half is shown once at creation and is
# never retrievable. Printing state and creation time is safe and is the only way to tell the
# two pairs apart.
heading "GCS HMAC keys"
hmac="$(gcloud storage hmac list --format='value(accessId,state)' 2>/dev/null)"
active_count="$(echo "${hmac}" | grep -c 'ACTIVE' || true)"
echo "${hmac}" | while read -r id state; do
  [ -n "${id}" ] || continue
  info "${id:0:12}...${id: -4}  ${state}"
done
if [ "${active_count}" -gt 1 ]; then
  bad "${active_count} HMAC keys are ACTIVE -- the compromised pair is still usable"; note_open
else
  ok "one ACTIVE HMAC key"
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "Cloud SQL -- the DuckLake catalog"
# ──────────────────────────────────────────────────────────────────────────────

tier="$(gcloud sql instances describe "${CLOUD_SQL_INSTANCE}" \
        --format='value(settings.tier)' 2>/dev/null)"
if [ -n "${tier}" ]; then
  ok "${CLOUD_SQL_INSTANCE} exists, tier ${tier}"
  info "users: $(gcloud sql users list --instance "${CLOUD_SQL_INSTANCE}" \
                 --format='value(name)' 2>/dev/null | tr '\n' ' ')"
else
  bad "${CLOUD_SQL_INSTANCE} not found"; note_open
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "Repository state"
# ──────────────────────────────────────────────────────────────────────────────

REPO="$(cd "${HERE}/../.." && pwd)"

# Presence alone proves nothing: the file ships as an empty map, which is valid, safe and
# means nobody is mapped. Report the count, so "present" cannot read as "done".
RA_FILE="${REPO}/thin-web-app/role_assignments.json"
if [ -f "${RA_FILE}" ]; then
  ra_count="$(python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d))' \
              "${RA_FILE}" 2>/dev/null)"
  if [ -z "${ra_count}" ]; then
    bad "thin-web-app/role_assignments.json is not valid JSON -- server.py falls back for every caller"; note_open
  elif [ "${ra_count}" -gt 0 ]; then
    ok "thin-web-app/role_assignments.json maps ${ra_count} caller(s)"
  else
    warn "thin-web-app/role_assignments.json is an empty map -- every caller gets least privilege"
    info "(safe, and deliberate: see thin-web-app/ROLE_ASSIGNMENTS.md)"
  fi
else
  warn "thin-web-app/role_assignments.json absent -- every caller gets least privilege (safe)"
fi

if grep -q "requireEnv('CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID')" "${REPO}/cube/cube.js" 2>/dev/null; then
  info "cube.js requires the GCS HMAC pair at module load -- any runtime without it crash-loops"
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "Summary"
# ──────────────────────────────────────────────────────────────────────────────

if [ "${FINDINGS}" -eq 0 ]; then
  ok "nothing outstanding at the infrastructure layer"
else
  printf '  %s%d open finding(s).%s Work them in the order in scripts/blocked/README.md.\n' \
         "${C_BOLD}" "${FINDINGS}" "${C_RESET}"
fi
echo
exit 0
