import os
import duckdb

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

res = con.execute("SELECT COUNT(*) FROM read_parquet('s3://scbi-ducklake-myanalyticsproduct/scbi_sdp_mart/dim_date/*.parquet')").fetchall()
print('Date rows count:', res)

res2 = con.execute("SELECT COUNT(*), SUM(aua_amount) FROM read_parquet('s3://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_investment_aua/*.parquet')").fetchall()
print('Member investment AUA rows count and sum:', res2)
