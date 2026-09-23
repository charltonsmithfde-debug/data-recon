"""
test_all_dashboards_recon.py
Master End-to-End Enterprise Reconciliation Suite (Sprint 5)
Executes all reconciliation test suites across:
 - Sprint 1: Cascading Filters (8 Slicers)
 - Sprint 2: Member Analysis Summary (PBI Replica)
 - Sprint 3: Fund Analytics - Investment Analysis (PBI Replica)
 - Sprint 4: Life Annuity Reporting (Quotes & Acceptances)

Validates 100% numerical match (0.00% variance) between Ground Truth DuckDB Lakehouse Marts
and the centralized Google Cloud Run semantic layer (scbi-cube).
"""

import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

import test_filters_recon
import test_member_recon
import test_invest_recon
import test_annuity_recon


def run_master_suite():
    t_start = time.time()
    print("=" * 90)
    print(" SANLAM ONLINE ANALYTICS PORTAL - MASTER ENTERPRISE RECONCILIATION SUITE")
    print(" Architecture: Thin Web App Client <-> scbi-cube (Cloud Run) <-> GCS Lakehouse Marts")
    print(" Target: 0.00% Numerical Variance across all 14 Core User Stories")
    print("=" * 90)

    results = []

    # ── Sprint 1: Cascading Filters ──────────────────────────────────────────
    print("\n" + "#" * 90)
    print(" SPRINT 1: DYNAMIC CASCADING FILTERS RECONCILIATION")
    print("#" * 90)
    sprint1_tests = [
        ("US 1.1: Snapshot Date Filter", test_filters_recon.test_story_1_1_snapshot_date),
        ("US 1.2: Calendar Year Cascade", test_filters_recon.test_story_1_2_calendar_year),
        ("US 1.3: Business Unit Filter", test_filters_recon.test_story_1_3_business_unit),
        ("US 1.4: Fund Name Cross-Cascade", test_filters_recon.test_story_1_4_fund_name),
        ("US 1.5: Client Name Cascade", test_filters_recon.test_story_1_5_client_name),
        ("US 1.6: Employer Name Cascade", test_filters_recon.test_story_1_6_employer_name),
        ("US 1.7: Brokerage Filter", test_filters_recon.test_story_1_7_brokerage),
        ("US 1.8: Paypoint Filter", test_filters_recon.test_story_1_8_paypoint)
    ]
    for name, fn in sprint1_tests:
        t0 = time.time()
        try:
            fn()
            results.append({"sprint": "Sprint 1", "test": name, "status": "PASSED", "duration": round(time.time() - t0, 2)})
        except Exception as e:
            results.append({"sprint": "Sprint 1", "test": name, "status": f"FAILED: {e}", "duration": round(time.time() - t0, 2)})

    # ── Sprint 2: Member Analysis ────────────────────────────────────────────
    print("\n" + "#" * 90)
    print(" SPRINT 2: MEMBER ANALYSIS SUMMARY RECONCILIATION")
    print("#" * 90)
    sprint2_tests = [
        ("US 2.1: Member Headline Cards & Demographics", test_member_recon.test_story_2_1_member_headline_cards),
        ("US 2.2: Age Band Distribution Histogram", test_member_recon.test_story_2_2_age_band_histogram)
    ]
    for name, fn in sprint2_tests:
        t0 = time.time()
        try:
            fn()
            results.append({"sprint": "Sprint 2", "test": name, "status": "PASSED", "duration": round(time.time() - t0, 2)})
        except Exception as e:
            results.append({"sprint": "Sprint 2", "test": name, "status": f"FAILED: {e}", "duration": round(time.time() - t0, 2)})

    # ── Sprint 3: Investment Analysis ─────────────────────────────────────────
    print("\n" + "#" * 90)
    print(" SPRINT 3: INVESTMENT ANALYSIS RECONCILIATION")
    print("#" * 90)
    sprint3_tests = [
        ("US 3.1: Market Value & Transaction Units", test_invest_recon.test_story_3_1_market_value_kpis),
        ("US 3.2: Member Investment AUA Headline", test_invest_recon.test_story_3_2_member_aua_kpis)
    ]
    for name, fn in sprint3_tests:
        t0 = time.time()
        try:
            fn()
            results.append({"sprint": "Sprint 3", "test": name, "status": "PASSED", "duration": round(time.time() - t0, 2)})
        except Exception as e:
            results.append({"sprint": "Sprint 3", "test": name, "status": f"FAILED: {e}", "duration": round(time.time() - t0, 2)})

    # ── Sprint 4: Life Annuity Reporting ──────────────────────────────────────
    print("\n" + "#" * 90)
    print(" SPRINT 4: LIFE ANNUITY REPORTING (QUOTES & ACCEPTANCES)")
    print("#" * 90)
    sprint4_tests = [
        ("US 4.1: Timeline & Conversion Rates", test_annuity_recon.test_story_4_1_timeline_conversion_rates),
        ("US 4.2: Consultant Performance KPIs", test_annuity_recon.test_story_4_2_consultant_kpis)
    ]
    for name, fn in sprint4_tests:
        t0 = time.time()
        try:
            fn()
            results.append({"sprint": "Sprint 4", "test": name, "status": "PASSED", "duration": round(time.time() - t0, 2)})
        except Exception as e:
            results.append({"sprint": "Sprint 4", "test": name, "status": f"FAILED: {e}", "duration": round(time.time() - t0, 2)})

    # ── Master Summary Report ────────────────────────────────────────────────
    total_time = round(time.time() - t_start, 2)
    passed = sum(1 for r in results if r["status"] == "PASSED")
    failed = len(results) - passed

    print("\n" + "=" * 90)
    print(" MASTER ENTERPRISE RECONCILIATION SUMMARY REPORT")
    print("=" * 90)
    print(f"{'Sprint':<12} | {'User Story / Test Name':<48} | {'Status':<8} | {'Duration':<8}")
    print("-" * 90)
    for r in results:
        print(f"{r['sprint']:<12} | {r['test']:<48} | {r['status']:<8} | {r['duration']}s")
    print("-" * 90)
    print(f" TOTAL TESTS: {len(results)} | PASSED: {passed} | FAILED: {failed} | SUCCESS RATE: {(passed / len(results) * 100):.1f}%")
    print(f" TOTAL DURATION: {total_time}s")
    print(f" OVERALL VERDICT: {'100% RECONCILED (0.00% VARIANCE)' if failed == 0 else 'VERIFICATION FAILED'}")
    print("=" * 90 + "\n")

    assert failed == 0, f"{failed} test(s) failed during master reconciliation suite."


if __name__ == "__main__":
    run_master_suite()
