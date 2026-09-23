#!/usr/bin/env bash
# First deployment of the thin web app, behind IAP -- US-1.1/US-1.2.
#
# scbi-thin-web does not exist in Cloud Run (measured 2026-09-20). The app's 26-test
# authentication gate therefore protects nothing today: it is all in the repository and none of
# it is in front of a user. This is the step that changes that.
#
# WHY NO --allow-unauthenticated, EVER, ON THIS SERVICE
#
# server.py's entire authorisation model reads the IAP assertion header and derives the caller's
# role from it (server.py:67,169). A Cloud Run service with allUsers on roles/run.invoker
# receives requests with no assertion at all -- so the app would either refuse every request or,
# worse, fall through to its default role. The service must be private from its first revision;
# retrofitting privacy after a public deploy leaves a window in which the dashboards were
# world-readable.
#
# THE AUDIENCE IS NOT OPTIONAL AND NOT GUESSABLE
#
# server.py:67 require_env()s SCBI_IAP_AUDIENCE, and IAP tokens are validated against it
# exactly. For a Cloud Run backend the audience is:
#
#     /projects/<PROJECT_NUMBER>/apps/<PROJECT_ID>
#
# A wrong audience does not fail loudly at deploy time -- it fails on the first real request,
# with every caller rejected. Stage 4 prints what was set so it can be compared against the IAP
# console before anyone is told the app is live.
#
# ORDER
#
#   1. deploy private        the app is up, nobody can reach it
#   2. grant IAP's SA        so IAP itself may invoke the service
#   3. enable IAP            the front door opens, authenticated only
#   4. grant the users       roles/iap.httpsResourceAccessor, per person
#
# Nothing is reachable between 1 and 3, which is the intended shape of a first deploy.
#
# Usage:
#   ./scripts/blocked/07_deploy_thin_web.sh [--yes] [--dry-run] \
#       [--user=user:someone@sanlam.co.za ...]
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${HERE}/lib/common.sh"

REPO="$(cd "${HERE}/../.." && pwd)"

USERS=()
ARGS=()
for arg in "$@"; do
  case "${arg}" in
    --user=*) USERS+=("${arg#*=}") ;;
    *)        ARGS+=("${arg}") ;;
  esac
done
parse_common_flags "${ARGS[@]:-}"

require_gcloud

IAP_AUDIENCE="/projects/${PROJECT_NUMBER}/apps/${PROJECT_ID}"
IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
SEC_API="scbi-cube-api-secret"
SOURCE_DIR="${REPO}/thin-web-app"

[ -d "${SOURCE_DIR}" ] || die "No thin-web-app directory at ${SOURCE_DIR}"

# ──────────────────────────────────────────────────────────────────────────────
heading "0. Preconditions"
# ──────────────────────────────────────────────────────────────────────────────

if gcloud secrets describe "${SEC_API}" >/dev/null 2>&1 && \
   [ "$(gcloud secrets versions list "${SEC_API}" --filter='state=ENABLED' \
        --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')" -gt 0 ]; then
  ok "${SEC_API} has an enabled version to mount"
else
  die "${SEC_API} has no enabled version. server.py:42 require_env()s CUBEJS_API_SECRET and the
       container will not start without it. Run 03 then 04 first."
fi

if [ -f "${SOURCE_DIR}/role_assignments.json" ]; then
  # An empty map is valid and safe, but it is not the same as a filled one -- count, do not
  # merely check for the file. See thin-web-app/ROLE_ASSIGNMENTS.md.
  ra_count="$(python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d))' \
              "${SOURCE_DIR}/role_assignments.json" 2>/dev/null)"
  if [ -z "${ra_count}" ]; then
    die "role_assignments.json is not valid JSON. server.py swallows the parse error and falls
       back to ROLE_FINANCE_MEMBER for every caller, so this would deploy silently wrong."
  elif [ "${ra_count}" -gt 0 ]; then
    ok "role_assignments.json maps ${ra_count} caller(s)"
  else
    warn "role_assignments.json is an empty map -- every caller falls back to ROLE_FINANCE_MEMBER"
    warn "(server.py:101-111,179-196). That is least privilege and safe, but named users will"
    warn "see less than intended until the file is filled in."
  fi
else
  warn "role_assignments.json absent -- every caller falls back to ROLE_FINANCE_MEMBER"
  warn "(server.py:101-111,190-196). That is least privilege and safe, but named users will"
  warn "see less than intended until the file is added."
fi

info "IAP audience will be: ${IAP_AUDIENCE}"

