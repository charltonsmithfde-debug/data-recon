#!/usr/bin/env bash
# US-2.1/US-2.2, the half that bites: rotate the platform credentials and move them out of
# plain environment variables into Secret Manager.
#
# THIS TAKES SERVICES DOWN. Read all of this before running it.
#
# WHAT ROTATES
#
#   CUBEJS_API_SECRET              new, 48 bytes of urlsafe entropy
#   ducklake_admin (Cloud SQL)     new password
#   metabase_admin (Cloud SQL)     new password
#
# WHAT DOES NOT
#
#   The GCS HMAC pair. It is *carried across*, not re-minted. The secret half is shown once at
#   creation and is never retrievable from GCS -- but it is recoverable from the SQL VM's
#   /etc/cube-sql.env, which is why stage 1 reads that file. Minting a new pair here would be a
#   third rotation nobody asked for, and would break the local web/*_engine.py until every
#   analyst re-ran setx. Retiring the OLD, compromised pair is 06's job and is a separate
#   decision.
#
# THE BUG THIS SCRIPT ALSO FIXES
#
#   scbi-cube has NEITHER CUBEJS_DB_DUCKDB_S3_* variable today (measured 2026-09-20), while
#   cube/cube.js:392-393 requireEnv()s both at module load. The currently deployed revision
#   predates that check. Any redeploy of scbi-cube that does not set them crash-loops the
#   container -- so this script sets them, and a plain `deploy_cube_rest_cloudrun.sh` run
#   without them would not.
#
# WHAT STAYS A PLAIN ENVIRONMENT VARIABLE, DELIBERATELY
#
#   CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID. It is the username half of the HMAC pair: an identifier,
#   printed by `gcloud storage hmac list`, logged on every bucket access. Only the secret half
#   is a secret.
#
# ORDER, AND WHY
#
#   Secret Manager versions are added BEFORE any service is redeployed, and Cloud SQL passwords
#   are changed BEFORE the services that use them. A service redeployed against a password that
#   has not been changed yet would come up healthy and then fail on first query, which is the
#   worst failure mode to debug. The window in which Cube and Metabase are down is the interval
#   between the Cloud SQL rotation and the end of their redeploys -- expect 5-10 minutes.
#
# Usage:
#   ./scripts/blocked/04_rotate_and_mount_secrets.sh [--yes] [--dry-run] [--include-vm]
#
#   --include-vm  also redeploy the Cube SQL VM with the new API secret, carrying its existing
#                 credential store across. Off by default: it is a second outage, on a runtime
#                 whose API secret no client actually presents (BI clients authenticate with
#                 CUBEJS_SQL_USERS, not a JWT). Leaving it out means the VM keeps the old API
#                 secret, which is a half-finished rotation -- do it, just do it knowingly.
set -uo pipefail

umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

REPO="$(cd "${HERE}/../.." && pwd)"

INCLUDE_VM=0
ARGS=()
for arg in "$@"; do
  case "${arg}" in
    --include-vm) INCLUDE_VM=1 ;;
    *)            ARGS+=("${arg}") ;;
  esac
done
parse_common_flags ${ARGS[@]+"${ARGS[@]}"}

require_gcloud
require_state_dir
require_ca_bundle

SEC_API="scbi-cube-api-secret"
SEC_HMAC="scbi-gcs-hmac-secret"
SEC_DUCKLAKE="scbi-ducklake-catalog-password"
SEC_METABASE="scbi-metabase-db-password"

RECOVERED_ENV="${STATE_DIR}/cube-sql.env.recovered"
ROTATION_LOG="${STATE_DIR}/rotation_$(date +%Y%m%d-%H%M%S).txt"

cleanup() {
  [ -f "${RECOVERED_ENV}" ] && { rm -f "${RECOVERED_ENV}"; info "removed ${RECOVERED_ENV}"; }
}
trap cleanup EXIT

gcloud services list --enabled --filter='config.name:secretmanager.googleapis.com' \
  --format='value(config.name)' 2>/dev/null | grep -q secretmanager \
  || die "Secret Manager is not enabled. Run 03_enable_secret_manager.sh first."

# ──────────────────────────────────────────────────────────────────────────────
heading "1. Recover the HMAC pair from the SQL VM"
# ──────────────────────────────────────────────────────────────────────────────

if [ "${DRY_RUN:-0}" = "1" ]; then
  info "(--dry-run) would read /etc/cube-sql.env from ${SQL_VM}"
