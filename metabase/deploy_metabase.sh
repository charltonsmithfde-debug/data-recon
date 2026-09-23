#!/usr/bin/env bash
# Deploy Metabase OSS on Google Cloud Run
set -euo pipefail

PROJECT_ID="${1:-myanalyticsproduct}"
REGION="${2:-europe-west1}"
CLOUD_SQL_INSTANCE="${3:-myanalyticsproduct:europe-west1:scbi-ducklake-catalog}"
: "${METABASE_DB_PASSWORD:?METABASE_DB_PASSWORD is not set. Export it from Secret Manager entry 'metabase-db-password' before deploying.}"
# Direct VPC egress. Without it this service has no route to a private address at all, so its
# connection to the Cube SQL runtime (deploy_cube_sql_vm.sh, internal IP only, no external
# address) fails at the TCP layer before any credential is checked -- and the failure looks
# identical to a wrong password in the Metabase UI.
#
# `private-ranges-only` keeps public traffic on Cloud Run's own egress path, so only RFC 1918
# destinations are routed through the VPC. Sending everything through the VPC instead would need
# a Cloud NAT for Metabase to reach the internet.
VPC_NETWORK="${VPC_NETWORK:-default}"
VPC_SUBNET="${VPC_SUBNET:-default}"

echo "Deploying Metabase OSS to Cloud Run in ${REGION}..."

gcloud run deploy scbi-metabase \
    --project="${PROJECT_ID}" \
    --image="metabase/metabase:latest" \
    --region="${REGION}" \
    --platform=managed \
    --memory="2Gi" \
    --cpu="2" \
    --min-instances=0 \
    --max-instances=5 \
    --set-env-vars="MB_DB_TYPE=postgres,MB_DB_DBNAME=metabase_appdb,MB_DB_PORT=5432,MB_DB_USER=metabase_admin,MB_DB_HOST=/cloudsql/${CLOUD_SQL_INSTANCE},MB_DB_PASS=${METABASE_DB_PASSWORD}" \
    --add-cloudsql-instances="${CLOUD_SQL_INSTANCE}"     --network="${VPC_NETWORK}"     --subnet="${VPC_SUBNET}"     --vpc-egress=private-ranges-only \
    --allow-unauthenticated

echo "Metabase deployed successfully on Cloud Run!"
