#!/usr/bin/env bash
# Make thin-web-app/role_assignments.json true in GCP IAM.
#
# WHAT THIS IS FOR
#
# The roster answers two questions at once. server.py reads the half that says what a person
# SEES (`role`, `can_view_pii`). This script reads the other half -- `groups` -- and turns it
# into the IAM bindings that decide what a person can REACH. Run it after every roster change,
# so "who may open Metabase" is answered in one reviewable file rather than in the IAM console's
# history.
#
# THE FOUR SURFACES, AND THE GROUP THAT OPENS EACH
#
#   portal       roles/iap.httpsResourceAccessor  scbi-thin-web  the recon portal itself
#   metabase     roles/run.invoker                scbi-metabase  the Metabase login page
#   cube_rest    roles/run.invoker                scbi-cube      the Cube REST API, by hand
#   sql_analyst  roles/iap.tunnelResourceAccessor + roles/compute.viewer (project-scoped)
#                                                                a tunnel to 5432 (delegated
#                                                                to 08_grant_analyst_iap.sh)
#
# `sys_admin` in the roster implies all four. That is what makes one word in the JSON mean
# "Metabase and scbi-cube and the tunnel", instead of three bindings someone has to remember.
#
# WHAT THIS DOES NOT DO
#
#   * It does not remove allUsers. That is 05_lock_down_cloud_run.sh, once, in the right order
#     (grant first, revoke second). Run 05 before this script or the services stay public no
#     matter who else is granted.
#   * It grants nothing inside Metabase or inside the database. Reaching the Metabase login
#     page is not a Metabase account, and a tunnel to 5432 is not a SQL credential -- those are
#     Metabase's own user admin and CUBEJS_SQL_USERS (02b) respectively.
#   * It never deploys. A `role` change reaches users only on the next 07_deploy_thin_web.sh,
#     because the roster is baked into the container image.
#
# PRUNING
#
# --prune revokes what the roster no longer justifies. It only ever removes `user:` principals,
# because this script only ever adds `user:` principals: a serviceAccount, group, domain,
# allUsers or allAuthenticatedUsers binding was put there by something else and is not this
# script's to take away. It also refuses to remove the account running it, which is the one
# mistake that cannot be undone from the tunnel it just closed.
#
# Usage:
#   ./scripts/blocked/09_apply_access.sh [--dry-run] [--yes] [--prune]
#   ./scripts/blocked/09_apply_access.sh --list                 # show drift, change nothing
#   ./scripts/blocked/09_apply_access.sh --only=metabase        # one surface
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

REPO="$(cd "${HERE}/../.." && pwd)"
ROSTER="${REPO}/thin-web-app/role_assignments.json"
MANAGE="${REPO}/scripts/access/manage_access.py"

PRUNE=0
LIST_ONLY=0
ONLY=""
ARGS=()
for arg in "$@"; do
  case "${arg}" in
    --prune) PRUNE=1 ;;
    --list)  LIST_ONLY=1 ;;
    --only=*) ONLY="${arg#*=}" ;;
    *)       ARGS+=("${arg}") ;;
  esac
done
parse_common_flags ${ARGS[@]+"${ARGS[@]}"}

wanted_surface() { [ -z "${ONLY}" ] || [ "${ONLY}" = "$1" ]; }

# ──────────────────────────────────────────────────────────────────────────────
heading "The roster"
# ──────────────────────────────────────────────────────────────────────────────

[ -f "${ROSTER}" ] || die "no roster at ${ROSTER}. Nothing to apply."
command -v python >/dev/null 2>&1 || die "python is not on PATH; it reads the roster."

# A roster that does not validate must not be applied: an unknown role is a silent demotion in
# the app, and an unknown group here would be a silently missing grant.
if ! python "${MANAGE}" --file="${ROSTER}" check >/dev/null 2>&1; then
  python "${MANAGE}" --file="${ROSTER}" check
  die "the roster does not validate. Fix it before granting anything from it."
fi

people="$(python -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "${ROSTER}")"
ok "${ROSTER##*/}: ${people} person(s), valid"

principals_for() { python "${MANAGE}" --file="${ROSTER}" principals --group="$1" 2>/dev/null; }

