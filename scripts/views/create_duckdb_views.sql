-- Auto-generated DuckDB External Views over GCS Parquet
-- Bucket: gs://scbi-ducklake-myanalyticsproduct/
-- Total Tables: 44 conformed facts, aggregations, and dimensions

INSTALL httpfs;
LOAD httpfs;

CREATE SCHEMA IF NOT EXISTS scbi_cdp_mart;
CREATE SCHEMA IF NOT EXISTS scbi_sdp_mart;
CREATE SCHEMA IF NOT EXISTS scbi_cdp_product;

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__agg_consolidated_member_measures_monthly AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__agg_consolidated_member_measures_monthly/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__agg_digital_portal_events_ytd AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__agg_digital_portal_events_ytd/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__agg_digital_portal_registrations_td AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__agg_digital_portal_registrations_td/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__agg_digital_portal_registrations_ytd AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__agg_digital_portal_registrations_ytd/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_admin_product AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_admin_product/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_aggregator AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_aggregator/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_annuity_product AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_annuity_product/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_bank_account AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_bank_account/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_beneficiary AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_beneficiary/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_broker_consultant AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_broker_consultant/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_claim_status AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_claim_status/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_claim_type AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_claim_type/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_client AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_client/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_digital_portal AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_digital_portal/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_digital_portal_user AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_digital_portal_user/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_employer AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_employer/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_employer_branch AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_employer_branch/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_fund AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_fund/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_insurer AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_insurer/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_investment_product AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_investment_product/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_member AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_member/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_paypoint AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_paypoint/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_revision_association AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_revision_association/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_risk_product AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_risk_product/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_service_offering AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_service_offering/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_transaction_type AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_transaction_type/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_annuity_quotations AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_annuity_quotations/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_digital_portal_events AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_digital_portal_events/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_digital_portal_registrations AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_digital_portal_registrations/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_investment_transactions AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_investment_transactions/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_inv_monthly_market_value AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_inv_monthly_market_value/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_in_fund_exit_member_aua_monthly AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_in_fund_exit_member_aua_monthly/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_in_fund_exit_member_aum_monthly AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_in_fund_exit_member_aum_monthly/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_base_contribution AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_base_contribution/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_base_risk_premium AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_base_risk_premium/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_claims AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_claims/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_claim_payment AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_claim_payment/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_investment_aua AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_investment_aua/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_investment_aum AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_investment_aum/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_monthly_fees AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_monthly_fees/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_segmentation AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_segmentation/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_transactions AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_transactions/*.parquet');
CREATE OR REPLACE VIEW scbi_cdp_product.cnf__prod_in_fund_exit_member_monthly AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_product/cnf__prod_in_fund_exit_member_monthly/*.parquet');
CREATE OR REPLACE VIEW scbi_sdp_mart.dim_date AS SELECT * FROM read_parquet('gs://scbi-ducklake-myanalyticsproduct/scbi_sdp_mart/dim_date/*.parquet');