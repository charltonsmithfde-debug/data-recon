#!/usr/bin/env bash
# GCP Infrastructure Provisioning Script for DuckLake + Cloud SQL + Cube.js + Metabase
set -euo pipefail

PROJECT_ID="${1:-myanalyticsproduct}"
REGION="${2:-europe-west1}"
BUCKET_NAME="${3:-scbi-ducklake-myanalyticsproduct}"
CLOUD_SQL_INSTANCE="${4:-scbi-ducklake-catalog}"
: "${DUCKLAKE_PASSWORD:?DUCKLAKE_PASSWORD is not set. Export it from Secret Manager entry 'ducklake-db-password' before provisioning.}"
: "${METABASE_PASSWORD:?METABASE_PASSWORD is not set. Export it from Secret Manager entry 'metabase-db-password' before provisioning.}"
echo "Setting active GCP Project to: ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

echo "Enabling required GCP APIs..."
gcloud services enable \
    run.googleapis.com \
    sqladmin.googleapis.com \
    storage.googleapis.com \
    compute.googleapis.com \
    iam.googleapis.com \
    iap.googleapis.com

echo "Creating GCS Storage Bucket (gs://${BUCKET_NAME}) in ${REGION}..."
gcloud storage buckets create "gs://${BUCKET_NAME}" \
    --location="${REGION}" \
    --uniform-bucket-level-access \
    --default-storage-class=STANDARD

echo "Provisioning Cloud SQL PostgreSQL 16 instance (${CLOUD_SQL_INSTANCE})..."
gcloud sql instances create "${CLOUD_SQL_INSTANCE}" \
    --database-version=POSTGRES_16 \
    --tier=db-custom-2-7680 \
    --region="${REGION}" \
    --storage-type=SSD \
    --storage-size=50GB \
    --storage-auto-increase \
    --availability-type=zonal

echo "Creating DuckLake and Metabase Databases..."
gcloud sql databases create ducklake_catalog --instance="${CLOUD_SQL_INSTANCE}"
gcloud sql databases create metabase_appdb --instance="${CLOUD_SQL_INSTANCE}"

echo "Creating Database Users..."
gcloud sql users create ducklake_admin --instance="${CLOUD_SQL_INSTANCE}" --password="${DUCKLAKE_PASSWORD}"
gcloud sql users create metabase_admin --instance="${CLOUD_SQL_INSTANCE}" --password="${METABASE_PASSWORD}"

echo "Infrastructure provisioning complete!"
echo "GCS Bucket: gs://${BUCKET_NAME}"
echo "Cloud SQL Instance: ${CLOUD_SQL_INSTANCE}"
echo "DuckLake Catalog DB: ducklake_catalog"
echo "Metabase App DB: metabase_appdb"
