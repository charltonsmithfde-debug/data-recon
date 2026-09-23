#!/usr/bin/env bash
# Re-mint the Cube SQL credential store and redeploy the VM -- the fix when 02 says the probe
# plaintext does not match the deployed digests, or when the plaintext is simply gone.
#
# THE TRAP THIS SCRIPT EXISTS TO AVOID
#
# cube/deploy_cube_sql_vm.sh requires four values from the environment and defaults none of them
# (US-2.2, deploy_cube_sql_vm.sh:51-54): CUBEJS_API_SECRET, both halves of the GCS HMAC pair, and
# CUBEJS_SQL_USERS. Three of those were only ever in a session transcript, and a GCS HMAC secret
# is shown once at creation and is never retrievable afterwards. Re-running the deploy blind
# therefore forces minting a fresh HMAC pair *and* a fresh API secret -- rotating two live
# credentials to fix a third, and breaking DuckDB's lakehouse reads on the way past.
#
# The way out: the container runs with `--env-file /etc/cube-sql.env`
# (deploy_cube_sql_vm.sh:252), and cloud-init wrote all four values into that file on the
# instance. They are recoverable. So this script carries the other three across untouched and
# rotates ONLY the SQL user store.
#
# WHY IT GOES THROUGH deploy_cube_sql_vm.sh RATHER THAN EDITING THE LIVE FILE
#
# Editing /etc/cube-sql.env in place would work until the next `gcloud compute instances reset`,
# at which point cloud-init rewrites it from the instance metadata and the change vanishes. The
# deploy script rewrites that metadata, so the rotation survives a reset. It also installs the
# iptables ExecStartPre (deploy_cube_sql_vm.sh:251) that keeps 5432 open across a reboot -- COS
# is default-DROP, and the rule on the live VM today was added by hand and is runtime-only.
#
# WHAT IT COSTS
#
# Every existing BI connection stops authenticating the moment the new store is live. Metabase
# and Power BI must be updated with the passwords this prints. Nothing else rotates: the API
# secret, the HMAC pair and the lakehouse are untouched.
#
# Usage:
#   ./scripts/blocked/02b_remint_sql_users.sh [--yes] [--dry-run] [connection ...]
#
#   With no connection names, mints the default set. Names are the short keys in
#   cube/mint_sql_users.js (member, investments, ...). The executive role is deliberately not
#   among them -- see the header of that file. A shared BI connection holding it would defeat
#   every mask in SharedDimensions.js, which is why tests/test_us_8_3_sql_api_runtime.py sweeps
#   every deploy artefact for that role's name and fails the suite on a hit.
set -uo pipefail

# Everything this script writes holds credential material.
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

REPO="$(cd "${HERE}/../.." && pwd)"

parse_common_flags "$@"
CONNECTIONS=()
[ "${#REMAINING_ARGS[@]}" -eq 0 ] || CONNECTIONS=("${REMAINING_ARGS[@]}")

require_gcloud
require_state_dir
require_ca_bundle

RECOVERED_ENV="${STATE_DIR}/cube-sql.env.recovered"
MINT_OUT="${STATE_DIR}/mint_$(date +%Y%m%d-%H%M%S).txt"
PROBE_CREDS="${STATE_DIR}/probe_creds.json"
STORE_LINE=""

# The recovered env file holds the API secret and the HMAC secret in the clear. It exists for the
# length of this script and no longer, however the script exits.
cleanup() {
  if [ -f "${RECOVERED_ENV}" ]; then
    rm -f "${RECOVERED_ENV}"
    info "removed ${RECOVERED_ENV}"
  fi
}
trap cleanup EXIT

# ──────────────────────────────────────────────────────────────────────────────
heading "1. Recover the three values that must NOT rotate"
# ──────────────────────────────────────────────────────────────────────────────

info "reading /etc/cube-sql.env from ${SQL_VM}"

if [ "${DRY_RUN:-0}" = "1" ]; then
  info "(--dry-run) would: gcloud compute ssh ${SQL_VM} --command='sudo cat /etc/cube-sql.env'"
else
  gcloud compute ssh "${SQL_VM}" --zone "${ZONE}" --tunnel-through-iap \
    --command="sudo cat /etc/cube-sql.env" > "${RECOVERED_ENV}" 2>"${STATE_DIR}/ssh.err" || {
      sed 's/^/      /' "${STATE_DIR}/ssh.err" >&2
      die "Could not read /etc/cube-sql.env.
       If this is a TLS failure, the CA bundle is stale -- re-run 00_export_ca_bundle.ps1.
       If the VM is gone, there is nothing to carry over and a full re-provision (new HMAC
       pair, new API secret) is the only route; that is a bigger decision than this script."
    }
  chmod 600 "${RECOVERED_ENV}" 2>/dev/null || true

  # Fail before anything is minted if a carried-over value is missing. A partial carry-over would
  # deploy a container that crash-loops on cube.js's requireEnv (cube/cube.js:392-393).
  MISSING=0
  for key in CUBEJS_API_SECRET CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY; do
    if grep -q "^${key}=." "${RECOVERED_ENV}"; then
      ok "${key} recovered"
    else
      bad "${key} is absent or empty in the recovered file"
      MISSING=1
    fi
  done
  [ "${MISSING}" = "0" ] || die "The deployed env file is not complete enough to carry over.
       Do not proceed: a redeploy from here would crash-loop the container."

  info "$(grep -c '=' "${RECOVERED_ENV}") variables recovered (values not shown)"
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "2. Mint a new credential store"
# ──────────────────────────────────────────────────────────────────────────────