for group in portal metabase cube_rest sql_analyst; do
  members="$(principals_for "${group}")"
  count="$(printf '%s' "${members}" | grep -c . || true)"
  if [ "${count}" -gt 0 ]; then
    info "${group}: ${count} -- $(echo "${members}" | tr '\n' ' ')"
  else
    info "${group}: (nobody)"
  fi
done

require_gcloud
SELF="$(gcloud config get-value account 2>/dev/null)"

RESULT=0

# ──────────────────────────────────────────────────────────────────────────────
# One surface: read what is bound, grant what is missing, report or prune the rest.
# ──────────────────────────────────────────────────────────────────────────────
#
# `read_members` and `grant`/`revoke` differ per surface, so each is passed in as a command
# name. Everything else -- the diff, the confirmation, the prune guards -- is shared.

reconcile() {
  local label="$1" role="$2" reader="$3" writer="$4" desired_group="$5"

  heading "${label}"

  local desired current line member
  local -a missing=() extra=()
  desired="$(principals_for "${desired_group}" | sort -u)"
  current="$("${reader}" | tr ';,' '\n' | sed 's/^ *//; s/ *$//; /^$/d' | sort -u)"

  if [ -z "${current}" ]; then
    info "nothing is bound to ${role} today"
  else
    info "bound today: $(echo "${current}" | tr '\n' ' ')"
  fi

  # Collected into arrays before anything is granted: `confirm` reads stdin, so a loop fed by a
  # here-string would have its next principal eaten by the prompt.
  while IFS= read -r line; do
    [ -n "${line}" ] && missing+=("${line}")
  done < <(comm -23 <(echo "${desired}") <(echo "${current}"))
  while IFS= read -r line; do
    [ -n "${line}" ] && extra+=("${line}")
  done < <(comm -13 <(echo "${desired}") <(echo "${current}"))

  if [ "${#missing[@]}" -eq 0 ]; then
    ok "every person the roster names already has ${role}"
  else
    info "to grant: ${missing[*]}"
    if [ "${LIST_ONLY}" = "0" ]; then
      confirm "Grant ${role} on ${label} to ${#missing[@]} principal(s)?"
      for member in "${missing[@]}"; do
        if "${writer}" grant "${member}"; then
          ok "granted: ${member}"
        else
          bad "could not grant ${member}"
          RESULT=1
        fi
      done
    fi
  fi

  # Anything bound that the roster does not justify. Reported always; removed only on --prune,
  # and then only if it is a plain user this script could have added itself.
  for member in ${extra[@]+"${extra[@]}"}; do
    case "${member}" in
      allUsers|allAuthenticatedUsers)
        warn "${member} is bound -- that is 05_lock_down_cloud_run.sh's job, not this script's"
        continue ;;
      serviceAccount:*|group:*|domain:*|projectOwner:*|projectEditor:*|projectViewer:*)
        info "leaving ${member} alone (not a user this roster grants)"
        continue ;;
    esac
    if [ "${member}" = "user:${SELF}" ]; then
      warn "${member} is bound but not in the roster -- NOT removing the account running this"
      warn "  (add yourself to the roster, or remove it from another account)"
      continue
    fi
    if [ "${PRUNE}" = "1" ] && [ "${LIST_ONLY}" = "0" ]; then
      confirm "Remove ${role} on ${label} from ${member}?
  They are not in the roster. They lose this access immediately."
      if "${writer}" revoke "${member}"; then
        ok "revoked: ${member}"
      else
        bad "could not revoke ${member}"
        RESULT=1
      fi
    else
      warn "${member} has ${role} and is not in the roster (--prune removes it)"
    fi
  done
}

# --- Cloud Run invoker: scbi-metabase, scbi-cube -------------------------------

run_invoker_members() {
  gcloud run services get-iam-policy "$1" --region="${REGION}" \
    --flatten='bindings[]' --filter='bindings.role=roles/run.invoker' \
    --format='value(bindings.members)' 2>/dev/null
}
metabase_members() { run_invoker_members "${METABASE_SERVICE}"; }
cube_members()     { run_invoker_members "${CUBE_SERVICE}"; }