else
  gcloud compute ssh "${SQL_VM}" --zone "${ZONE}" --tunnel-through-iap \
    --command="sudo cat /etc/cube-sql.env" > "${RECOVERED_ENV}" 2>"${STATE_DIR}/ssh.err" || {
      sed 's/^/      /' "${STATE_DIR}/ssh.err" >&2
      die "Could not read /etc/cube-sql.env -- without it the HMAC secret is unrecoverable and
       this rotation would have to mint a new pair. Fix the access first (a TLS failure means
       a stale CA bundle: re-run 00_export_ca_bundle.ps1)."
    }
  chmod 600 "${RECOVERED_ENV}" 2>/dev/null || true

  for key in CUBEJS_API_SECRET CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID \
             CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY CUBEJS_SQL_USERS; do
    grep -q "^${key}=." "${RECOVERED_ENV}" || die "${key} is absent from the deployed env file."
  done
  ok "HMAC pair and current API secret recovered"

  # Report the CURRENT secret's length rather than asserting it. cube.js:188 enforces a 32-byte
  # floor, so anything under that means the running revision predates the check.
  CUR_LEN="$(awk -F= '/^CUBEJS_API_SECRET=/ { print length($2) }' "${RECOVERED_ENV}")"
  if [ "${CUR_LEN:-0}" -lt 32 ]; then
    warn "the current CUBEJS_API_SECRET is ${CUR_LEN} bytes -- under the RFC 7518 s3.2 floor"
  else
    info "the current CUBEJS_API_SECRET is ${CUR_LEN} bytes"
  fi
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "2. Generate the new values"
# ──────────────────────────────────────────────────────────────────────────────

gen() { python -c "import secrets; print(secrets.token_urlsafe($1))"; }

if [ "${DRY_RUN:-0}" = "1" ]; then
  info "(--dry-run) would generate a 48-byte API secret and two Cloud SQL passwords"
  NEW_API="dry-run"; NEW_DUCKLAKE="dry-run"; NEW_METABASE="dry-run"
else
  NEW_API="$(gen 48)"      || die "could not generate the API secret"
  NEW_DUCKLAKE="$(gen 32)" || die "could not generate the ducklake_admin password"
  NEW_METABASE="$(gen 32)" || die "could not generate the metabase_admin password"
  [ "${#NEW_API}" -ge 32 ] || die "generated API secret is too short -- refusing to proceed"
  ok "new API secret: ${#NEW_API} bytes"
  ok "new Cloud SQL passwords generated"
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "3. Confirm -- this is the outage"
# ──────────────────────────────────────────────────────────────────────────────

confirm "About to rotate live credentials and redeploy:
  - CUBEJS_API_SECRET                 new (invalidates every JWT already issued)
  - Cloud SQL ducklake_admin          new password
  - Cloud SQL metabase_admin          new password
  - ${CUBE_SERVICE} and ${METABASE_SERVICE} redeployed against Secret Manager
$( [ "${INCLUDE_VM}" = "1" ] && echo "  - ${SQL_VM} redeployed with the new API secret" )
  Cube and Metabase are UNAVAILABLE until their redeploys finish (5-10 minutes).
  The GCS HMAC pair is carried across unchanged."

# ──────────────────────────────────────────────────────────────────────────────
heading "4. Write the secret versions"
# ──────────────────────────────────────────────────────────────────────────────
#
# Values reach gcloud on stdin via --data-file=-, never as --data-file with a temp file and
# never on a command line: an argument is world-readable in the process table.

add_version() {
  local name="$1" value="$2"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    info "(--dry-run) would add a version to ${name}"
    return 0
  fi
  printf '%s' "${value}" | gcloud secrets versions add "${name}" --data-file=- >/dev/null \
    && ok "${name}: new version added" \
    || die "could not add a version to ${name} -- nothing has been redeployed yet, so the
       platform is still consistent. Fix the permission and re-run."
}

add_version "${SEC_API}"      "${NEW_API}"
add_version "${SEC_DUCKLAKE}" "${NEW_DUCKLAKE}"
add_version "${SEC_METABASE}" "${NEW_METABASE}"

if [ "${DRY_RUN:-0}" = "1" ]; then
  info "(--dry-run) would copy the recovered HMAC secret into ${SEC_HMAC}"
else
  awk -F'=' '/^CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY=/ { sub(/^[^=]*=/, ""); print }' \
    "${RECOVERED_ENV}" | tr -d '\r\n' | \
    gcloud secrets versions add "${SEC_HMAC}" --data-file=- >/dev/null \
    && ok "${SEC_HMAC}: carried across from the VM" \
    || die "could not store the HMAC secret"
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "5. Rotate the Cloud SQL passwords"
# ──────────────────────────────────────────────────────────────────────────────
#
# From here until the redeploys finish, Cube and Metabase are talking to the catalog with a
# password that no longer works. This is the outage window.

set_sql_password() {
  local user="$1" value="$2"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    info "(--dry-run) would set the password for ${user}"
    return 0
  fi
  gcloud sql users set-password "${user}" \
    --instance="${CLOUD_SQL_INSTANCE}" --password="${value}" >/dev/null 2>&1 \
    && ok "${user}: password rotated" \
    || die "could not rotate ${user}. Secret Manager already holds the new value, so re-running
       this script would generate a THIRD password. Instead: set ${user}'s password by hand to
       the latest version of the matching secret, then continue from stage 6."
}

