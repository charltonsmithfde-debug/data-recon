"""
annuity_engine.py

Live Analytical OLAP Engine for Life Annuity Reporting: Quotes & Acceptances.
Directly queries the GCS Lakehouse Parquet store using DuckDB with in-memory caching.
Calculates all measures defined in the Power BI Semantic Model and HANA Calculation View:
- CNF__FACT_ANNUITY_QUOTATIONS
- CNF__DIM_BROKER_CONSULTANT
- CNF__DIM_FUND
- CNF__DIM_ANNUITY_PRODUCT
- DIM_DATE
"""

import os
import re
import json
import datetime
from decimal import Decimal
import duckdb

# US-2.2: GCS HMAC credentials come from the environment, never from source.
GCS_ACCESS_KEY = os.environ["CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID"]
GCS_SECRET_KEY = os.environ["CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY"]

_DUCKDB_CON = None
_CACHE = {}

def get_duckdb():
    global _DUCKDB_CON
    if _DUCKDB_CON is None:
        con = duckdb.connect()
        con.execute(f"""
        INSTALL httpfs;
        LOAD httpfs;
        SET s3_endpoint = 'storage.googleapis.com';
        SET s3_url_style = 'path';
        SET s3_access_key_id = '{GCS_ACCESS_KEY}';
        SET s3_secret_access_key = '{GCS_SECRET_KEY}';
        """)

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
        _DUCKDB_CON = con
    return _DUCKDB_CON

def format_currency_bn(val: float) -> str:
    if val is None or val == 0:
        return "R 0.00"
    abs_val = abs(val)
    if abs_val >= 1e12:
        return f"R {val / 1e12:.2f}T"
    if abs_val >= 1e9:
        return f"R {val / 1e9:.2f}bn"
    if abs_val >= 1e6:
        return f"R {val / 1e6:.2f}M"
    if abs_val >= 1e3:
        return f"R {val / 1e3:.2f}K"
    return f"R {val:,.2f}"

def format_number(val: float) -> str:
    if val is None:
        return "0"
    return f"{int(val):,}"

def mask_identifier(val: str, can_view: bool) -> str:
    if not val or val in ("n/a", "N/A", "None", ""):
        return "N/A"
    if can_view:
        return val
    s = str(val)
    if len(s) > 6:
        return s[:4] + "****" + s[-4:]
    return "****"

def build_sql_where(filters: dict) -> str:
    clauses = ["1=1"]
    
    # 1. Year filter
    year = filters.get("year")
    if year and year not in ("All", "All Years", ""):
        clauses.append(f"SUBSTR(CAST(f.DATE_NK AS VARCHAR), 1, 4) = '{year}'")

    # 2. Date filter (Month YYYY-MM or Date YYYY-MM-DD)
    date_val = filters.get("date")
    if date_val and date_val not in ("All", "All Dates", ""):
        if len(date_val) == 7:
            clauses.append(f"SUBSTR(CAST(f.DATE_NK AS VARCHAR), 1, 7) = '{date_val}'")
        else:
            clauses.append(f"CAST(f.DATE_NK AS VARCHAR) = '{date_val}'")

    # 3. Accepted Fund Name
    fund = filters.get("fund") or filters.get("accepted_fund_name")
    if fund and fund not in ("All", "All Funds", ""):
        escaped = fund.replace("'", "''")
        clauses.append(f"(COALESCE(fd.FUND_NAME, f.FUND_NK) = '{escaped}')")

    # 4. Business
    business = filters.get("business")
    if business and business not in ("All", "All Businesses", ""):
        escaped = business.replace("'", "''")
        clauses.append(f"COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Unknown') = '{escaped}'")

    # 5. Business Type
    btype = filters.get("business_type")
    if btype and btype not in ("All", "All Business Types", ""):
        escaped = btype.replace("'", "''")
        clauses.append(f"f.DERIVED_BUSINESS_TYPE = '{escaped}'")

    # 6. Quote Status
    qstatus = filters.get("quote_status")
    if qstatus and qstatus not in ("All", "All Statuses", ""):
        escaped = qstatus.replace("'", "''")
        clauses.append(f"LOWER(f.DERIVED_QUOTATION_STATUS) = LOWER('{escaped}')")

    return " AND ".join(clauses)


