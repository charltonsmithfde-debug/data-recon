#!/usr/bin/env bash
# US-1.3: take both Cloud Run services off the public internet.
#
# Measured 2026-09-20: BOTH scbi-cube AND scbi-metabase have allUsers on roles/run.invoker.
# Every note before that session pinned this on scbi-cube alone. Metabase is the more serious
# of the two -- it is a login UI sitting directly over the warehouse, so an unauthenticated
# caller reaches a credential prompt backed by real data rather than an API that at least wants
# a signed token.
#
# THE ORDER MATTERS AND IS NOT NEGOTIABLE
#
# Removing allUsers before granting the real invokers takes the platform down for everyone,
# including the people who are meant to have access. This script therefore grants first and
# revokes second, and refuses to revoke if the grant list is empty -- an empty list plus a
# revoke is an outage with no way back in except another IAM change.
#
# WHO THE REAL INVOKERS ARE
#
#   scbi-cube      the thin web app's runtime service account, which mints an ID token per
#                  request. Not a human: nobody should be calling the Cube REST API by hand.
#   scbi-metabase  the people who use Metabase, plus IAP once 07 is in place.
#
# Pass them explicitly. There is no default list, because guessing one here would either grant
# too much or lock somebody out.
#
# Usage:
#   ./scripts/blocked/05_lock_down_cloud_run.sh [--yes] [--dry-run] \
#       --cube-invoker=serviceAccount:... [--cube-invoker=...] \
#       --metabase-invoker=user:someone@sanlam.co.za [--metabase-invoker=...]
#
#   --skip-metabase   lock down scbi-cube only (for staging the change over two windows)
#   --skip-cube       lock down scbi-metabase only
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

CUBE_INVOKERS=()
METABASE_INVOKERS=()
SKIP_CUBE=0
SKIP_METABASE=0
ARGS=()

for arg in "$@"; do
  case "${arg}" in
    --cube-invoker=*)     CUBE_INVOKERS+=("${arg#*=}") ;;
    --metabase-invoker=*) METABASE_INVOKERS+=("${arg#*=}") ;;
    --skip-cube)          SKIP_CUBE=1 ;;
    --skip-metabase)      SKIP_METABASE=1 ;;
    *)                    ARGS+=("${arg}") ;;
  esac
done
parse_common_flags ${ARGS[@]+"${ARGS[@]}"}

require_gcloud

# ──────────────────────────────────────────────────────────────────────────────
# One service, granted then revoked.
# ──────────────────────────────────────────────────────────────────────────────

lock_down() {
  local svc="$1"; shift
  local invokers=("$@")

  heading "${svc}"

  if ! gcloud run services describe "${svc}" --region="${REGION}" \
       --format='value(metadata.name)' >/dev/null 2>&1; then
    warn "${svc} is not deployed -- nothing to lock down"
    return 0
  fi

  local current
  current="$(gcloud run services get-iam-policy "${svc}" --region="${REGION}" \
             --flatten='bindings[]' --filter='bindings.role=roles/run.invoker' \
             --format='value(bindings.members)' 2>/dev/null)"

  if ! echo "${current}" | grep -q 'allUsers'; then
    ok "${svc}: no allUsers binding -- already private"
    info "current invokers: $(echo "${current}" | tr '\n;' '  ')"
    return 0
  fi

  bad "${svc}: allUsers can invoke this service"
  info "current invokers: $(echo "${current}" | tr '\n;' '  ')"

  # The refusal that prevents a self-inflicted outage.
  if [ "${#invokers[@]}" -eq 0 ]; then
    warn "No invoker given for ${svc}, so removing allUsers would lock everyone out."
    warn "Re-run with, for example:"
    case "${svc}" in
      "${CUBE_SERVICE}")     warn "  --cube-invoker=serviceAccount:${COMPUTE_SA}" ;;
      "${METABASE_SERVICE}") warn "  --metabase-invoker=user:you@sanlam.co.za" ;;
    esac
    return 1
  fi

  info "granting roles/run.invoker to ${#invokers[@]} principal(s) FIRST"
  local member
  for member in "${invokers[@]}"; do
    run gcloud run services add-iam-policy-binding "${svc}" \
      --region="${REGION}" --member="${member}" --role=roles/run.invoker >/dev/null \
      || die "could not grant ${member} on ${svc}. allUsers is still in place, so nothing is
       down. Fix the principal name and re-run."
    ok "granted: ${member}"
  done

  confirm "Remove allUsers from ${svc}?
  After this, only the ${#invokers[@]} principal(s) above can invoke it.
  Anything calling ${svc} anonymously starts getting 403 immediately."

  run gcloud run services remove-iam-policy-binding "${svc}" \
    --region="${REGION}" --member=allUsers --role=roles/run.invoker >/dev/null \
    || die "could not remove allUsers from ${svc}."
  ok "${svc}: allUsers removed"

  # Rollback, printed rather than wired to a flag: re-opening a service to the internet should
  # take a deliberate copy-and-paste, not a convenient switch.
  info "rollback if this was wrong:"
  info "  gcloud run services add-iam-policy-binding ${svc} \\"
  info "    --region=${REGION} --member=allUsers --role=roles/run.invoker"
}

RESULT=0
[ "${SKIP_CUBE}" = "1" ]     || lock_down "${CUBE_SERVICE}"     ${CUBE_INVOKERS[@]+"${CUBE_INVOKERS[@]}"}     || RESULT=1
[ "${SKIP_METABASE}" = "1" ] || lock_down "${METABASE_SERVICE}" ${METABASE_INVOKERS[@]+"${METABASE_INVOKERS[@]}"} || RESULT=1

# ──────────────────────────────────────────────────────────────────────────────
heading "After this"
# ──────────────────────────────────────────────────────────────────────────────

info "The thin web app must send an ID token on every call to ${CUBE_SERVICE}; without one it"
info "now gets 403. That is the point of US-1.3 -- see thin-web-app/server.py."
echo
info "Confirm with:  ./scripts/blocked/01_preflight.sh"
echo

exit "${RESULT}"
