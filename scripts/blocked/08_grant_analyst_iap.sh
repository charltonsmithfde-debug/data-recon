#!/usr/bin/env bash
# Give named analysts a route to Cube SQL on 5432, through IAP -- not through the internet.
#
# THE SHAPE OF THE ACCESS
#
# The SQL VM has no public address and 5432 is not open to the world; the GCP firewall rule
# allows only IAP's fixed forwarding range, 35.235.240.0/20 (deploy_cube_sql_vm.sh:47-48). So
# an analyst's Power BI or Metabase connection reaches the VM only by opening an IAP tunnel on
# their own machine, and IAP checks IAM before a single packet arrives. That is the design: the
# port is authenticated by Google before it is reachable, rather than being protected by the
# password alone.
#
# THE TWO ROLES, AND WHY BOTH
#
#   roles/iap.tunnelResourceAccessor   permission to open the tunnel. The access itself.
#   roles/compute.viewer               permission to SEE the instance. gcloud resolves the VM's
#                                      name and zone before it can tunnel to it, so without
#                                      this the tunnel command fails with a not-found that
#                                      reads as though the VM were gone.
#
# Both are project-scoped here. tunnelResourceAccessor can be narrowed to a single instance with
# an IAM condition, and should be if this list ever grows beyond a handful of people -- at that
# point a Google group is the right principal, not a list of individuals.
#
# WHAT THIS DOES NOT GIVE THEM
#
# Nothing on the database. A tunnel reaches the listener; the login is still checked against
# CUBEJS_SQL_USERS, and the role that connection gets is fixed by which user it authenticates
# as. Granting tunnel access to someone who has no SQL credential gives them a port that
# refuses them.
#
# Usage:
#   ./scripts/blocked/08_grant_analyst_iap.sh [--yes] [--dry-run] \
#       user:a@sanlam.co.za user:b@sanlam.co.za
#   ./scripts/blocked/08_grant_analyst_iap.sh --revoke user:a@sanlam.co.za
#   ./scripts/blocked/08_grant_analyst_iap.sh --list
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

REVOKE=0
LIST_ONLY=0
ARGS=()
for arg in "$@"; do
  case "${arg}" in
    --revoke) REVOKE=1 ;;
    --list)   LIST_ONLY=1 ;;
    *)        ARGS+=("${arg}") ;;
  esac
done
parse_common_flags ${ARGS[@]+"${ARGS[@]}"}

require_gcloud

ROLES=(roles/iap.tunnelResourceAccessor roles/compute.viewer)

# ──────────────────────────────────────────────────────────────────────────────
heading "Who can tunnel today"
# ──────────────────────────────────────────────────────────────────────────────

for role in "${ROLES[@]}"; do
  members="$(gcloud projects get-iam-policy "${PROJECT_ID}" \
             --flatten='bindings[]' --filter="bindings.role=${role}" \
             --format='value(bindings.members)' 2>/dev/null | tr ';' '\n' | sed '/^$/d')"
  if [ -n "${members}" ]; then
    info "${role}:"
    echo "${members}" | sed 's/^/      /'
  else
    info "${role}: (nobody)"
  fi
done

if [ "${LIST_ONLY}" = "1" ]; then
  echo
  exit 0
fi

MEMBERS=(${REMAINING_ARGS[@]+"${REMAINING_ARGS[@]}"})
[ -n "${MEMBERS[0]:-}" ] || die "Usage: $0 [--revoke] user:someone@sanlam.co.za ...    ($0 --list)"

# A bare address is a common slip and IAM accepts it nowhere; catch it before the API does.
for member in "${MEMBERS[@]}"; do
  case "${member}" in
    user:*|group:*|serviceAccount:*|domain:*) ;;
    *) die "Principals need a type prefix: 'user:${member}', not '${member}'." ;;
  esac
done

# ──────────────────────────────────────────────────────────────────────────────
if [ "${REVOKE}" = "1" ]; then
# ──────────────────────────────────────────────────────────────────────────────
  heading "Revoke"

  confirm "Remove tunnel access for ${#MEMBERS[@]} principal(s)?
  Their open tunnels drop within minutes and new ones are refused.
  Their SQL credentials are NOT revoked -- rotate those with 02b if that is the intent."

  for member in "${MEMBERS[@]}"; do
    for role in "${ROLES[@]}"; do
      run gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
        --member="${member}" --role="${role}" --condition=None >/dev/null 2>&1 \
        && ok "${member}: ${role} removed" \
        || warn "${member}: ${role} was not bound"
    done
  done
  echo
  exit 0
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "Grant"
# ──────────────────────────────────────────────────────────────────────────────

info "principals: ${MEMBERS[*]}"
info "roles:      ${ROLES[*]}"

confirm "Grant project-level tunnel access to ${#MEMBERS[@]} principal(s)?
  This lets them reach ${SQL_VM}:${SQL_PORT} from their own machine through IAP.
  It grants nothing inside the database -- the SQL login is still checked."

for member in "${MEMBERS[@]}"; do
  for role in "${ROLES[@]}"; do
    run gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="${member}" --role="${role}" --condition=None >/dev/null \
      || die "could not grant ${role} to ${member}."
    ok "${member}: ${role}"
  done
done

# ──────────────────────────────────────────────────────────────────────────────
heading "What to send them"
# ──────────────────────────────────────────────────────────────────────────────

cat <<INSTRUCTIONS

  To connect a BI tool to Cube SQL:

  1. Install the Google Cloud CLI, then once:
       gcloud auth login
       gcloud config set project ${PROJECT_ID}

  2. Behind Zscaler, export a CA bundle once (PowerShell, from the repo):
       powershell -ExecutionPolicy Bypass -File scripts/blocked/00_export_ca_bundle.ps1
     and set the variable it prints, permanently, with setx.

  3. Open the tunnel and leave the window running:
       gcloud compute start-iap-tunnel ${SQL_VM} ${SQL_PORT} \\
         --local-host-port=localhost:15432 --zone ${ZONE}

  4. Point the BI tool at localhost:15432 as a PostgreSQL source, with the username and
     password issued for their role. Power BI: do not tick Encrypt Connection -- the tunnel
     is the encrypted channel, and Cube's SQL endpoint does not terminate TLS itself.

  The tunnel must be open whenever they refresh. If step 3 fails with a certificate error,
  the CA bundle in step 2 is missing or stale.

INSTRUCTIONS

info "Revoke later with:  $0 --revoke <principal>"
echo