confirm "Deploy ${THIN_WEB_SERVICE} to Cloud Run in ${REGION}, private, then put IAP in front?
  The service does not exist yet, so nothing is taken down.
  It is unreachable by anyone until stage 3 completes."

# ──────────────────────────────────────────────────────────────────────────────
heading "1. Deploy, private from the first revision"
# ──────────────────────────────────────────────────────────────────────────────

run gcloud run deploy "${THIN_WEB_SERVICE}" \
  --project="${PROJECT_ID}" \
  --source="${SOURCE_DIR}" \
  --region="${REGION}" \
  --platform=managed \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=5 \
  --no-allow-unauthenticated \
  --set-secrets="CUBEJS_API_SECRET=${SEC_API}:latest" \
  --set-env-vars="SCBI_IAP_AUDIENCE=${IAP_AUDIENCE},SCBI_CUBE_ID_TOKEN_AUDIENCE=https://${CUBE_SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app" \
  || die "the deploy failed. Nothing is exposed: the service is either absent or private."
ok "deployed, private"

# ──────────────────────────────────────────────────────────────────────────────
heading "2. Let IAP invoke the service"
# ──────────────────────────────────────────────────────────────────────────────
#
# IAP terminates the request and calls the backend as its own service agent. Without this
# binding IAP authenticates the user correctly and then gets 403 from Cloud Run -- which
# presents to the user as a failure that looks like their own credentials.

run gcloud run services add-iam-policy-binding "${THIN_WEB_SERVICE}" \
  --region="${REGION}" \
  --member="serviceAccount:${IAP_SA}" \
  --role=roles/run.invoker >/dev/null \
  || die "could not grant roles/run.invoker to IAP's service agent (${IAP_SA}).
       If this 400s, the IAP service agent does not exist yet on this project: run
       'gcloud beta services identity create --service=iap.googleapis.com' and retry."
ok "IAP service agent may invoke ${THIN_WEB_SERVICE}"

# ──────────────────────────────────────────────────────────────────────────────
heading "3. Enable IAP on the service"
# ──────────────────────────────────────────────────────────────────────────────

run gcloud beta run services update "${THIN_WEB_SERVICE}" \
  --region="${REGION}" --iap \
  || die "could not enable IAP. The service stays private and unreachable, which is a safe
       resting state. Enabling IAP on Cloud Run needs the service to be in a supported region
       and may need iap.googleapis.com enabled:
         gcloud services enable iap.googleapis.com"
ok "IAP enabled"

# ──────────────────────────────────────────────────────────────────────────────
heading "4. Grant the people who may open it"
# ──────────────────────────────────────────────────────────────────────────────

if [ "${#USERS[@]}" -eq 0 ] || [ -z "${USERS[0]:-}" ]; then
  warn "No --user given, so nobody can open the app yet. That is deliberate: the grant list"
  warn "is an authorisation decision, not a default. Add people with:"
  warn "  gcloud beta iap web add-iam-policy-binding \\"
  warn "    --resource-type=cloud-run --service=${THIN_WEB_SERVICE} --region=${REGION} \\"
  warn "    --member=user:someone@sanlam.co.za --role=roles/iap.httpsResourceAccessor"
else
  for member in "${USERS[@]}"; do
    run gcloud beta iap web add-iam-policy-binding \
      --resource-type=cloud-run --service="${THIN_WEB_SERVICE}" --region="${REGION}" \
      --member="${member}" --role=roles/iap.httpsResourceAccessor >/dev/null \
      && ok "granted: ${member}" \
      || warn "could not grant ${member}"
  done
fi

# ──────────────────────────────────────────────────────────────────────────────
heading "5. Verify before telling anyone it is live"
# ──────────────────────────────────────────────────────────────────────────────

URL="$(gcloud run services describe "${THIN_WEB_SERVICE}" --region="${REGION}" \
       --format='value(status.url)' 2>/dev/null)"
info "URL: ${URL:-(not available)}"
echo
info "1. Anonymous access must FAIL. This should print 302 (to the IAP sign-in) or 403,"
info "   and must never print 200:"
info "     curl -s -o /dev/null -w '%{http_code}\\n' ${URL:-<url>}"
info "2. The audience set on the service must match what IAP issues:"
info "     gcloud run services describe ${THIN_WEB_SERVICE} --region=${REGION} \\"
info "       --format='value(spec.template.spec.containers[0].env)' | tr ',' '\\n' | grep IAP"
info "   expected: ${IAP_AUDIENCE}"
info "3. Sign in as a granted user and confirm the role the app derives is the intended one."
echo
info "Rollback: gcloud run services delete ${THIN_WEB_SERVICE} --region=${REGION}"
echo