# `run` echoes the command on stdout, so `run gcloud ... >/dev/null` would swallow the echo
# along with the output and a --dry-run would print nothing at all. --format trims gcloud's own
# policy dump to one line instead of redirecting it away.
run_invoker_write() {           # <svc> <grant|revoke> <member>
  local svc="$1" verb="$2" member="$3" action
  [ "${verb}" = "grant" ] && action="add-iam-policy-binding" || action="remove-iam-policy-binding"
  run gcloud run services "${action}" "${svc}" --region="${REGION}" \
    --member="${member}" --role=roles/run.invoker --format='value(etag)'
}
metabase_write() { run_invoker_write "${METABASE_SERVICE}" "$@"; }
cube_write()     { run_invoker_write "${CUBE_SERVICE}" "$@"; }

# --- IAP on the thin web app ---------------------------------------------------

portal_members() {
  gcloud beta iap web get-iam-policy --resource-type=cloud-run \
    --service="${THIN_WEB_SERVICE}" --region="${REGION}" \
    --flatten='bindings[]' --filter='bindings.role=roles/iap.httpsResourceAccessor' \
    --format='value(bindings.members)' 2>/dev/null
}
portal_write() {                # <grant|revoke> <member>
  local verb="$1" member="$2" action
  [ "${verb}" = "grant" ] && action="add-iam-policy-binding" || action="remove-iam-policy-binding"
  run gcloud beta iap web "${action}" --resource-type=cloud-run \
    --service="${THIN_WEB_SERVICE}" --region="${REGION}" \
    --member="${member}" --role=roles/iap.httpsResourceAccessor --format='value(etag)'
}

# ──────────────────────────────────────────────────────────────────────────────

wanted_surface portal   && reconcile "${THIN_WEB_SERVICE} (the portal)" \
  roles/iap.httpsResourceAccessor portal_members portal_write portal

wanted_surface metabase && reconcile "${METABASE_SERVICE} (Metabase)" \
  roles/run.invoker metabase_members metabase_write metabase

wanted_surface cube     && reconcile "${CUBE_SERVICE} (Cube REST API)" \
  roles/run.invoker cube_members cube_write cube_rest

# --- Cube SQL on 5432: delegated ----------------------------------------------
#
# 08 already owns this pair of project-level roles, its confirmation wording and the
# instructions it prints for the analyst. Re-implementing that here would give two scripts an
# opinion about the same two bindings.

if wanted_surface sql; then
  heading "${SQL_VM}:${SQL_PORT} (Cube SQL over IAP)"
  sql_people="$(principals_for sql_analyst | sed '/^$/d')"
  if [ -z "${sql_people}" ]; then
    info "nobody in the roster is in sql_analyst or sys_admin -- nothing to grant"
  else
    info "delegating to 08_grant_analyst_iap.sh: $(echo "${sql_people}" | tr '\n' ' ')"
    # shellcheck disable=SC2046
    run_args=()
    [ "${ASSUME_YES}" = "1" ] && run_args+=(--yes)
    [ "${DRY_RUN}" = "1" ]    && run_args+=(--dry-run)
    while IFS= read -r member; do
      [ -n "${member}" ] && run_args+=("${member}")
    done <<< "${sql_people}"
    if [ "${LIST_ONLY}" = "1" ]; then
      info "(--list) would run: 08_grant_analyst_iap.sh ${run_args[*]}"
      "${HERE}/08_grant_analyst_iap.sh" --list
    else
      "${HERE}/08_grant_analyst_iap.sh" "${run_args[@]}" || RESULT=1
    fi
  fi
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "After this"
# ──────────────────────────────────────────────────────────────────────────────

info "IAM is now what the roster says. Two things IAM cannot do for you:"
info "  1. A changed 'role' or 'can_view_pii' is baked into the container image."
info "     Ship it:  ./scripts/blocked/07_deploy_thin_web.sh"
info "  2. Reaching Metabase is not having a Metabase account, and a tunnel to"
info "     ${SQL_PORT} is not a SQL credential (02b_remint_sql_users.sh issues those)."
echo
info "Confirm with:  ./scripts/blocked/99_verify.sh"
echo

exit "${RESULT}"
