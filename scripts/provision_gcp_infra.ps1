# GCP Infrastructure Provisioning Script for DuckLake + Cloud SQL + Cube.js + Metabase
# Run with Google Cloud SDK (gcloud CLI)

param (
    [string]$ProjectId = "myanalyticsproduct",
    [string]$Region = "europe-west1",
    [string]$BucketName = "scbi-ducklake-myanalyticsproduct",
    [string]$CloudSqlInstance = "scbi-ducklake-catalog",
    [string]$DuckLakePassword = $env:DUCKLAKE_CATALOG_PASSWORD,
    [string]$MetabasePassword = $env:METABASE_DB_PASSWORD
)

# These two defaults used to be literals in the repo. A placeholder that tells the reader to
# replace it is still a credential once someone runs the script without doing so -- and this
# script creates the
# Cloud SQL users, so whatever it reads here is what the database ends up trusting. US-2.2
# swept .sh for exactly this and did not cover .ps1.
foreach ($pair in @(
    @{ Name = "DUCKLAKE_CATALOG_PASSWORD"; Value = $DuckLakePassword },
    @{ Name = "METABASE_DB_PASSWORD";      Value = $MetabasePassword }
)) {
    if ([string]::IsNullOrWhiteSpace($pair.Value)) {
        throw "$($pair.Name) is not set. Generate one with secrets.token_urlsafe(32), " +
              "export it, and store it in Secret Manager. This script creates the " +
              "Cloud SQL user with whatever it reads here."
    }
}

Write-Host "Setting active GCP Project to: $ProjectId" -ForegroundColor Cyan
gcloud config set project $ProjectId

Write-Host "Enabling required GCP APIs..." -ForegroundColor Cyan
gcloud services enable `
    run.googleapis.com `
    sqladmin.googleapis.com `
    storage.googleapis.com `
    compute.googleapis.com `
    iam.googleapis.com `
    iap.googleapis.com

Write-Host "Creating GCS Storage Bucket ($BucketName) in $Region..." -ForegroundColor Cyan
gcloud storage buckets create "gs://$BucketName" `
    --location=$Region `
    --uniform-bucket-level-access `
    --default-storage-class=STANDARD

Write-Host "Provisioning Cloud SQL PostgreSQL 16 instance ($CloudSqlInstance)..." -ForegroundColor Cyan
gcloud sql instances create $CloudSqlInstance `
    --database-version=POSTGRES_16 `
    --tier=db-custom-2-7680 `
    --region=$Region `
    --storage-type=SSD `
    --storage-size=50GB `
    --storage-auto-increase `
    --availability-type=zonal

Write-Host "Creating DuckLake and Metabase Databases..." -ForegroundColor Cyan
gcloud sql databases create ducklake_catalog --instance=$CloudSqlInstance
gcloud sql databases create metabase_appdb --instance=$CloudSqlInstance

Write-Host "Creating Database Users..." -ForegroundColor Cyan
gcloud sql users create ducklake_admin --instance=$CloudSqlInstance --password=$DuckLakePassword
gcloud sql users create metabase_admin --instance=$CloudSqlInstance --password=$MetabasePassword

Write-Host "Infrastructure provisioning complete!" -ForegroundColor Green
Write-Host "GCS Bucket: gs://$BucketName"
Write-Host "Cloud SQL Instance: $CloudSqlInstance"
Write-Host "DuckLake Catalog DB: ducklake_catalog"
Write-Host "Metabase App DB: metabase_appdb"
