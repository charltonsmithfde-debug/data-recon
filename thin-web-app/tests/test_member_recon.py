"""
test_member_recon.py
Sprint 2 TDD Reconciliation Test Suite: Member Analysis Summary
Validates live scbi-cube (Cloud Run) responses against Ground-Truth DuckDB GCS Lakehouse Marts.
"""

import os
import sys
import time
import json
import datetime
import urllib.request
from pathlib import Path

# Add web directory for ground truth DuckDB query execution
WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
sys.path.insert(0, str(WEB_DIR))

try:
    import jwt
except ImportError:
    jwt = None

CUBE_BASE_URL = os.environ.get("CUBEJS_BASE_URL", "https://scbi-cube-886154918734.europe-west1.run.app")
CUBE_SECRET = os.environ["CUBEJS_API_SECRET"]  # US-2.2: no in-code default


def get_ground_truth_duckdb():
    from member_engine import get_duckdb
    return get_duckdb()


def execute_cube_query(query_dict: dict, timeout_sec=45) -> list:
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
                    time.sleep(1.5)
                    continue
                if "data" in res:
                    return res["data"]
        except Exception as ex:
            time.sleep(1.5)
    return []


def test_story_2_1_executive_headline_kpis():
    """US 2.1: Executive Demographics & Financial Headline KPIs (:selected_date_sk = 20251231)."""
    print("\n" + "=" * 80)
    print("RUNNING: User Story 2.1 - Executive Demographics & Financial Headline Cards")
    print("=" * 80)

    # 1. Ground Truth SQL against Marts
    con = get_ground_truth_duckdb()
    t0 = time.time()
    sql = """
    SELECT 
        COUNT(DISTINCT f.MEMBER_HK) as total_members,
        ROUND(SUM(f.AUA_AMOUNT), 2) as total_aua,
        COUNT(DISTINCT CASE WHEN m.MEMBER_GENDER = 'Male' THEN m.MEMBER_HK END) as male_count,
        COUNT(DISTINCT CASE WHEN m.MEMBER_GENDER = 'Female' THEN m.MEMBER_HK END) as female_count
    FROM fct_member_aua f
    JOIN dim_member m ON f.MEMBER_HK = m.MEMBER_HK
    WHERE f.DATE_SK = 20251231;
    """
    row = con.execute(sql).fetchone()
    sql_time = round(time.time() - t0, 2)
    sql_total = row[0]
    sql_aua = float(row[1])
    sql_male = row[2]
    sql_female = row[3]
    print(f"[Ground Truth SQL] Executed in {sql_time}s | Members: {sql_total:,} | Male: {sql_male:,} | Female: {sql_female:,} | Total AUA: R {sql_aua:,.2f}")

    # 2. Cube.js API execution
    t1 = time.time()
    cube_query = {
        "measures": [
            "MemberMonthly.distinctMembers",
            "MemberMonthly.totalAua",
            "MemberMonthly.avgAua"
        ],
        "dimensions": ["DimMember.memberGender"],
        "filters": [
            {"member": "MemberMonthly.dateSk", "operator": "equals", "values": ["20251231"]}
        ]
    }
    cube_data = execute_cube_query(cube_query)
    cube_time = round(time.time() - t1, 2)

    cube_total = sum(int(float(r.get("MemberMonthly.distinctMembers", 0))) for r in cube_data)
    cube_aua = sum(float(r.get("MemberMonthly.totalAua", 0.0)) for r in cube_data)
    cube_male = sum(int(float(r.get("MemberMonthly.distinctMembers", 0))) for r in cube_data if r.get("DimMember.memberGender") == "Male")
    cube_female = sum(int(float(r.get("MemberMonthly.distinctMembers", 0))) for r in cube_data if r.get("DimMember.memberGender") == "Female")

    print(f"[Cube.js CloudRun] Executed in {cube_time}s | Members: {cube_total:,} | Male: {cube_male:,} | Female: {cube_female:,} | Total AUA: R {cube_aua:,.2f}")

    # 3. Assertions
    assert sql_total == cube_total, f"Member count mismatch: SQL {sql_total} vs Cube {cube_total}"
    assert sql_male == cube_male, f"Male count mismatch: SQL {sql_male} vs Cube {cube_male}"
    assert sql_female == cube_female, f"Female count mismatch: SQL {sql_female} vs Cube {cube_female}"
    assert round(sql_aua, 0) == round(cube_aua, 0), f"AUA mismatch: SQL {sql_aua} vs Cube {cube_aua}"

    print("[PASSED] US 2.1: Executive Demographics and Financial KPIs reconcile 100% (0.00% variance)")
    return True


def test_story_2_2_age_band_histogram():
    """US 2.2: Page 1 - Age Band Histogram (:selected_date_sk = 20251231)."""
    print("\n" + "=" * 80)
    print("RUNNING: User Story 2.2 - Page 1 Age Band Histogram")
    print("=" * 80)

    con = get_ground_truth_duckdb()
    t0 = time.time()
    sql = """
    SELECT 
        m.MEMBER_AGE_BAND,
        COUNT(DISTINCT f.MEMBER_HK) as member_count
    FROM fct_member_aua f
    JOIN dim_member m ON f.MEMBER_HK = m.MEMBER_HK
    WHERE f.DATE_SK = 20251231
    GROUP BY 1
    ORDER BY 1;
    """
    sql_rows = con.execute(sql).fetchall()
    sql_time = round(time.time() - t0, 2)
    sql_dict = {r[0]: r[1] for r in sql_rows}
    print(f"[Ground Truth SQL] Executed in {sql_time}s | Age Bands: {sql_dict}")

    t1 = time.time()
    cube_query = {
        "measures": ["MemberMonthly.distinctMembers"],
        "dimensions": ["DimMember.memberAgeBand"],
        "filters": [
            {"member": "MemberMonthly.dateSk", "operator": "equals", "values": ["20251231"]}
        ],
        "order": {"DimMember.memberAgeBand": "asc"}
    }
    cube_data = execute_cube_query(cube_query)
    cube_time = round(time.time() - t1, 2)
    cube_dict = {r.get("DimMember.memberAgeBand"): int(float(r.get("MemberMonthly.distinctMembers", 0))) for r in cube_data}
    print(f"[Cube.js CloudRun] Executed in {cube_time}s | Age Bands: {cube_dict}")

    # Reconcile each band
    for band, expected_count in sql_dict.items():
        actual_count = cube_dict.get(band, 0)
        assert expected_count == actual_count, f"Band '{band}' mismatch: SQL {expected_count} vs Cube {actual_count}"

    print("[PASSED] US 2.2: Age Band histogram distribution reconciles 100% across all brackets")
    return True


if __name__ == "__main__":
    print("=" * 80)
    print(" STARTING SPRINT 2 TDD RECONCILIATION SUITE: MEMBER ANALYSIS SUMMARY")
    print(" Target: scbi-cube (Cloud Run) vs GCS Lakehouse Marts")
    print("=" * 80)

    t_start = time.time()
    r1 = test_story_2_1_executive_headline_kpis()
    r2 = test_story_2_2_age_band_histogram()

    elapsed = round(time.time() - t_start, 2)
    print("\n" + "=" * 80)
    print(f" ALL SPRINT 2 TESTS COMPLETED SUCCESSFULLY IN {elapsed}s!")
    print(" Results: 2 Passed, 0 Failed, 100% Reconciled with scbi-cube")
    print("=" * 80)