set_sql_password ducklake_admin "${NEW_DUCKLAKE}"
set_sql_password metabase_admin "${NEW_METABASE}"

# ──────────────────────────────────────────────────────────────────────────────
heading "6. Redeploy ${CUBE_SERVICE} against Secret Manager"
# ──────────────────────────────────────────────────────────────────────────────
#
# --set-secrets replaces the plain values; --update-env-vars carries the non-secret settings,
# including the HMAC access id that the current revision is missing entirely.

HMAC_ACCESS_ID=""
if [ "${DRY_RUN:-0}" != "1" ]; then
  HMAC_ACCESS_ID="$(awk -F'=' '/^CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID=/ { sub(/^[^=]*=/, ""); print }' \
                    "${RECOVERED_ENV}" | tr -d '\r\n')"
  [ -n "${HMAC_ACCESS_ID}" ] || die "no HMAC access id recovered"
fi

run gcloud run services update "${CUBE_SERVICE}" \
  --region="${REGION}" \
  --set-secrets="CUBEJS_API_SECRET=${SEC_API}:latest,CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY=${SEC_HMAC}:latest,DUCKLAKE_CATALOG_PASSWORD=${SEC_DUCKLAKE}:latest" \
  --update-env-vars="CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID=${HMAC_ACCESS_ID}" \
  || die "the ${CUBE_SERVICE} update failed. Cloud Run keeps serving the previous revision, but
       that revision now holds a Cloud SQL password that has been rotated away -- so Cube is
       down until this succeeds. Read the error and re-run stage 6."
ok "${CUBE_SERVICE} updated"

# ──────────────────────────────────────────────────────────────────────────────
heading "7. Redeploy ${METABASE_SERVICE} against Secret Manager"
# ──────────────────────────────────────────────────────────────────────────────

run gcloud run services update "${METABASE_SERVICE}" \
  --region="${REGION}" \
  --set-secrets="MB_DB_PASS=${SEC_METABASE}:latest" \
  || die "the ${METABASE_SERVICE} update failed. Metabase is down until this succeeds."
ok "${METABASE_SERVICE} updated"

# ──────────────────────────────────────────────────────────────────────────────
heading "8. The SQL VM"
# ──────────────────────────────────────────────────────────────────────────────

if [ "${INCLUDE_VM}" = "1" ]; then
  if [ "${DRY_RUN:-0}" = "1" ]; then
    info "(--dry-run) would redeploy ${SQL_VM} with the new API secret"
  else
    info "redeploying ${SQL_VM}, carrying its existing credential store across"
    (
      set -a
      # shellcheck disable=SC1090
      . "${RECOVERED_ENV}"
      set +a
      export CUBEJS_API_SECRET="${NEW_API}"
      cd "${REPO}" && ./cube/deploy_cube_sql_vm.sh
    ) || die "the VM redeploy failed. It is still serving with the OLD API secret; every BI
       connection is unaffected, because those authenticate with CUBEJS_SQL_USERS."
    ok "${SQL_VM} redeployed"
  fi
else
  warn "${SQL_VM} still holds the OLD API secret -- re-run with --include-vm to finish the"
  warn "rotation. No client is affected meanwhile: SQL clients authenticate with the user"
  warn "store, not a JWT."
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "9. What is left for a human"
# ──────────────────────────────────────────────────────────────────────────────

{
  echo "Rotation $(date -Iseconds)"
  echo "  ${SEC_API}       new version"
  echo "  ${SEC_DUCKLAKE}  new version, ducklake_admin rotated"
  echo "  ${SEC_METABASE}  new version, metabase_admin rotated"
  echo "  ${SEC_HMAC}      carried across from ${SQL_VM}, NOT rotated"
  echo "  VM redeployed:   $( [ "${INCLUDE_VM}" = "1" ] && echo yes || echo no )"
} > "${ROTATION_LOG}"
chmod 600 "${ROTATION_LOG}" 2>/dev/null || true
info "record: ${ROTATION_LOG} (no values in it)"
echo

info "1. The local reconciliation engines read the HMAC pair from the user environment"
info "   (web/member_engine.py:25-26 and its siblings). The pair did NOT rotate, so they keep"
info "   working. If you ever do rotate it, each analyst needs, in PowerShell, once:"
info "     setx CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID \"<access id>\""
info "     setx CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY \"<secret>\""
info "   setx writes the user environment permanently; a new shell is needed to see it."
echo
info "2. thin-web-app/server.py:42 also requires CUBEJS_API_SECRET. It is not deployed yet"
info "   (07_deploy_thin_web.sh); when it is, mount ${SEC_API} rather than passing a value."
echo
info "3. Verify:  ./scripts/blocked/99_verify.sh"
echo
