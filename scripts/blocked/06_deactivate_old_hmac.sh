#!/usr/bin/env bash
# Retire the compromised GCS HMAC key -- by DEACTIVATING it, never by deleting it.
#
# WHY DEACTIVATE AND NOT DELETE
#
# Deactivation is reversible in seconds (`gcloud storage hmac update --activate`). Deletion is
# final: the access id and its secret are gone, and if anything unlisted was still using the
# pair there is no way back except minting a new one and finding every consumer under an
# outage. The security benefit is identical -- a deactivated key authenticates nothing.
#
# This is the whole argument for the decision recorded in
# docs/adr/0002-outstanding-decisions.md. A key that is deactivated and demonstrably unused for
# a week can be deleted later, deliberately, by someone who no longer has to guess.
#
# WHAT READS THE OLD PAIR TODAY
#
# Measured 2026-09-20: nothing deployed. scbi-cube has no CUBEJS_DB_DUCKDB_S3_* variables at
# all, and the SQL VM's /etc/cube-sql.env holds the NEW pair. The only consumers are the local
# reconciliation engines (web/member_engine.py:25-26 and its siblings), which read whatever is
# in the analyst's user environment -- so an analyst still on the old pair is exactly the case
# this script must not silently break.
#
# The old key's secret is committed to the repository's history, which is what makes it
# compromised. Its access id is an identifier, not a secret; printing it is safe, and
# `gcloud storage hmac list` prints it to anyone with project read access anyway.
#
# Usage:
#   ./scripts/blocked/06_deactivate_old_hmac.sh [--yes] [--dry-run] <access-id>
#   ./scripts/blocked/06_deactivate_old_hmac.sh --rollback <access-id>
#   ./scripts/blocked/06_deactivate_old_hmac.sh --list
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

ROLLBACK=0
LIST_ONLY=0
ARGS=()
for arg in "$@"; do
  case "${arg}" in
    --rollback) ROLLBACK=1 ;;
    --list)     LIST_ONLY=1 ;;
    *)          ARGS+=("${arg}") ;;
  esac
done
parse_common_flags ${ARGS[@]+"${ARGS[@]}"}

require_gcloud

# ──────────────────────────────────────────────────────────────────────────────
heading "HMAC keys on ${PROJECT_ID}"
# ──────────────────────────────────────────────────────────────────────────────

HMAC="$(gcloud storage hmac list --format='value(accessId,state,serviceAccountEmail,timeCreated)' 2>/dev/null)"
[ -n "${HMAC}" ] || die "No HMAC keys found, or no permission to list them."

ACTIVE=0
while read -r id state sa created; do
  [ -n "${id}" ] || continue
  [ "${state}" = "ACTIVE" ] && ACTIVE=$((ACTIVE + 1))
  printf '  %-4s %s  %s  %s\n' "${state}" "${id}" "${sa}" "${created}"
done <<< "${HMAC}"

echo
if [ "${ACTIVE}" -gt 1 ]; then
  bad "${ACTIVE} keys are ACTIVE -- the compromised pair is still usable"
else
  ok "${ACTIVE} key ACTIVE"
fi

if [ "${LIST_ONLY}" = "1" ]; then
  echo
  info "Older timeCreated is the compromised pair. Deactivate it with:"
  info "  $0 <access-id>"
  echo
  exit 0
fi

ACCESS_ID="${REMAINING_ARGS[0]:-}"
[ -n "${ACCESS_ID}" ] || die "Usage: $0 [--rollback] <access-id>    ($0 --list to see them)"

echo "${HMAC}" | grep -q "^${ACCESS_ID}[[:space:]]" \
  || die "No HMAC key with access id ${ACCESS_ID} on this project."

CURRENT_STATE="$(echo "${HMAC}" | awk -v id="${ACCESS_ID}" '$1 == id { print $2 }')"

# ──────────────────────────────────────────────────────────────────────────────
if [ "${ROLLBACK}" = "1" ]; then
# ──────────────────────────────────────────────────────────────────────────────
  heading "Rollback -- re-activate ${ACCESS_ID}"

  if [ "${CURRENT_STATE}" = "ACTIVE" ]; then
    ok "already ACTIVE -- nothing to do"
    exit 0
  fi
  confirm "Re-activate ${ACCESS_ID}?
  This makes a key whose secret is in the repository's history usable again.
  Only do this to restore service while a real fix is prepared."
  run gcloud storage hmac update "${ACCESS_ID}" --activate >/dev/null \
    || die "could not re-activate ${ACCESS_ID}"
  ok "${ACCESS_ID} is ACTIVE again"
  echo
  exit 0
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "Deactivate ${ACCESS_ID}"
# ──────────────────────────────────────────────────────────────────────────────

if [ "${CURRENT_STATE}" = "INACTIVE" ]; then
  ok "${ACCESS_ID} is already INACTIVE -- nothing to do"
  echo
  exit 0
fi

if [ "${ACTIVE}" -le 1 ]; then
  die "${ACCESS_ID} is the ONLY active key. Deactivating it stops every DuckDB read of the
       lakehouse. Mint and deploy a replacement pair before retiring this one."
fi

warn "Anyone still holding the old pair in their user environment loses lakehouse access."
warn "Check first: the local engines read CUBEJS_DB_DUCKDB_S3_* from the user environment,"
warn "so an analyst who has not re-run setx since the new pair was minted is on the old one."

confirm "Deactivate ${ACCESS_ID}?
  Reversible: $0 --rollback ${ACCESS_ID}
  The key is NOT deleted -- deletion is final and is a separate, later decision."

run gcloud storage hmac update "${ACCESS_ID}" --deactivate >/dev/null \
  || die "could not deactivate ${ACCESS_ID}"
ok "${ACCESS_ID} is INACTIVE"

# ──────────────────────────────────────────────────────────────────────────────
heading "Verify"
# ──────────────────────────────────────────────────────────────────────────────

info "1. A real lakehouse read must still work -- SELECT 1 does not touch GCS:"
info "     PROBE_QUERY='SELECT COUNT(*) FROM MemberMonthly' \\"
info "       python ${HERE}/lib/pg_probe.py <probe_creds.json>"
info "2. Then the board:  ./scripts/blocked/01_preflight.sh"
echo
info "If something broke:  $0 --rollback ${ACCESS_ID}"
echo
info "Once a week has passed with nothing broken, deleting the key is safe -- but that is a"
info "deliberate act, not a step in this runbook."
echo
