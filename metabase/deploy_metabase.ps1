# Deploy Metabase OSS on Google Cloud Run connecting to Cloud SQL Application DB
param (
    [string]$ProjectId = "myanalyticsproduct",
    [string]$Region = "europe-west1",
    [string]$CloudSqlInstance = "myanalyticsproduct:europe-west1:scbi-ducklake-catalog",
    [string]$MetabaseDbPassword = $env:METABASE_DB_PASSWORD
)

# US-2.2 removed the literal from deploy_metabase.sh and left this PowerShell twin behind,
# because that sweep covered .sh and not .ps1. Same rule: the password comes from the
# environment, never from a default a reader of the repo can see.
if ([string]::IsNullOrWhiteSpace($MetabaseDbPassword)) {
    throw "METABASE_DB_PASSWORD is not set. Export it from the Secret Manager entry " +
          "'metabase-db-password' before deploying, or pass -MetabaseDbPassword."
}

Write-Host "Deploying Metabase OSS to Cloud Run..." -ForegroundColor Cyan

gcloud run deploy scbi-metabase `
    --project=$ProjectId `
    --image="metabase/metabase:latest" `
    --region=$Region `
    --platform=managed `
    --memory="2Gi" `
    --cpu="2" `
    --min-instances=0 `
    --max-instances=5 `
    --set-env-vars="MB_DB_TYPE=postgres,MB_DB_DBNAME=metabase_appdb,MB_DB_PORT=5432,MB_DB_USER=metabase_admin,MB_DB_HOST=/cloudsql/$CloudSqlInstance,MB_DB_PASS=$MetabaseDbPassword" `
    --add-cloudsql-instances=$CloudSqlInstance `
    --allow-unauthenticated

Write-Host "Metabase deployed successfully on Cloud Run!" -ForegroundColor Green
Write-Host "Note: Protect the public URL using Google Cloud Identity-Aware Proxy (IAP) for corporate SSO."