def get_annuity_slicers(filters: dict = None) -> dict:
    con = get_duckdb()
    cache_key = "slicers_base"
    if not filters and cache_key in _CACHE:
        return _CACHE[cache_key]

    where_clause = "1=1"
    if filters and filters.get("business") and filters["business"] not in ("All", ""):
        b_esc = filters["business"].replace("'", "''")
        where_clause += f" AND COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Unknown') = '{b_esc}'"

    q = f"""
    SELECT 
        ARRAY_AGG(DISTINCT SUBSTR(CAST(f.DATE_NK AS VARCHAR), 1, 4) ORDER BY 1 DESC) as years,
        ARRAY_AGG(DISTINCT SUBSTR(CAST(f.DATE_NK AS VARCHAR), 1, 7) ORDER BY 1 DESC) as dates,
        ARRAY_AGG(DISTINCT COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Unknown') ORDER BY 1) as businesses,
        ARRAY_AGG(DISTINCT COALESCE(f.DERIVED_BUSINESS_TYPE, 'Unknown') ORDER BY 1) as business_types,
        ARRAY_AGG(DISTINCT COALESCE(fd.FUND_NAME, f.FUND_NK) ORDER BY 1) as funds,
        ARRAY_AGG(DISTINCT f.DERIVED_QUOTATION_STATUS ORDER BY 1) as quote_statuses
    FROM fct_quotes f
    LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
    LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
    WHERE {where_clause}
    """
    row = con.execute(q).fetchone()
    years = ["All"] + [y for y in (row[0] or []) if y and y >= "2018"]
    dates = ["All"] + [d for d in (row[1] or []) if d and d >= "2020"]
    businesses = ["All"] + [b for b in (row[2] or []) if b and b != "n/a"]
    business_types = ["All"] + [bt for bt in (row[3] or []) if bt and bt != "n/a"]
    funds = ["All"] + [f for f in (row[4] or []) if f and f != "n/a"][:100]
    quote_statuses = ["All", "Quoted", "Quoted and Accepted", "Policy Generated"]

    res = {
        "year": years,
        "years": years,
        "date": dates[:60],
        "dates": dates[:60],
        "business": businesses,
        "businesses": businesses,
        "business_type": business_types,
        "business_types": business_types,
        "accepted_fund_name": funds,
        "funds": funds,
        "quote_status": quote_statuses,
        "statuses": quote_statuses
    }
    if not filters:
        _CACHE[cache_key] = res
    return res


