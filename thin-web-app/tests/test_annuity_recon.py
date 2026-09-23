"""
test_annuity_recon.py
Sprint 4 TDD Reconciliation Test Suite: Life Annuity Reporting (Quotes & Acceptances)
Validates live scbi-cube (Cloud Run) responses against Ground-Truth DuckDB GCS Lakehouse Marts.
"""

import os
import sys
import time
import json
import datetime
import urllib.request
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
sys.path.insert(0, str(WEB_DIR))

try:
    import jwt
except ImportError:
    jwt = None

CUBE_BASE_URL = os.environ.get("CUBEJS_BASE_URL", "https://scbi-cube-886154918734.europe-west1.run.app")
CUBE_SECRET = os.environ["CUBEJS_API_SECRET"]  # US-2.2: no in-code default


def get_ground_truth_duckdb():
    from annuity_engine import get_duckdb
    return get_duckdb()


def execute_cube_query(query_dict: dict, timeout_sec=60) -> list:
    now = datetime.datetime.now(datetime.timezone.utc)
    token = jwt.encode({
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(hours=2)).timestamp()),
        "role": "ROLE_EXECUTIVE_ALL",
        "canViewPii": True
    }, CUBE_SECRET, algorithm="HS256")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    url = f"{CUBE_BASE_URL}/cubejs-api/v1/load"
    payload = json.dumps({"query": query_dict}).encode("utf-8")

    start_wait = time.time()
    while (time.time() - start_wait) < timeout_sec:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("continueWait") or res.get("error") == "Continue wait":
                    time.sleep(2.0)
                    continue
                if "data" in res:
                    return res["data"]
        except Exception as e:
            time.sleep(2.0)
    return []


def test_story_4_1_timeline_conversion_rates():
    """US 4.1: Timeline & Conversion Rates parameterized by Brokerage (:selected_brokerage = 'Alexforbes')."""
    print("\n" + "=" * 80)
    print("RUNNING: User Story 4.1 - Life Annuity Timeline & Conversion Rates")
    print("=" * 80)

    con = get_ground_truth_duckdb()
    selected_brokerage = "Alexforbes"
    t0 = time.time()
    sql = f"""
    SELECT 
        COUNT(DISTINCT f.QUOTATION_NUMBER) as quotation_count,
        COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_NUMBER END) as accepted_count,
        ROUND(SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END), 2) as accepted_price
    FROM fct_quotes f
    LEFT JOIN dim_broker b ON f.QUOTED_BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
    WHERE b.BROKER_CONSULTANT_BUSINESS = '{selected_brokerage}'
      AND f.DATE_NK >= '2025-01-01' AND f.DATE_NK <= '2025-09-30';
    """
    row = con.execute(sql).fetchone()
    sql_time = round(time.time() - t0, 2)
    sql_quotes = int(row[0] or 0)
    sql_acc = int(row[1] or 0)
    sql_price = float(row[2] or 0.0)
    print(f"[Ground Truth SQL] Executed in {sql_time}s | Quotes: {sql_quotes:,} | Accepted: {sql_acc:,} | Accepted Price: R {sql_price:,.2f}")

    t1 = time.time()
    cube_query = {
        "measures": [
            "AnnuityQuotation.quotationCount",
            "AnnuityQuotation.acceptedQuotations",
            "AnnuityQuotation.acceptedPurchasePrice"
        ],
        "filters": [
            {"member": "DimBrokerConsultant.brokerConsultantBusiness", "operator": "equals", "values": [selected_brokerage]},
            {"member": "AnnuityQuotation.dateNk", "operator": "gte", "values": ["2025-01-01"]},
            {"member": "AnnuityQuotation.dateNk", "operator": "lte", "values": ["2025-09-30"]}
        ]
    }
    cube_data = execute_cube_query(cube_query)
    cube_time = round(time.time() - t1, 2)
    cube_quotes = int(cube_data[0].get("AnnuityQuotation.quotationCount") or 0) if cube_data else 0
    cube_acc = int(cube_data[0].get("AnnuityQuotation.acceptedQuotations") or 0) if cube_data else 0
    cube_price = float(cube_data[0].get("AnnuityQuotation.acceptedPurchasePrice") or 0.0) if cube_data else 0.0
    print(f"[Cube.js CloudRun] Executed in {cube_time}s | Quotes: {cube_quotes:,} | Accepted: {cube_acc:,} | Accepted Price: R {cube_price:,.2f}")

    speedup = round(sql_time / cube_time, 1) if cube_time > 0 else 1.0
    print(f"[Performance] Cube.js is {speedup}x faster than raw GCS DuckDB scan.")

    # Variance assertions
    diff_quotes = abs(sql_quotes - cube_quotes)
    diff_acc = abs(sql_acc - cube_acc)
    diff_price = abs(sql_price - cube_price)
    print(f"[Audit] Quote Delta: {diff_quotes} | Accepted Delta: {diff_acc} | Price Delta: R {diff_price:,.2f}")

    assert diff_quotes == 0, f"Quotation count mismatch: SQL {sql_quotes} != Cube {cube_quotes}"
    assert diff_acc == 0, f"Accepted count mismatch: SQL {sql_acc} != Cube {cube_acc}"
    assert diff_price < 0.01, f"Accepted price mismatch: SQL {sql_price} != Cube {cube_price}"
    print(">>> User Story 4.1: PASSED (0.00% Variance)\n")