command -v node >/dev/null 2>&1 || die "node is not on PATH; mint_sql_users.js needs it."

if [ "${DRY_RUN:-0}" = "1" ]; then
  info "(--dry-run) would: node cube/mint_sql_users.js ${CONNECTIONS[*]:-}"
else
  ( cd "${REPO}" && node cube/mint_sql_users.js "${CONNECTIONS[@]}" ) > "${MINT_OUT}" 2>&1 || {
    sed 's/^/      /' "${MINT_OUT}" >&2
    die "mint_sql_users.js failed. Nothing has changed."
  }
  chmod 600 "${MINT_OUT}" 2>/dev/null || true

  # The store is the one line that is JSON; everything else mint_sql_users.js prints is a comment.
  STORE_LINE="$(grep -v '^#' "${MINT_OUT}" | grep '^{' | head -1)"
  [ -n "${STORE_LINE}" ] || die "No credential store found in ${MINT_OUT}."

  # Turn the transcript's plaintext block into the probe file 02_diagnose_sql_login.sh consumes,
  # so the rotation can be verified without anyone retyping a password. Generated passwords are
  # base64url (mint_sql_users.js:74), so no JSON escaping is needed.
  awk '
    /^#[[:space:]]+user:/     { u = $3 }
    /^#[[:space:]]+password:/ { printf "%s\"%s\": \"%s\"", (n++ ? ",\n  " : "{\n  "), u, $3 }
    END                       { print (n ? "\n}" : "{}") }
  ' "${MINT_OUT}" > "${PROBE_CREDS}"
  chmod 600 "${PROBE_CREDS}" 2>/dev/null || true

  USER_COUNT="$(grep -c '^#[[:space:]]\+user:' "${MINT_OUT}")"
  [ "${USER_COUNT}" -gt 0 ] || die "The transcript has no plaintext block; ${PROBE_CREDS} would be empty."
  ok "${USER_COUNT} connection(s) minted"
  info "transcript:  ${MINT_OUT}"
  info "probe file:  ${PROBE_CREDS}"
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "3. Confirm"
# ──────────────────────────────────────────────────────────────────────────────

confirm "This redeploys ${SQL_VM} with a NEW SQL credential store.
  Every current Metabase and Power BI connection to Cube SQL stops working until it is
  updated with the passwords in ${MINT_OUT}.
  The API secret, the GCS HMAC pair and the lakehouse are NOT touched."

# ──────────────────────────────────────────────────────────────────────────────
heading "4. Redeploy"
# ──────────────────────────────────────────────────────────────────────────────

if [ "${DRY_RUN:-0}" = "1" ]; then
  info "(--dry-run) would: cd ${REPO} && ./cube/deploy_cube_sql_vm.sh"
else
  # A subshell, so the recovered secrets live in this process tree and no further. They reach the
  # deploy script as exported variables and never as arguments: a command line is world-readable
  # in the process table of a shared machine.
  (
    set -a
    # shellcheck disable=SC1090
    . "${RECOVERED_ENV}"
    set +a
    export CUBEJS_SQL_USERS="${STORE_LINE}"
    cd "${REPO}" && ./cube/deploy_cube_sql_vm.sh
  ) || die "The redeploy failed. The VM is still serving the OLD store, so nothing is broken --
       the new passwords in ${MINT_OUT} are simply not live. Read the error above and re-run."
  ok "redeployed"
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "5. What to do now"
# ──────────────────────────────────────────────────────────────────────────────

info "1. Verify the rotation end to end:"
info "     ./scripts/blocked/02_diagnose_sql_login.sh ${PROBE_CREDS}"
info "2. Update every BI connection from the transcript at ${MINT_OUT}:"
info "     Metabase  -- one database entry per role"
info "     Power BI  -- the PostgreSQL connection's stored credential"
info "3. Prove the lakehouse half, which SELECT 1 never touches:"
info "     PROBE_QUERY='SELECT COUNT(*) FROM MemberMonthly' \\"
info "       python ${HERE}/lib/pg_probe.py ${PROBE_CREDS}"
info "4. Then delete the transcript and the probe file:"
info "     rm -f ${MINT_OUT} ${PROBE_CREDS}"
echo