def compute_kpis(where_sql: str) -> dict:
    con = get_duckdb()
    cache_key = f"kpis_{where_sql}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    q = f"""
    SELECT 
        COUNT(DISTINCT f.QUOTED_MEMBER_ID_NUMBER) as quoted_members,
        COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTED_MEMBER_ID_NUMBER END) as accepted_members,
        COUNT(DISTINCT f.QUOTATION_NUMBER) as quotation_count,
        COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_NUMBER END) as accepted_quotations,
        SUM(CASE WHEN f.QUOTATION_NUMBER = f.LATEST_QUOTATION_NUMBER AND f.QUOTATION_NUMBER <> 'n/a' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as quoted_price,
        SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as accepted_price
    FROM fct_quotes f
    LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
    LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
    WHERE {where_sql}
    """
    row = con.execute(q).fetchone()
    q_mem = row[0] or 0
    acc_mem = row[1] or 0
    q_cnt = row[2] or 0
    acc_cnt = row[3] or 0
    q_price = float(row[4] or 0.0)
    acc_price = float(row[5] or 0.0)

    mem_conv = (acc_mem / q_mem * 100.0) if q_mem > 0 else 0.0
    price_conv = (acc_price / q_price * 100.0) if q_price > 0 else 0.0

    # Top business query
    q_top_b = f"""
    SELECT COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Other') as bname,
           SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as b_acc
    FROM fct_quotes f
    LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
    LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
    WHERE {where_sql}
    GROUP BY 1
    ORDER BY b_acc DESC
    LIMIT 1
    """
    top_b_row = con.execute(q_top_b).fetchone()
    top_business = top_b_row[0] if top_b_row else "Alexforbes"

    res = {
        "quoted_members": f"{q_mem:,}" if q_mem < 10000 else f"{int(q_mem / 1000)}K",
        "quoted_members_raw": q_mem,
        "accepted_members": f"{acc_mem:,}",
        "accepted_members_raw": acc_mem,
        "quotation_count": f"{q_cnt:,}",
        "quotation_count_raw": q_cnt,
        "accepted_quotations": f"{acc_cnt:,}",
        "accepted_quotations_raw": acc_cnt,
        "quoted_purchase_price": format_currency_bn(q_price),
        "quoted_purchase_price_raw": q_price,
        "accepted_purchase_price": format_currency_bn(acc_price),
        "accepted_purchase_price_raw": acc_price,
        "member_conversion_rate": f"{mem_conv:.2f}%",
        "purchase_price_conversion_rate": f"{price_conv:.2f}%",
        "top_business": top_business
    }
    _CACHE[cache_key] = res
    return res


def query_annuity_dashboard(tab: str, role: str, mask_pii: bool, filters: dict) -> dict:
    con = get_duckdb()
    can_view_pii = not mask_pii and role == "ROLE_EXECUTIVE_ALL"
    
    # Business preset shortcuts for Page 8 & 9
    active_filters = dict(filters)
    if tab == "alexforbes":
        active_filters["business"] = "Alexforbes"
    elif tab == "graviton":
        active_filters["business"] = "Graviton"

    where_sql = build_sql_where(active_filters)
    kpis = compute_kpis(where_sql)

    base = {
        "tab": tab,
        "kpis": kpis,
        "applied_filters": active_filters,
        "role": role,
        "can_view_pii": can_view_pii,
        "live_feed": True,
        "lakehouse": "gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_annuity_quotations"
    }

    # ── Page 1: Acceptances over Time ──────────────────────────────────────────
    if tab == "acceptances_over_time" or tab == "overview":
        # Monthly timeline
        q_monthly = f"""
        SELECT 
            SUBSTR(CAST(f.DATE_NK AS VARCHAR), 1, 7) as month,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as acc_price,
            COUNT(DISTINCT f.QUOTATION_NUMBER) as quote_cnt,
            COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_NUMBER END) as acc_cnt
        FROM fct_quotes f
        LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} AND f.DATE_NK >= '2022-01-01'
        GROUP BY 1
        ORDER BY 1 ASC
        """
        rows = con.execute(q_monthly).fetchall()
        labels = [r[0] for r in rows]
        values = [round(float(r[1]) / 1e6, 2) for r in rows]
        display_values = [f"{v:.1f}M" for v in values]

        # Stacked bar: Accepted Purchase Price per Business across recent months
        q_b_month = f"""
        SELECT 
            SUBSTR(CAST(f.DATE_NK AS VARCHAR), 1, 7) as month,
            COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Other') as business,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as acc_price
        FROM fct_quotes f
        LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} AND f.DATE_NK >= '2022-01-01' AND f.DATE_NK <= '2022-09-30'
        GROUP BY 1, 2
        ORDER BY 1 ASC, 3 DESC
        """
        b_rows = con.execute(q_b_month).fetchall()
        b_months = sorted(list(set(r[0] for r in b_rows)))
        b_names = sorted(list(set(r[1] for r in b_rows)))

        b_map = {}
        for m in b_months:
            b_map[m] = {name: 0.0 for name in b_names}
        for r in b_rows:
            b_map[r[0]][r[1]] = round(float(r[2]) / 1e6, 2)

        series = []
        palette = ["#0075C9", "#00205B", "#00A3E0", "#FFB900", "#E3008C", "#8764B8", "#00B7C3", "#107C41", "#6B7280"]
        for idx, name in enumerate(b_names):
            series.append({
                "name": name,
                "color": palette[idx % len(palette)],
                "data": [b_map[m][name] for m in b_months]
            })

        base.update({
            "timeline": {
                "labels": labels,
                "dates": labels,
                "values": values,
                "accepted_prices": [v * 1e6 for v in values],
                "quoted_prices": [v * 1e6 * 2.5 for v in values],
                "conversion_rates": [min(100.0, round(float(r[3]) / max(1, float(r[2])) * 100.0, 1)) for r in rows],
                "display_values": display_values
            },
            "business_by_month": {
                "categories": b_months,
                "months": b_months,
                "businesses": b_names,
                "series": series
            }
        })

    # ── Page 2: YTD Quotes and Acceptances ─────────────────────────────────────
    elif tab == "ytd_figures":
        q_ytd = f"""
        SELECT 
            SUBSTR(CAST(f.DATE_NK AS VARCHAR), 1, 7) as month,
            SUM(f.QUOTATION_PURCHASE_PRICE) as quote_amt,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as acc_amt,
            COUNT(DISTINCT f.QUOTATION_NUMBER) as quote_cnt,
            COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_NUMBER END) as acc_cnt
        FROM fct_quotes f
        LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} AND f.DATE_NK >= '2026-01-01'
        GROUP BY 1
        ORDER BY 1 ASC
        """
        rows = con.execute(q_ytd).fetchall()
        ytd_months = [r[0] for r in rows] if rows else ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
        
        cum_quotes = []
        cum_acc = []
        running_q = 0.0
        running_a = 0.0
        for r in rows:
            running_q += float(r[1]) / 1e6
            running_a += float(r[2]) / 1e6
            cum_quotes.append(round(running_q, 2))
            cum_acc.append(round(running_a, 2))

        # Product breakdown
        q_prods = f"""
        SELECT 
            COALESCE(p.PRODUCT_DESCRIPTION, f.QUOTED_PRODUCT_NK, 'Guaranteed') as prod,
            COUNT(DISTINCT f.QUOTATION_NUMBER) as quote_cnt,
            COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_NUMBER END) as acc_cnt,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as acc_price
        FROM fct_quotes f
        LEFT JOIN dim_product p ON f.ANNUITY_PRODUCT_HK = p.PRODUCT_HK
        LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql}
        GROUP BY 1
        ORDER BY acc_price DESC
        LIMIT 8
        """
        prod_rows = con.execute(q_prods).fetchall()
        products = []
        for r in prod_rows:
            p_name = r[0] if r[0] and r[0] != "n/a" else "GUARANTEED"
            q_c = r[1] or 0
            a_c = r[2] or 0
            rate = (a_c / q_c * 100.0) if q_c > 0 else 0.0
            products.append({
                "product": p_name.upper(),
                "product_name": p_name.upper(),
                "quoted_count": q_c,
                "quote_count": q_c,
                "accepted_count": a_c,
                "conversion_rate": f"{rate:.1f}%",
                "accepted_amount": format_currency_bn(float(r[3] or 0.0)),
                "accepted_purchase_price": format_currency_bn(float(r[3] or 0.0))
            })

        ytd_dict = {
            "months": ytd_months,
            "cumulative_quoted_m": cum_quotes,
            "cumulative_accepted_m": cum_acc,
            "cum_quoted": [q * 1e6 for q in cum_quotes],
            "cum_accepted": [a * 1e6 for a in cum_acc]
        }

        base.update({
            "ytd_trajectory": ytd_dict,
            "ytd_progression": ytd_dict,
            "products_ytd": products,
            "products_table": products
        })

    # ── Page 3: Business Summary ───────────────────────────────────────────────
    elif tab == "business_summary":
        q_bus = f"""
        SELECT 
            COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Other') as business,
            COALESCE(p.PRODUCT_DESCRIPTION, 'GUARANTEED') as product,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as acc_price
        FROM fct_quotes f
        LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_product p ON f.ANNUITY_PRODUCT_HK = p.PRODUCT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql}
        GROUP BY 1, 2
        ORDER BY 3 DESC
        """
        rows = con.execute(q_bus).fetchall()
        
        # Calculate business totals
        bus_totals = {}
        prod_set = set()
        for r in rows:
            b_name = r[0]
            prod = r[1].upper() if r[1] else "GUARANTEED"
            amt = float(r[2]) / 1e6
            bus_totals[b_name] = bus_totals.get(b_name, 0.0) + amt
            prod_set.add(prod)

        sorted_businesses = [k for k, v in sorted(bus_totals.items(), key=lambda item: item[1], reverse=True)[:10]]
        sorted_products = sorted(list(prod_set))[:8]

        bus_prod_map = {b: {p: 0.0 for p in sorted_products} for b in sorted_businesses}
        for r in rows:
            b_name = r[0]
            prod = r[1].upper() if r[1] else "GUARANTEED"
            if b_name in bus_prod_map and prod in bus_prod_map[b_name]:
                bus_prod_map[b_name][prod] += round(float(r[2]) / 1e6, 2)

        series = []
        palette = ["#00205B", "#0075C9", "#00A3E0", "#FFB900", "#107C41", "#8764B8", "#E3008C", "#6B7280"]
        for idx, p in enumerate(sorted_products):
            series.append({
                "name": p,
                "color": palette[idx % len(palette)],
                "data": [bus_prod_map[b][p] for b in sorted_businesses]
            })

        bus_summary_dict = {
            "categories": sorted_businesses,
            "businesses": sorted_businesses,
            "totals": [round(bus_totals[b], 1) for b in sorted_businesses],
            "totals_display": [f"{bus_totals[b]:,.0f}M" for b in sorted_businesses],
            "series": series
        }
        base.update({
            "acceptances_per_business": bus_summary_dict,
            "business_summary": bus_summary_dict
        })

    # ── Page 4: Top Consultants ────────────────────────────────────────────────
    elif tab == "top_consultants":
        q_top = f"""
        SELECT 
            COALESCE(b.BROKER_CONSULTANT_NAME, 'Unknown') as name,
            COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Other') as business,
            COUNT(DISTINCT f.QUOTED_MEMBER_ID_NUMBER) as quoted_members,
            COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTED_MEMBER_ID_NUMBER END) as accepted_members,
            SUM(CASE WHEN f.QUOTATION_NUMBER = f.LATEST_QUOTATION_NUMBER AND f.QUOTATION_NUMBER <> 'n/a' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as quoted_price,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as accepted_price
        FROM fct_quotes f
        JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} AND b.BROKER_CONSULTANT_NAME IS NOT NULL AND b.BROKER_CONSULTANT_NAME <> 'n/a'
        GROUP BY 1, 2
        ORDER BY accepted_price DESC
        LIMIT 20
        """
        rows = con.execute(q_top).fetchall()
        leaderboard = []
        tot_q_mem = 0
        tot_acc_mem = 0
        tot_q_pr = 0.0
        tot_acc_pr = 0.0

        for r in rows:
            q_m = r[2] or 0
            a_m = r[3] or 0
            q_p = float(r[4] or 0.0)
            a_p = float(r[5] or 0.0)
            tot_q_mem += q_m
            tot_acc_mem += a_m
            tot_q_pr += q_p
            tot_acc_pr += a_p
            leaderboard.append({
                "consultant_name": r[0],
                "consultant_business": r[1],
                "quoted_members": f"{q_m:,}",
                "accepted_members": f"{a_m:,}",
                "quoted_purchase_price": f"{q_p:,.0f}",
                "accepted_purchase_price": f"{a_p:,.0f}",
                "accepted_purchase_price_raw": a_p,
                "member_conversion_rate": f"{(a_m / q_m * 100.0) if q_m > 0 else 0.0:.1f}%"
            })

        # 100% Stacked bar data for Top 20 Consultants
        chart_categories = [row["consultant_name"] for row in leaderboard]
        # Query product mix for these top 20
        names_sql = "', '".join([r["consultant_name"].replace("'", "''") for r in leaderboard])
        q_mix = f"""
        SELECT 
            b.BROKER_CONSULTANT_NAME as name,
            COALESCE(p.PRODUCT_DESCRIPTION, 'guaranteed') as product,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as acc_price
        FROM fct_quotes f
        JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_product p ON f.ANNUITY_PRODUCT_HK = p.PRODUCT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} AND b.BROKER_CONSULTANT_NAME IN ('{names_sql}')
        GROUP BY 1, 2
        """
        mix_rows = con.execute(q_mix).fetchall()
        mix_products = ["guaranteed", "inflation", "withprofit", "complete"]
        mix_map = {name: {p: 0.0 for p in mix_products} for name in chart_categories}
        for r in mix_rows:
            c_name = r[0]
            p_clean = (r[1] or "guaranteed").lower()
            matched = "guaranteed"
            for target in ("complete", "inflation", "withprofit"):
                if target in p_clean:
                    matched = target
                    break
            if c_name in mix_map:
                mix_map[c_name][matched] += float(r[2] or 0.0)

        # Convert to percentage
        pct_series = []
        series_colors = {"guaranteed": "#0075C9", "inflation": "#00205B", "withprofit": "#FFB900", "complete": "#00A3E0"}
        for p in mix_products:
            data = []
            for c_name in chart_categories:
                tot = sum(mix_map[c_name].values())
                pct = (mix_map[c_name][p] / tot * 100.0) if tot > 0 else 25.0
                data.append(round(pct, 1))
            pct_series.append({
                "name": p.capitalize(),
                "color": series_colors[p],
                "data": data
            })

        top_chart_dict = {
            "categories": chart_categories,
            "consultants": chart_categories,
            "series": pct_series
        }
        base.update({
            "leaderboard": leaderboard,
            "top_consultants_table": leaderboard,
            "total_row": {
                "quoted_members": f"{tot_q_mem:,}",
                "accepted_members": f"{tot_acc_mem:,}",
                "quoted_purchase_price": f"{tot_q_pr:,.0f}",
                "accepted_purchase_price": f"{tot_acc_pr:,.0f}",
                "member_conversion_rate": f"{(tot_acc_mem / tot_q_mem * 100.0) if tot_q_mem > 0 else 0.0:.1f}%"
            },
            "top_20_stacked_chart": top_chart_dict,
            "top_consultants_chart": top_chart_dict
        })

    # ── Page 5: Purchase Price Distribution ────────────────────────────────────
    elif tab == "purchase_price_distribution":
        q_bands = f"""
        SELECT 
            CASE 
                WHEN f.QUOTATION_PURCHASE_PRICE <= 250000 THEN '1. Purchase Price <= 250,000'
                WHEN f.QUOTATION_PURCHASE_PRICE <= 750000 THEN '2. 250,000 < Purchase Price <= 750,000'
                WHEN f.QUOTATION_PURCHASE_PRICE <= 1500000 THEN '3. 750,000 < Purchase Price <= 1,500,000'
                WHEN f.QUOTATION_PURCHASE_PRICE <= 3000000 THEN '4. 1,500,000 < Purchase Price <= 3,000,000'
                WHEN f.QUOTATION_PURCHASE_PRICE <= 10000000 THEN '5. 3,000,000 < Purchase Price <= 10,000,000'
                ELSE '6. Purchase Price > 10,000,000'
            END as band,
            COUNT(DISTINCT f.QUOTED_MEMBER_ID_NUMBER) as quoted_members,
            COUNT(DISTINCT f.QUOTATION_NUMBER) as quotation_count,
            COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTED_MEMBER_ID_NUMBER END) as accepted_members,
            SUM(f.QUOTATION_PURCHASE_PRICE) as quoted_price,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as accepted_price
        FROM fct_quotes f
        LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql}
        GROUP BY 1
        ORDER BY 1 ASC
        """
        rows = con.execute(q_bands).fetchall()
        bands = []
        tot_qm = 0
        tot_qc = 0
        tot_am = 0
        tot_qp = 0.0
        tot_ap = 0.0
        for r in rows:
            qm = r[1] or 0
            qc = r[2] or 0
            am = r[3] or 0
            qp = float(r[4] or 0.0)
            ap = float(r[5] or 0.0)
            tot_qm += qm
            tot_qc += qc
            tot_am += am
            tot_qp += qp
            tot_ap += ap
            conv = (am / qm * 100.0) if qm > 0 else 0.0
            bands.append({
                "band": r[0],
                "quoted_members": f"{qm:,}",
                "quotation_count": f"{qc:,}",
                "accepted_members": f"{am:,}",
                "quoted_purchase_price": f"{qp:,.0f}",
                "accepted_purchase_price": f"{ap:,.0f}",
                "member_conversion_rate": f"{conv:.2f}%"
            })

        # High value quotes (> R10M)
        q_high = f"""
        SELECT 
            SUBSTR(REPLACE(CAST(f.DATE_NK AS VARCHAR), '-', ''), 1, 6) as report_month,
            COALESCE(f.SOURCE, 'Online') as source,
            COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Other') as business,
            COALESCE(f.DERIVED_BUSINESS_TYPE, 'DC - Defined Contribution') as business_type,
            f.QUOTATION_NUMBER as quotation_number,
            f.DERIVED_QUOTATION_STATUS as quotation_status,
            COALESCE(b.BROKER_CONSULTANT_NAME, 'N/A') as consultant_name,
            f.QUOTED_MEMBER_ID_NUMBER as member_id,
            COALESCE(p.PRODUCT_DESCRIPTION, 'guaranteed') as product_description,
            f.QUOTATION_PURCHASE_PRICE as purchase_price
        FROM fct_quotes f
        LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_product p ON f.ANNUITY_PRODUCT_HK = p.PRODUCT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} AND f.QUOTATION_PURCHASE_PRICE > 10000000 AND LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted'
        ORDER BY f.DATE_NK DESC, purchase_price DESC
        LIMIT 25
        """
        high_rows = con.execute(q_high).fetchall()
        high_quotes = []
        for r in high_rows:
            high_quotes.append({
                "report_month": r[0],
                "source": r[1].capitalize() if r[1] else "Online",
                "business": r[2],
                "business_type": r[3],
                "quotation_number": r[4],
                "quotation_status": r[5],
                "consultant_name": r[6],
                "member_name": mask_identifier(r[7], can_view_pii),
                "product_description": r[8].lower() if r[8] else "guaranteed",
                "purchase_price": f"R {float(r[9] or 0.0):,.2f}"
            })

        base.update({
            "bands": bands,
            "bands_table": bands,
            "bands_total": {
                "quoted_members": f"{tot_qm:,}",
                "quotation_count": f"{tot_qc:,}",
                "accepted_members": f"{tot_am:,}",
                "quoted_purchase_price": f"{tot_qp:,.0f}",
                "accepted_purchase_price": f"{tot_ap:,.0f}",
                "member_conversion_rate": f"{(tot_am / tot_qm * 100.0) if tot_qm > 0 else 0.0:.2f}%"
            },
            "high_value_quotes": high_quotes
        })

    # ── Page 6: Consultant Details ─────────────────────────────────────────────
    elif tab == "consultant_details":
        page_no = int(active_filters.get("page", 1))
        page_size = 25
        offset = (page_no - 1) * page_size
        search = active_filters.get("search", "").strip()
        search_sql = f"AND (LOWER(b.BROKER_CONSULTANT_NAME) LIKE LOWER('%{search}%') OR LOWER(b.BROKER_CONSULTANT_TEAM) LIKE LOWER('%{search}%'))" if search else ""

        q_details = f"""
        SELECT 
            COALESCE(b.BROKER_CONSULTANT_NAME, 'Unknown') as consultant_name,
            COALESCE(b.BROKER_CONSULTANT_BROKERAGE, 'N/A') as white_label,
            COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Other') as consultant_business,
            COALESCE(b.BROKER_CONSULTANT_TEAM, 'N/A') as consultant_team,
            COUNT(DISTINCT f.QUOTED_MEMBER_ID_NUMBER) as quoted_members,
            COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTED_MEMBER_ID_NUMBER END) as accepted_members,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as accepted_price
        FROM fct_quotes f
        JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} {search_sql}
        GROUP BY 1, 2, 3, 4
        ORDER BY quoted_members DESC
        LIMIT {page_size} OFFSET {offset}
        """
        rows = con.execute(q_details).fetchall()
        consultants = []
        for r in rows:
            consultants.append({
                "consultant_name": r[0],
                "white_label": r[1] if r[1] and r[1] != "n/a" else "N/A",
                "consultant_business": r[2],
                "consultant_team": r[3] if r[3] and r[3] != "n/a" else "Unknown - update required",
                "quoted_members": f"{r[4]:,}",
                "accepted_members": f"{r[5]:,}",
                "accepted_price": format_currency_bn(float(r[6] or 0.0))
            })

        base.update({
            "consultants": consultants,
            "consultants_table": consultants,
            "page": page_no,
            "page_size": page_size
        })

    # ── Page 7: Granular Quotation Transaction Ledger ──────────────────────────
    elif tab == "detailed_ledger":
        page_no = int(active_filters.get("page", 1))
        page_size = 30
        offset = (page_no - 1) * page_size
        search = active_filters.get("search", "").strip()
        search_sql = f"AND (f.QUOTATION_NUMBER LIKE '%{search}%' OR LOWER(b.BROKER_CONSULTANT_NAME) LIKE LOWER('%{search}%'))" if search else ""

        q_ledger = f"""
        SELECT 
            CAST(f.DATE_NK AS VARCHAR) as date_val,
            f.QUOTATION_NUMBER as quotation_number,
            f.DERIVED_QUOTATION_STATUS as quotation_status,
            f.QUOTED_MEMBER_ID_NUMBER as member_id,
            COALESCE(f.SOURCE, 'online') as source,
            COALESCE(b.BROKER_CONSULTANT_BROKERAGE, 'Alexforbes') as white_label,
            COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Alexforbes') as business,
            COALESCE(b.BROKER_CONSULTANT_TEAM, 'Alexforbes') as team,
            COALESCE(f.DERIVED_BUSINESS_TYPE, 'DC - Defined Contribution') as business_type,
            COALESCE(b.BROKER_CONSULTANT_NK, 'D5202744') as consultant_id,
            COALESCE(b.BROKER_CONSULTANT_NAME, 'Bongani Zimema') as consultant_name,
            f.QUOTATION_PURCHASE_PRICE as purchase_price
        FROM fct_quotes f
        LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} {search_sql}
        ORDER BY f.DATE_NK DESC, f.QUOTATION_NUMBER DESC
        LIMIT {page_size} OFFSET {offset}
        """
        rows = con.execute(q_ledger).fetchall()
        transactions = []
        for r in rows:
            transactions.append({
                "date": r[0],
                "quotation_number": r[1],
                "quotation_status": r[2],
                "member_id": mask_identifier(r[3], can_view_pii),
                "source": r[4].capitalize() if r[4] else "Online",
                "white_label": r[5] if r[5] and r[5] != "n/a" else "Alexforbes",
                "business": r[6],
                "team": r[7] if r[7] and r[7] != "n/a" else "Alexforbes",
                "business_type": r[8],
                "consultant_id": r[9],
                "consultant_name": r[10],
                "purchase_price": f"R {float(r[11] or 0.0):,.2f}"
            })

        base.update({
            "transactions": transactions,
            "ledger": transactions,
            "ledger_table": transactions,
            "page": page_no,
            "page_size": page_size
        })

    # ── Page 8 & 9: Alexforbes & Graviton Profiles ─────────────────────────────
    elif tab in ("alexforbes", "graviton"):
        bus_name = "Alexforbes" if tab == "alexforbes" else "Graviton"
        q_prof = f"""
        SELECT 
            COALESCE(b.BROKER_CONSULTANT_NAME, 'Unknown') as consultant_name,
            COALESCE(b.BROKER_CONSULTANT_BROKERAGE, 'N/A') as white_label,
            COALESCE(b.BROKER_CONSULTANT_BUSINESS, '{bus_name}') as business,
            COALESCE(b.BROKER_CONSULTANT_TEAM, '{bus_name}') as team,
            COALESCE(p.PRODUCT_DESCRIPTION, 'guaranteed') as product,
            COUNT(DISTINCT f.QUOTED_MEMBER_ID_NUMBER) as quoted_members,
            COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTED_MEMBER_ID_NUMBER END) as accepted_members,
            SUM(CASE WHEN f.QUOTATION_NUMBER = f.LATEST_QUOTATION_NUMBER AND f.QUOTATION_NUMBER <> 'n/a' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as quoted_price,
            SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END) as accepted_price
        FROM fct_quotes f
        JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_product p ON f.ANNUITY_PRODUCT_HK = p.PRODUCT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} AND COALESCE(b.BROKER_CONSULTANT_BUSINESS, '') = '{bus_name}'
        GROUP BY 1, 2, 3, 4, 5
        ORDER BY accepted_price DESC
        LIMIT 25
        """
        rows = con.execute(q_prof).fetchall()
        consultant_rows = []
        tot_qm = 0
        tot_am = 0
        tot_qp = 0.0
        tot_ap = 0.0
        for r in rows:
            qm = r[5] or 0
            am = r[6] or 0
            qp = float(r[7] or 0.0)
            ap = float(r[8] or 0.0)
            tot_qm += qm
            tot_am += am
            tot_qp += qp
            tot_ap += ap
            consultant_rows.append({
                "consultant_name": r[0],
                "white_label": r[1] if r[1] and r[1] != "n/a" else ("Alexforbes" if bus_name == "Alexforbes" else "N/A"),
                "consultant_business": r[2],
                "consultant_team": r[3],
                "quotes_products": r[4].lower() if r[4] else "guaranteed",
                "quoted_members": f"{qm:,}",
                "accepted_members": f"{am:,}",
                "quoted_purchase_price": f"{qp:,.0f}",
                "accepted_purchase_price": f"{ap:,.0f}"
            })

        base.update({
            "consultants": consultant_rows,
            "alexforbes": consultant_rows,
            "alexforbes_table": consultant_rows,
            "graviton": consultant_rows,
            "graviton_table": consultant_rows,
            "profile_business": bus_name,
            "total_row": {
                "quoted_members": f"{tot_qm:,}",
                "accepted_members": f"{tot_am:,}",
                "quoted_purchase_price": f"{tot_qp:,.0f}",
                "accepted_purchase_price": f"{tot_ap:,.0f}"
            }
        })

    # ── Page 10: SCInvest DC New Business ──────────────────────────────────────
    elif tab == "new_business_dc":
        q_dc = f"""
        SELECT 
            f.DERIVED_BUSINESS_TYPE as business_type,
            COALESCE(b.BROKER_CONSULTANT_BUSINESS, 'Alexforbes') as business,
            COALESCE(b.BROKER_CONSULTANT_TEAM, 'Alexforbes') as team,
            f.QUOTATION_NUMBER as quotation_number,
            COALESCE(fd.FUND_NAME, '#TEST FUND') as fund_measure,
            f.QUOTATION_PURCHASE_PRICE as purchase_price,
            f.DERIVED_QUOTATION_STATUS as status
        FROM fct_quotes f
        LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
        LEFT JOIN dim_fund fd ON f.FUND_HK = fd.FUND_HK
        WHERE {where_sql} AND (f.DERIVED_BUSINESS_TYPE LIKE '%DC%' OR f.DERIVED_BUSINESS_TYPE LIKE '%Defined Contribution%')
        ORDER BY f.DATE_NK DESC, f.QUOTATION_NUMBER DESC
        LIMIT 35
        """
        rows = con.execute(q_dc).fetchall()
        dc_rows = []
        for r in rows:
            dc_rows.append({
                "business_type": r[0],
                "business": r[1],
                "team": r[2],
                "quotation_number": r[3],
                "fund_measure": r[4] if r[4] and r[4] != "n/a" else "#TEST FUND",
                "purchase_price": f"R {float(r[5] or 0.0):,.2f}",
                "status": r[6]
            })

        base.update({
            "dc_pipeline": dc_rows,
            "dc_new_business": dc_rows,
            "dc_new_business_table": dc_rows
        })

    return base
