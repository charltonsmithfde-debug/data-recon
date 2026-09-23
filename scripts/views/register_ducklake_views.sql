-- data-recon/scripts/views/register_ducklake_views.sql
-- Conformed DuckDB External Lakehouse Views over Google Cloud Storage Parquet
-- Target Bucket: gs://scbi-ducklake-myanalyticsproduct/

INSTALL httpfs;
LOAD httpfs;

SET s3_endpoint = 'storage.googleapis.com';
SET s3_access_style = 'path';

CREATE SCHEMA IF NOT EXISTS scbi_cdp_mart;
CREATE SCHEMA IF NOT EXISTS scbi_sdp_mart;

-- ============================================================================
-- 1. CONFORMED DIMENSIONS
-- ============================================================================

CREATE OR REPLACE VIEW scbi_sdp_mart.dim_date AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_sdp_mart/dim_date/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_member AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_member/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_fund AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_fund/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_client AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_client/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_employer AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_employer/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_portfolio AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_portfolio/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_investment_product AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_investment_product/*.parquet');

-- ============================================================================
-- 2. MEMBER ANALYSIS FACTS (DASHBOARD 1)
-- ============================================================================

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_investment_aua AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_investment_aua/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_base_contribution AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_base_contribution/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_segmentation AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_segmentation/*.parquet');

-- ============================================================================
-- 3. INVESTMENT ANALYSIS FACTS (DASHBOARD 2)
-- ============================================================================

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_inv_monthly_market_value AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_inv_monthly_market_value/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_monthly_investment AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_monthly_investment/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__agg_consolidated_member_measures_monthly AS
SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__agg_consolidated_member_measures_monthly/*.parquet');