def test_story_4_2_consultant_kpis():
    """US 4.2: Consultant & Conversion Performance KPIs."""
    print("\n" + "=" * 80)
    print("RUNNING: User Story 4.2 - Life Annuity KPIs & Conversion Performance")
    print("=" * 80)

    con = get_ground_truth_duckdb()
    t0 = time.time()
    sql = """
    SELECT 
        COUNT(DISTINCT f.QUOTED_MEMBER_ID_NUMBER) as quoted_members,
        COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTED_MEMBER_ID_NUMBER END) as accepted_members,
        COUNT(DISTINCT f.QUOTATION_NUMBER) as quotation_count,
        COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_NUMBER END) as accepted_quotations
    FROM fct_quotes f
    WHERE f.DATE_NK >= '2026-01-01';
    """
    row = con.execute(sql).fetchone()
    sql_time = round(time.time() - t0, 2)
    sql_q_mem = int(row[0] or 0)
    sql_acc_mem = int(row[1] or 0)
    sql_q_cnt = int(row[2] or 0)
    sql_acc_cnt = int(row[3] or 0)
    print(f"[Ground Truth SQL] Executed in {sql_time}s | Quoted Members: {sql_q_mem:,} | Accepted Members: {sql_acc_mem:,} | Quotes: {sql_q_cnt:,} | Accepted Quotes: {sql_acc_cnt:,}")

    t1 = time.time()
    cube_query = {
        "measures": [
            "AnnuityQuotation.quotedMembers",
            "AnnuityQuotation.acceptedMembers",
            "AnnuityQuotation.quotationCount",
            "AnnuityQuotation.acceptedQuotations"
        ],
        "filters": [
            {"member": "AnnuityQuotation.dateNk", "operator": "gte", "values": ["2026-01-01"]}
        ]
    }
    cube_data = execute_cube_query(cube_query)
    cube_time = round(time.time() - t1, 2)
    cube_q_mem = int(cube_data[0].get("AnnuityQuotation.quotedMembers") or 0) if cube_data else 0
    cube_acc_mem = int(cube_data[0].get("AnnuityQuotation.acceptedMembers") or 0) if cube_data else 0
    cube_q_cnt = int(cube_data[0].get("AnnuityQuotation.quotationCount") or 0) if cube_data else 0
    cube_acc_cnt = int(cube_data[0].get("AnnuityQuotation.acceptedQuotations") or 0) if cube_data else 0
    print(f"[Cube.js CloudRun] Executed in {cube_time}s | Quoted Members: {cube_q_mem:,} | Accepted Members: {cube_acc_mem:,} | Quotes: {cube_q_cnt:,} | Accepted Quotes: {cube_acc_cnt:,}")

    diff_q_mem = abs(sql_q_mem - cube_q_mem)
    diff_acc_mem = abs(sql_acc_mem - cube_acc_mem)
    diff_q_cnt = abs(sql_q_cnt - cube_q_cnt)
    diff_acc_cnt = abs(sql_acc_cnt - cube_acc_cnt)
    print(f"[Audit] Quoted Mem Delta: {diff_q_mem} | Accepted Mem Delta: {diff_acc_mem} | Quote Delta: {diff_q_cnt} | Accepted Quote Delta: {diff_acc_cnt}")

    assert diff_q_mem == 0, f"Quoted members mismatch: SQL {sql_q_mem} != Cube {cube_q_mem}"
    assert diff_acc_mem == 0, f"Accepted members mismatch: SQL {sql_acc_mem} != Cube {cube_acc_mem}"
    assert diff_q_cnt == 0, f"Quotation count mismatch: SQL {sql_q_cnt} != Cube {cube_q_cnt}"
    assert diff_acc_cnt == 0, f"Accepted count mismatch: SQL {sql_acc_cnt} != Cube {cube_acc_cnt}"
    print(">>> User Story 4.2: PASSED (0.00% Variance)\n")


if __name__ == "__main__":
    print("\n================================================================================")
    print(" Sprint 4 TDD Reconciliation: Life Annuity Reporting (Quotes & Acceptances)")
    print(" Target: scbi-cube (Cloud Run) vs GCS Lakehouse Marts")
    print("================================================================================")
    
    test_story_4_1_timeline_conversion_rates()
    test_story_4_2_consultant_kpis()

    print("=" * 80)
    print(" ALL SPRINT 4 ANNUITY RECONCILIATION TESTS PASSED (0.00% Variance)")
    print(" Results: 2 Passed, 0 Failed, 100% Reconciled with scbi-cube")
    print("================================================================================\n")
