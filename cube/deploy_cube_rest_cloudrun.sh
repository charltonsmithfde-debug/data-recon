#!/usr/bin/env bash
# Deploy the Cube REST/GraphQL API to Cloud Run as `scbi-cube` (US-8.3).
#
# This is the half of the semantic layer the thin web app talks to: HTTP on 4000, one container
# port, authenticated by Cloud Run IAM plus Cube's own HS256 token. It cannot serve Metabase or
# Power BI -- Cloud Run routes a single port and speaks HTTP/1, HTTP/2, gRPC and WebSockets only,
# so the Postgres wire protocol cannot reach it at any port. That half is deploy_cube_sql_vm.sh.
#
# Until 2026-09-20 there was no deploy script at all and the live revision was assembled by hand.
# It was missing both CUBEJS_DB_DUCKDB_S3_* variables, which cube.js has requireEnv()d since
# US-2.2 -- the next hand-rolled deploy would have crash-looped on startup with no note of why.
# That is what this file exists to prevent.
#
# Usage:
#   export CUBEJS_API_SECRET=...            # >= 32 bytes; python -c "import secrets; print(secrets.token_urlsafe(48))"
#   export CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID=...
#   export CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY=...
#   export DUCKLAKE_CATALOG_PASSWORD=...
#   export CUBE_INVOKER_POLICY=private      # or `public`, see below
#   ./cube/deploy_cube_rest_cloudrun.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-myanalyticsproduct}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-scbi-cube}"
CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-myanalyticsproduct:europe-west1:scbi-ducklake-catalog}"
GCS_BUCKET="${DUCKLAKE_GCS_BUCKET:-scbi-ducklake-myanalyticsproduct}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Every secret is required from the environment. No defaults, no fallbacks -- US-2.2.
: "${CUBEJS_API_SECRET:?CUBEJS_API_SECRET is not set. cube.js enforces a 32-byte floor (RFC 7518 s3.2) and refuses the revoked in-repo value.}"
: "${CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID:?CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID is not set. It is the GCS HMAC access id DuckDB reads the lakehouse with; cube.js requireEnv()s it at module load.}"
: "${CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY:?CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY is not set. Mint a pair with: gcloud storage hmac create <service-account>.}"
: "${DUCKLAKE_CATALOG_PASSWORD:?DUCKLAKE_CATALOG_PASSWORD is not set. Export it from the Secret Manager entry 'ducklake-db-password'.}"

# The invoker policy is an explicit choice, never a default. `private` is US-1.3 criterion 3 and
# the target state: only the thin web app's service account may invoke, and it must already be
# sending an ID token (SCBI_CUBE_ID_TOKEN_AUDIENCE set on scbi-thin-web) or every dashboard goes
# dark the moment this lands. `public` preserves today's posture -- allUsers bound to
# roles/run.invoker, i.e. the Cube API invokable by anyone who has the signing key.
case "${CUBE_INVOKER_POLICY:-}" in
  private) INVOKER_FLAG="--no-allow-unauthenticated" ;;
  public)  INVOKER_FLAG="--allow-unauthenticated" ;;
  *) echo "CUBE_INVOKER_POLICY must be 'private' (US-1.3 target: callers need an ID token) or" >&2
     echo "'public' (today's posture: invokable by anyone). It has no default -- flipping it is" >&2
     echo "outward-facing in both directions." >&2
     exit 1 ;;
esac

echo "Deploying ${SERVICE} (REST API) to Cloud Run in ${REGION} [${CUBE_INVOKER_POLICY}]..."

# CUBEJS_SQL_USERS is deliberately absent: nothing here can serve a SQL client, so provisioning
# credentials on this service would only advertise an endpoint that refuses every connection.
# cube.js fails the container on that combination on purpose (assertSqlApiIsCoherent).
gcloud run deploy "${SERVICE}" \
    --project="${PROJECT_ID}" \
    --source="${SOURCE_DIR}" \
    --region="${REGION}" \
    --platform=managed \
    --port=4000 \
    --memory="4Gi" \
    --cpu="2" \
    --min-instances=0 \
    --max-instances=5 \
    --add-cloudsql-instances="${CLOUD_SQL_INSTANCE}" \
    --set-env-vars="^@^CUBEJS_DB_TYPE=duckdb@CUBEJS_PORT=4000@CUBEJS_DEV_MODE=false@CUBEJS_CACHE_AND_QUEUE_DRIVER=memory@DUCKLAKE_GCS_BUCKET=${GCS_BUCKET}@DUCKLAKE_CATALOG_HOST=/cloudsql/${CLOUD_SQL_INSTANCE}@DUCKLAKE_CATALOG_DB=ducklake_catalog@DUCKLAKE_CATALOG_USER=ducklake_admin@DUCKLAKE_CATALOG_PASSWORD=${DUCKLAKE_CATALOG_PASSWORD}@CUBEJS_API_SECRET=${CUBEJS_API_SECRET}@CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID=${CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID}@CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY=${CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY}" \
    "${INVOKER_FLAG}"

echo
echo "Deployed. Two things this script cannot do for you:"
echo "  1. These are --set-env-vars, not --set-secrets: every value above is readable by anyone"
echo "     who can 'gcloud run services describe ${SERVICE}'. Moving them to Secret Manager is"
echo "     US-2.2 criteria 1 and 3, and needs secretmanager.googleapis.com enabled first."
if [ "${CUBE_INVOKER_POLICY}" = "private" ]; then
  echo "  2. Removing any stale allUsers binding: gcloud run services remove-iam-policy-binding"
  echo "     ${SERVICE} --region=${REGION} --member=allUsers --role=roles/run.invoker"
else
  echo "  2. ${SERVICE} is invokable by anyone on the internet. US-1.3 criterion 3 is unmet"
  echo "     until CUBE_INVOKER_POLICY=private and the thin app sends an ID token."
fi
