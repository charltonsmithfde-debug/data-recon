import os
import snowflake.connector

conn = snowflake.connector.connect(
    account='gw52249.eu-west-1',
    user='G988557',
    role='ARDEVSCBIPRODUCTDEVELOPERSF',
    warehouse='SC_BI_PRODUCT_PPE_WH',
    database='SC_BI_PRODUCT_PPE',
    authenticator='externalbrowser'
)
cur = conn.cursor()
tables = [
    'CNF__AGG_DIGITAL_PORTAL_REGISTRATIONS_TD',
    'CNF__AGG_DIGITAL_PORTAL_EVENTS_YTD',
    'CNF__FACT_MEMBER_MONTHLY_FEES',
    'CNF__FACT_MEMBER_INVESTMENT_AUM',
    'CNF__FACT_DIGITAL_PORTAL_EVENTS',
    'CNF__FACT_MEMBER_INVESTMENT_AUA',
    'CNF__FACT_MEMBER_BASE_RISK_PREMIUM',
    'CNF__FACT_MEMBER_TRANSACTIONS',
    'CNF__FACT_MEMBER_BASE_CONTRIBUTION',
    'CNF__FACT_MEMBER_SEGMENTATION',
    'CNF__AGG_CONSOLIDATED_MEMBER_MEASURES_MONTHLY'
]
for t in tables:
    cur.execute(f"""
        SELECT COLUMN_NAME, DATA_TYPE
        FROM SC_BI_PRODUCT_PPE.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'SCBI_CDP_MART' AND TABLE_NAME = '{t}' AND (COLUMN_NAME LIKE '%DATE%' OR COLUMN_NAME LIKE '%MONTH%')
        ORDER BY ORDINAL_POSITION
    """)
    print(f"{t}:")
    for row in cur.fetchall():
        print(f"   {row[0]} ({row[1]})")
cur.close()
conn.close()
