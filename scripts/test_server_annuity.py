import os
import duckdb
import datetime
from decimal import Decimal

# US-2.2: GCS HMAC credentials come from the environment, never from source.
GCS_ACCESS_KEY = os.environ["CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID"]
GCS_SECRET_KEY = os.environ["CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY"]

con = duckdb.connect()
con.execute(f"""
INSTALL httpfs;
LOAD httpfs;
SET s3_endpoint = 'storage.googleapis.com';
SET s3_url_style = 'path';
SET s3_access_key_id = '{GCS_ACCESS_KEY}';
SET s3_secret_access_key = '{GCS_SECRET_KEY}';
""")

print("Initializing in-memory view for ultra-fast queries...")
start = datetime.datetime.now()
con.execute("""
CREATE OR REPLACE VIEW fct_quotes AS 
SELECT * FROM read_parquet('s3://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_annuity_quotations/*.parquet')
WHERE DERIVED_QUOTATION_STATUS <> 'Accepted'
  AND NOT (DERIVED_QUOTATION_TYPE = 'Bulk' AND LOWER(SOURCE) = 'online');

CREATE OR REPLACE VIEW dim_broker AS 
SELECT * FROM read_parquet('s3://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_broker_consultant/*.parquet');

CREATE OR REPLACE VIEW dim_fund AS 
SELECT * FROM read_parquet('s3://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_fund/*.parquet');

CREATE OR REPLACE VIEW dim_product AS 
SELECT * FROM read_parquet('s3://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_annuity_product/*.parquet');
""")
print(f"Views created in {(datetime.datetime.now() - start).total_seconds():.2f}s")

# Test Slicers
q_slicers = """
SELECT 
    ARRAY_AGG(DISTINCT SUBSTR(CAST(DATE_NK AS VARCHAR), 1, 4) ORDER BY 1 DESC) as years,
    ARRAY_AGG(DISTINCT COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Unknown') ORDER BY 1) as businesses,
    ARRAY_AGG(DISTINCT COALESCE(f.DERIVED_BUSINESS_TYPE, 'Unknown') ORDER BY 1) as business_types,
    ARRAY_AGG(DISTINCT COALESCE(fd.FUND_NAME, f.FUND_NK) ORDER BY 1) as funds
FROM fct_quotes f
LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
"""
start = datetime.datetime.now()
slicers = con.execute(q_slicers).fetchone()
print(f"Slicers fetched in {(datetime.datetime.now() - start).total_seconds():.2f}s")
print("Years:", slicers[0][:6])
print("Businesses:", slicers[1][:8])
print("Business Types:", slicers[2][:6])
print("Funds sample:", slicers[3][:6])

# Test KPIs
q_kpis = """
SELECT 
    COUNT(DISTINCT f.QUOTED_MEMBER_ID_NUMBER) as quoted_members,
    COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTED_MEMBER_ID_NUMBER END) as accepted_members,
    COUNT(DISTINCT f.QUOTATION_NUMBER) as quotation_count,
    COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_NUMBER END) as accepted_quotations,
    SUM(CASE WHEN f.QUOTATION_NUMBER = f.LATEST_QUOTATION_NUMBER THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as quoted_price,
    SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as accepted_price
FROM fct_quotes f
"""
start = datetime.datetime.now()
kpis = con.execute(q_kpis).fetchone()
print(f"KPIs fetched in {(datetime.datetime.now() - start).total_seconds():.2f}s")
print("KPIs:", kpis)
