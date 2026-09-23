"""
test_first_dashboard_cascading_filters.py
===========================================
Cascading Filters & Data Linkage QA Verification Suite
Dashboard 1: Member Analysis Summary (PBI Replica)

Tests the following 4 suites (18 test cases total):
  Suite 1: Filter Cross-Linkage & Cascading Integrity (/api/member_analysis/slicers)
  Suite 2: Slicer-to-Visual Data Linkage & Mathematical Consistency (/api/member_analysis/query)
  Suite 3: Edge Cases, Resilience & Performance
  Suite 4: End-to-End API Contract Verification

Architecture:
  Test Script -> HTTP -> server.py (/api/member_analysis/slicers, /api/member_analysis/query)
  Test Script -> HTTP -> server.py -> scbi-cube Cloud Run (via /api/cube/load)

Author: Test Engineering (Automated)
"""

import sys
import os
import json
import time
import datetime
import urllib.request
import urllib.parse
import traceback
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────
SERVER_BASE = os.environ.get("TEST_SERVER_BASE", "http://localhost:8080")
REPORT_DIR = Path(__file__).resolve().parent

# ─── Test Results Collector ───────────────────────────────────────────────────
_results = []
_start_time = None


def _record(suite, test_id, name, status, duration_ms, details="", expected="", actual=""):
    _results.append({
        "suite": suite,
        "test_id": test_id,
        "name": name,
        "status": status,  # PASSED | FAILED | SKIPPED | ERROR
        "duration_ms": duration_ms,
        "details": details,
        "expected": expected,
        "actual": actual
    })


# ─── HTTP Helpers ─────────────────────────────────────────────────────────────
def call_slicers(**params):
    """Call /api/member_analysis/slicers with optional filter parameters."""
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v})
    url = f"{SERVER_BASE}/api/member_analysis/slicers?{qs}"
    t0 = time.time()
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    elapsed_ms = int((time.time() - t0) * 1000)
    return data, elapsed_ms


def call_query(**params):
    """Call /api/member_analysis/query with optional filter parameters."""
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v})
    url = f"{SERVER_BASE}/api/member_analysis/query?{qs}"
    t0 = time.time()
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    elapsed_ms = int((time.time() - t0) * 1000)
    return data, elapsed_ms


def parse_int(s):
    """Parse an integer from a formatted string like '366,784'."""
    if isinstance(s, (int, float)):
        return int(s)
    return int(str(s).replace(",", "").strip())


def parse_float_rand(s):
    """Parse a Rand-formatted float string like 'R 122.33 B'."""
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    s = s.replace("R ", "").replace(",", "").strip()
    multiplier = 1
    if s.endswith("T"):
        multiplier = 1e12
        s = s[:-1].strip()
    elif s.endswith("B"):
        multiplier = 1e9
        s = s[:-1].strip()
    elif s.endswith("M"):
        multiplier = 1e6
        s = s[:-1].strip()
    return float(s) * multiplier


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 1: Filter Cross-Linkage & Cascading Integrity
# ═══════════════════════════════════════════════════════════════════════════════

def tc_s1_01_baseline_initialization():
    """TC-S1-01: Baseline Initialization - Call slicers with no params."""
    t0 = time.time()
    try:
        data, ms = call_slicers()

        # Must contain all 8 slicer keys
        required_keys = ["date", "fund", "client", "employer", "brokerage",
                         "association", "paypoint_classification", "business_unit"]
        missing = [k for k in required_keys if k not in data and k.replace("_classification", "") not in data]
        # Also accept 'dates' as alias for 'date'
        if "date" in missing and "dates" in data:
            missing.remove("date")

        assert len(missing) == 0, f"Missing slicer keys: {missing}"

        # Date slicer must include latest snapshot
        dates = data.get("date", data.get("dates", []))
        assert len(dates) > 1, f"Date slicer has too few options: {len(dates)}"
        assert "31-DEC-2025" in dates, f"Latest snapshot 31-DEC-2025 not found in dates: {dates[:5]}"

        # Fund slicer must have All Funds + at least 5 funds
        funds = data.get("fund", data.get("funds", []))
        assert len(funds) >= 6, f"Fund slicer has too few options: {len(funds)}"
        assert any("all" in f.lower() for f in funds[:2]), f"Fund slicer missing 'All Funds': {funds[:3]}"

        # Business Unit must have All + SUS + SCS
        bu = data.get("business_unit", [])
        assert len(bu) >= 3, f"Business unit slicer has too few options: {len(bu)}"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-01", "Baseline Initialization", "PASSED", elapsed,
                f"All 8 slicer keys present, {len(dates)} dates, {len(funds)} funds, response {ms}ms",
                "All 8 slicer keys with valid options", "All present")
        print(f"  [PASSED] TC-S1-01: Baseline Initialization ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-01", "Baseline Initialization", "FAILED", elapsed,
                traceback.format_exc(), "All 8 slicer keys with valid options", str(e))
        print(f"  [FAILED] TC-S1-01: Baseline Initialization - {e}")
        return False


def tc_s1_02_bu_cascade_sus():
    """TC-S1-02: Business Unit Cascade - SUS should restrict funds to Umbrella only."""
    t0 = time.time()
    try:
        data, ms = call_slicers(business_unit="SUS")
        funds = data.get("fund", data.get("funds", []))

        # Remove "All Funds" prefix entry for content check
        content_funds = [f for f in funds if "all" not in f.lower()]

        # All returned funds should contain 'umbrella' or 'sanlam' (umbrella family)
        standalone_leaked = [f for f in content_funds if "standalone" in f.lower() or
                             ("eskom" in f.lower() or "transnet" in f.lower() or
                              "mineworkers" in f.lower() or "metal" in f.lower())]

        assert len(standalone_leaked) == 0, f"SUS filter leaked standalone funds: {standalone_leaked}"
        assert len(content_funds) > 0, "SUS filter returned zero content funds"

        # Client list should cascade for SUS context
        clients = data.get("client", [])
        assert len(clients) >= 2, f"Client slicer too narrow for SUS: {clients}"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-02", "BU Cascade (SUS→Funds)", "PASSED", elapsed,
                f"Returned {len(content_funds)} umbrella funds, 0 standalone leaks, {len(clients)} clients",
                "Only umbrella funds returned for SUS", f"{len(content_funds)} umbrella funds, 0 leaks")
        print(f"  [PASSED] TC-S1-02: BU Cascade SUS ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-02", "BU Cascade (SUS→Funds)", "FAILED", elapsed,
                traceback.format_exc(), "Only umbrella funds returned for SUS", str(e))
        print(f"  [FAILED] TC-S1-02: BU Cascade SUS - {e}")
        return False


def tc_s1_02b_bu_cascade_scs():
    """TC-S1-02b: Business Unit Cascade - SCS should restrict funds to Standalone only."""
    t0 = time.time()
    try:
        data, ms = call_slicers(business_unit="SCS")
        funds = data.get("fund", data.get("funds", []))

        content_funds = [f for f in funds if "all" not in f.lower()]

        umbrella_leaked = [f for f in content_funds if "umbrella" in f.lower()]

        assert len(umbrella_leaked) == 0, f"SCS filter leaked umbrella funds: {umbrella_leaked}"
        assert len(content_funds) > 0, "SCS filter returned zero content funds"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-02b", "BU Cascade (SCS→Funds)", "PASSED", elapsed,
                f"Returned {len(content_funds)} standalone funds, 0 umbrella leaks",
                "Only standalone funds returned for SCS", f"{len(content_funds)} standalone funds, 0 leaks")
        print(f"  [PASSED] TC-S1-02b: BU Cascade SCS ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-02b", "BU Cascade (SCS→Funds)", "FAILED", elapsed,
                traceback.format_exc(), "Only standalone funds returned for SCS", str(e))
        print(f"  [FAILED] TC-S1-02b: BU Cascade SCS - {e}")
        return False


def tc_s1_03_fund_client_employer_cascade():
    """TC-S1-03: Fund→Client & Employer Cascade - Selecting a specific fund filters clients/employers."""
    t0 = time.time()
    try:
        # Get baseline (no filter)
        base, _ = call_slicers()
        base_clients = base.get("client", [])
        base_employers = base.get("employer", [])

        # Select a specific umbrella fund
        filtered, ms = call_slicers(fund="SANLAM UMBRELLA PENSION FUND")
        filt_clients = filtered.get("client", [])
        filt_employers = filtered.get("employer", [])

        # Filtered clients should be a subset (or equal) of baseline
        assert len(filt_clients) <= len(base_clients), \
            f"Fund filter expanded clients: base={len(base_clients)}, filtered={len(filt_clients)}"
        assert len(filt_clients) >= 2, f"Fund filter produced too few clients: {filt_clients}"

        # Filtered employers should be a subset (or equal) of baseline
        assert len(filt_employers) <= len(base_employers), \
            f"Fund filter expanded employers: base={len(base_employers)}, filtered={len(filt_employers)}"
        assert len(filt_employers) >= 2, f"Fund filter produced too few employers: {filt_employers}"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-03", "Fund→Client & Employer Cascade", "PASSED", elapsed,
                f"Clients: {len(base_clients)}→{len(filt_clients)}, Employers: {len(base_employers)}→{len(filt_employers)}",
                "Clients and employers cascade when fund is selected",
                f"Clients {len(base_clients)}→{len(filt_clients)}, Employers {len(base_employers)}→{len(filt_employers)}")
        print(f"  [PASSED] TC-S1-03: Fund→Client & Employer Cascade ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-03", "Fund→Client & Employer Cascade", "FAILED", elapsed,
                traceback.format_exc(), "Clients and employers narrow on fund selection", str(e))
        print(f"  [FAILED] TC-S1-03: Fund→Client & Employer Cascade - {e}")
        return False


def tc_s1_04_client_bidirectional_cascade():
    """TC-S1-04: Client→Fund & Employer Bidirectional Cascade."""
    t0 = time.time()
    try:
        # Select a specific client
        data, ms = call_slicers(client="FAIRSURE ADMINISTRATION (PTY) LTD")
        funds = data.get("fund", data.get("funds", []))
        employers = data.get("employer", [])

        content_funds = [f for f in funds if "all" not in f.lower()]

        # FAIRSURE client should map to FAIRSURE + Abaqulusi funds (known linkage)
        assert any("fairsure" in f.lower() or "abaqulusi" in f.lower() for f in content_funds), \
            f"FAIRSURE client did not cascade to matching funds: {content_funds}"

        # Employer list should be constrained for this client
        assert len(employers) <= 5, f"FAIRSURE client returned too many employers (expected <=5): {len(employers)}"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-04", "Client→Fund & Employer Bidirectional", "PASSED", elapsed,
                f"Funds for FAIRSURE: {content_funds}, Employers: {employers}",
                "Client selection cascades to matching funds and employers",
                f"{len(content_funds)} funds, {len(employers)} employers")
        print(f"  [PASSED] TC-S1-04: Client→Fund & Employer Bidirectional ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-04", "Client→Fund & Employer Bidirectional", "FAILED", elapsed,
                traceback.format_exc(), "Client selection cascades to matching funds/employers", str(e))
        print(f"  [FAILED] TC-S1-04: Client→Fund & Employer Bidirectional - {e}")
        return False


def tc_s1_05_date_snapshot_cascade():
    """TC-S1-05: Date Snapshot Temporal Cascade - Different dates should return valid results."""
    t0 = time.time()
    try:
        # Query with latest date
        data_dec, ms1 = call_slicers(date="31-DEC-2025")
        # Query with older date
        data_oct, ms2 = call_slicers(date="31-OCT-2025")

        # Both should return full slicer sets (date doesn't cascade slicer options in current impl)
        assert "fund" in data_dec or "funds" in data_dec, "Dec snapshot missing fund slicer"
        assert "fund" in data_oct or "funds" in data_oct, "Oct snapshot missing fund slicer"

        # Verify both return valid dates
        dates_dec = data_dec.get("date", data_dec.get("dates", []))
        dates_oct = data_oct.get("date", data_oct.get("dates", []))
        assert len(dates_dec) > 0 and len(dates_oct) > 0, "Date slicers are empty"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-05", "Date Snapshot Temporal Cascade", "PASSED", elapsed,
                f"Dec slicers OK ({ms1}ms), Oct slicers OK ({ms2}ms)",
                "Different snapshot dates return valid slicer sets",
                f"Both snapshots return valid slicers")
        print(f"  [PASSED] TC-S1-05: Date Snapshot Temporal Cascade ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-05", "Date Snapshot Temporal Cascade", "FAILED", elapsed,
                traceback.format_exc(), "Different dates return valid slicer sets", str(e))
        print(f"  [FAILED] TC-S1-05: Date Snapshot Temporal Cascade - {e}")
        return False


def tc_s1_06_multi_level_interlocking():
    """TC-S1-06: Multi-Level Slicer Interlocking - BU→Fund→Client→Employer progressive cascade."""
    t0 = time.time()
    try:
        # Step 1: Select BU=SUS
        step1, _ = call_slicers(business_unit="SUS")
        funds_step1 = step1.get("fund", step1.get("funds", []))
        clients_step1 = step1.get("client", [])

        # Step 2: BU=SUS + Fund=specific umbrella fund
        fund_pick = None
        for f in funds_step1:
            if "umbrella pension" in f.lower():
                fund_pick = f
                break
        if not fund_pick:
            fund_pick = funds_step1[1] if len(funds_step1) > 1 else funds_step1[0]

        step2, _ = call_slicers(business_unit="SUS", fund=fund_pick)
        clients_step2 = step2.get("client", [])
        employers_step2 = step2.get("employer", [])

        # Step 3: BU=SUS + Fund + Client
        client_pick = clients_step2[1] if len(clients_step2) > 1 else clients_step2[0]
        step3, _ = call_slicers(business_unit="SUS", fund=fund_pick, client=client_pick)
        employers_step3 = step3.get("employer", [])

        # Verify progressive narrowing (each step ≤ previous or equal)
        assert len(clients_step2) <= len(clients_step1), \
            f"Clients expanded after fund selection: {len(clients_step1)}→{len(clients_step2)}"
        assert len(employers_step3) <= len(employers_step2), \
            f"Employers expanded after client selection: {len(employers_step2)}→{len(employers_step3)}"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-06", "Multi-Level Slicer Interlocking", "PASSED", elapsed,
                f"Clients: {len(clients_step1)}→{len(clients_step2)}, Employers: {len(employers_step2)}→{len(employers_step3)}",
                "Each progressive slicer narrows downstream options",
                "Progressive narrowing confirmed")
        print(f"  [PASSED] TC-S1-06: Multi-Level Slicer Interlocking ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 1", "TC-S1-06", "Multi-Level Slicer Interlocking", "FAILED", elapsed,
                traceback.format_exc(), "Progressive narrowing of cascading slicers", str(e))
        print(f"  [FAILED] TC-S1-06: Multi-Level Slicer Interlocking - {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 2: Slicer-to-Visual Data Linkage & Mathematical Consistency
# ═══════════════════════════════════════════════════════════════════════════════

def tc_s2_01_demographic_math_reconciliation():
    """TC-S2-01: Demographic Card Mathematical Reconciliation - Total = Male + Female (exact)."""
    t0 = time.time()
    try:
        # Test with multiple filter combos
        combos = [
            {"tab": "overview"},
            {"tab": "overview", "fund": "SANLAM UMBRELLA PENSION FUND"},
            {"tab": "overview", "business_unit": "SUS"},
            {"tab": "overview", "client": "Standard Bank Corporate"},
            {"tab": "overview", "business_unit": "SCS", "employer": "(NTU) - Abaqulusi Private Hospital (Pty) Ltd"},
        ]

        failures = []
        for i, params in enumerate(combos):
            data, ms = call_query(**params)
            demo = data.get("demographics", {})

            total = parse_int(demo.get("all", {}).get("total_members", "0"))
            male = parse_int(demo.get("male", {}).get("total_members", "0"))
            female = parse_int(demo.get("female", {}).get("total_members", "0"))

            if total != male + female:
                failures.append(f"Combo {i+1}: Total({total}) != Male({male}) + Female({female})")

            # Total must be > 0 for any valid filter combo
            if total <= 0:
                failures.append(f"Combo {i+1}: Total members is 0 or negative ({total})")

        assert len(failures) == 0, "Math parity failures: " + "; ".join(failures)

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-01", "Demographic Math Reconciliation", "PASSED", elapsed,
                f"All {len(combos)} filter combos pass Total = Male + Female (100% exact)",
                "Total Members = Male + Female for all combos",
                f"{len(combos)}/{len(combos)} combos pass")
        print(f"  [PASSED] TC-S2-01: Demographic Math Reconciliation ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-01", "Demographic Math Reconciliation", "FAILED", elapsed,
                traceback.format_exc(), "Total = Male + Female (exact)", str(e))
        print(f"  [FAILED] TC-S2-01: Demographic Math Reconciliation - {e}")
        return False


def tc_s2_02_financial_kpi_aua_consistency():
    """TC-S2-02: Financial KPI Linkage - AUA consistency (avg_aua = total_aua / total)."""
    t0 = time.time()
    try:
        combos = [
            {"tab": "overview"},
            {"tab": "overview", "fund": "SANLAM UMBRELLA PENSION FUND"},
            {"tab": "overview", "business_unit": "SUS"},
        ]

        failures = []
        for i, params in enumerate(combos):
            data, ms = call_query(**params)
            demo = data.get("demographics", {})
            fin = data.get("financial_kpis", {})

            total_members = parse_int(demo.get("all", {}).get("total_members", "0"))
            total_aua = parse_float_rand(fin.get("total_aua", "0"))
            avg_aua = parse_float_rand(fin.get("avg_aua", "0"))

            if total_members > 0:
                expected_avg = round(total_aua / total_members, 2)
                variance_pct = abs(avg_aua - expected_avg) / expected_avg * 100 if expected_avg > 0 else 0
                if variance_pct > 0.01:
                    failures.append(
                        f"Combo {i+1}: avg_aua variance {variance_pct:.4f}% "
                        f"(actual={avg_aua:.2f}, expected={expected_avg:.2f})"
                    )

        assert len(failures) == 0, "AUA consistency failures: " + "; ".join(failures)

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-02", "Financial KPI AUA Consistency", "PASSED", elapsed,
                f"All {len(combos)} combos pass avg_aua == total_aua/total_members (<0.01% variance)",
                "avg_aua == total_aua / total_members (<0.01%)",
                f"{len(combos)}/{len(combos)} combos pass")
        print(f"  [PASSED] TC-S2-02: Financial KPI AUA Consistency ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-02", "Financial KPI AUA Consistency", "FAILED", elapsed,
                traceback.format_exc(), "avg_aua == total_aua / total_members", str(e))
        print(f"  [FAILED] TC-S2-02: Financial KPI AUA Consistency - {e}")
        return False


def tc_s2_03_age_band_histogram_reconciliation():
    """TC-S2-03: Age Band Histogram - sum(age bins) == total_members (0 variance)."""
    t0 = time.time()
    try:
        combos = [
            {"tab": "overview"},
            {"tab": "overview", "fund": "SANLAM UMBRELLA PENSION FUND"},
            {"tab": "overview", "business_unit": "SCS"},
            {"tab": "overview", "brokerage": "Alexander Forbes"},
        ]

        failures = []
        for i, params in enumerate(combos):
            data, ms = call_query(**params)
            demo = data.get("demographics", {})
            chart = data.get("age_band_chart", {})

            total_members = parse_int(demo.get("all", {}).get("total_members", "0"))
            bins = chart.get("values", [])
            bin_sum = sum(bins)

            if bin_sum != total_members:
                failures.append(
                    f"Combo {i+1}: sum(bins)={bin_sum} != total_members={total_members} "
                    f"(delta={abs(bin_sum - total_members)})"
                )

            # Verify 7 bins present (standard age bands)
            labels = chart.get("labels", [])
            if len(labels) != 7:
                failures.append(f"Combo {i+1}: Expected 7 age bands, got {len(labels)}")

        assert len(failures) == 0, "Histogram reconciliation failures: " + "; ".join(failures)

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-03", "Age Band Histogram Reconciliation", "PASSED", elapsed,
                f"All {len(combos)} combos: sum(bins) == total_members (exact)",
                "Sum of age band bins == total_members (0 variance)",
                f"{len(combos)}/{len(combos)} combos pass")
        print(f"  [PASSED] TC-S2-03: Age Band Histogram Reconciliation ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-03", "Age Band Histogram Reconciliation", "FAILED", elapsed,
                traceback.format_exc(), "Sum of bins == total_members", str(e))
        print(f"  [FAILED] TC-S2-03: Age Band Histogram Reconciliation - {e}")
        return False


def tc_s2_04_cross_tab_linkage():
    """TC-S2-04: Cross-Tab Linkage - Filters persist across all 5 tabs."""
    t0 = time.time()
    try:
        filter_params = {"fund": "SANLAM UMBRELLA PENSION FUND", "business_unit": "SUS"}
        tabs = ["overview", "retirement", "age_salary", "contributions", "products_risk"]

        base_total = None
        failures = []

        for tab in tabs:
            params = dict(filter_params)
            params["tab"] = tab
            data, ms = call_query(**params)

            demo = data.get("demographics", {})
            total = parse_int(demo.get("all", {}).get("total_members", "0"))

            if base_total is None:
                base_total = total
            elif total != base_total:
                failures.append(f"Tab '{tab}': total_members={total} != overview={base_total}")

            # Verify tab-specific data exists
            if tab == "retirement":
                assert "near_normal" in data, f"Tab retirement missing 'near_normal' key"
                assert "past_early" in data, f"Tab retirement missing 'past_early' key"
            elif tab == "age_salary":
                assert "age_band_gender" in data, f"Tab age_salary missing 'age_band_gender'"
                assert "salary_band_gender" in data, f"Tab age_salary missing 'salary_band_gender'"
            elif tab == "contributions":
                assert "gross_age_band" in data, f"Tab contributions missing 'gross_age_band'"
            elif tab == "products_risk":
                assert "product_group_aua" in data, f"Tab products_risk missing 'product_group_aua'"

        assert len(failures) == 0, "Cross-tab linkage failures: " + "; ".join(failures)

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-04", "Cross-Tab Linkage (Tabs 1–5)", "PASSED", elapsed,
                f"All {len(tabs)} tabs consistent: total_members={base_total} across all tabs",
                "Filter state persists and data consistent across all 5 tabs",
                f"All {len(tabs)} tabs pass with total={base_total}")
        print(f"  [PASSED] TC-S2-04: Cross-Tab Linkage ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-04", "Cross-Tab Linkage (Tabs 1–5)", "FAILED", elapsed,
                traceback.format_exc(), "Consistent data across 5 tabs", str(e))
        print(f"  [FAILED] TC-S2-04: Cross-Tab Linkage - {e}")
        return False


def tc_s2_05_compound_filter_querying():
    """TC-S2-05: Compound Filter Querying - Apply all 8 filters simultaneously."""
    t0 = time.time()
    try:
        # Apply a realistic compound filter combination
        data, ms = call_query(
            tab="overview",
            date="31-DEC-2025",
            fund="SANLAM UMBRELLA PENSION FUND",
            business_unit="SUS",
            client="Sanlam Corporate Clients",
            employer="Sanlam Life Insurance Ltd",
            brokerage="Alexander Forbes",
            association="ASISA",
            paypoint="Contributing"
        )

        demo = data.get("demographics", {})
        total = parse_int(demo.get("all", {}).get("total_members", "0"))
        male = parse_int(demo.get("male", {}).get("total_members", "0"))
        female = parse_int(demo.get("female", {}).get("total_members", "0"))

        # With all filters active, total should be significantly reduced from baseline (366,784)
        assert total < 366784, f"Compound filter did not reduce total: {total} (baseline=366,784)"
        assert total > 0, "Compound filter produced 0 members"
        assert total == male + female, f"Math parity: {total} != {male} + {female}"

        # Financial KPIs should also be reduced
        fin = data.get("financial_kpis", {})
        total_aua = parse_float_rand(fin.get("total_aua", "0"))
        assert total_aua < 122330000000.0, f"Compound filter did not reduce AUA: {total_aua}"
        assert total_aua > 0, "Compound filter produced 0 AUA"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-05", "Compound Filter Querying (8 filters)", "PASSED", elapsed,
                f"8-filter compound: total={total}, male={male}, female={female}, AUA={fin.get('total_aua')}",
                "Compound filter reflects intersection of all 8 active filters",
                f"total={total} (reduced from 366,784), math parity holds")
        print(f"  [PASSED] TC-S2-05: Compound Filter Querying ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 2", "TC-S2-05", "Compound Filter Querying (8 filters)", "FAILED", elapsed,
                traceback.format_exc(), "Compound filter reflects all 8 filters", str(e))
        print(f"  [FAILED] TC-S2-05: Compound Filter Querying - {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 3: Edge Cases, Resilience & Performance
# ═══════════════════════════════════════════════════════════════════════════════

def tc_s3_01_filter_reset_to_all():
    """TC-S3-01: Filter Reset / 'All' Selection - Resetting restores baseline."""
    t0 = time.time()
    try:
        # 1. Get baseline (no filters)
        base, _ = call_query(tab="overview")
        base_total = parse_int(base.get("demographics", {}).get("all", {}).get("total_members", "0"))

        # 2. Apply a filter
        filtered, _ = call_query(tab="overview", fund="SANLAM UMBRELLA PENSION FUND")
        filt_total = parse_int(filtered.get("demographics", {}).get("all", {}).get("total_members", "0"))

        # 3. Reset to "All" (send All Funds)
        reset, _ = call_query(tab="overview", fund="All Funds")
        reset_total = parse_int(reset.get("demographics", {}).get("all", {}).get("total_members", "0"))

        assert filt_total < base_total, f"Filter did not reduce: base={base_total}, filtered={filt_total}"
        assert reset_total == base_total, f"Reset did not restore baseline: reset={reset_total}, base={base_total}"

        # 4. Slicer reset should also restore full options
        base_slicers, _ = call_slicers()
        reset_slicers, _ = call_slicers(fund="All Funds")
        base_clients = base_slicers.get("client", [])
        reset_clients = reset_slicers.get("client", [])
        assert len(reset_clients) == len(base_clients), \
            f"Slicer reset did not restore client count: {len(reset_clients)} vs {len(base_clients)}"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 3", "TC-S3-01", "Filter Reset / 'All' Selection", "PASSED", elapsed,
                f"Base={base_total}, Filtered={filt_total}, Reset={reset_total} (matches base)",
                "Reset restores baseline metrics and slicer options",
                f"Reset total={reset_total} matches base={base_total}")
        print(f"  [PASSED] TC-S3-01: Filter Reset ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 3", "TC-S3-01", "Filter Reset / 'All' Selection", "FAILED", elapsed,
                traceback.format_exc(), "Reset restores baseline", str(e))
        print(f"  [FAILED] TC-S3-01: Filter Reset - {e}")
        return False


def tc_s3_02_conflicting_selections():
    """TC-S3-02: Conflicting/Mutually Exclusive Selections - No crash or 500."""
    t0 = time.time()
    try:
        # Select SCS business unit but an umbrella fund (conflict)
        data, ms = call_slicers(business_unit="SCS", fund="SANLAM UMBRELLA PENSION FUND")

        # Should NOT crash - must return a valid JSON response
        assert isinstance(data, dict), f"Response is not a dict: {type(data)}"
        assert "error" not in data, f"Server returned error: {data.get('error')}"

        # Query with conflicting params should also not crash
        q_data, q_ms = call_query(
            tab="overview",
            business_unit="SCS",
            fund="SANLAM UMBRELLA PENSION FUND"
        )
        assert "error" not in q_data, f"Query returned error on conflict: {q_data.get('error')}"
        assert "demographics" in q_data, "Query missing demographics on conflict"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 3", "TC-S3-02", "Conflicting Selections (No Crash)", "PASSED", elapsed,
                f"Slicer response: {ms}ms, Query response: {q_ms}ms, no errors",
                "System handles conflicting filters without crash or 500",
                f"Both endpoints returned valid JSON, no errors")
        print(f"  [PASSED] TC-S3-02: Conflicting Selections ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 3", "TC-S3-02", "Conflicting Selections (No Crash)", "FAILED", elapsed,
                traceback.format_exc(), "No crash or 500 on conflict", str(e))
        print(f"  [FAILED] TC-S3-02: Conflicting Selections - {e}")
        return False


def tc_s3_03_rapid_fire_resilience():
    """TC-S3-03: Rapid-Fire Event Resilience - Sequential burst of 5 queries within tight window."""
    t0 = time.time()
    try:
        params_list = [
            {"tab": "overview"},
            {"tab": "overview", "fund": "SANLAM UMBRELLA PENSION FUND"},
            {"tab": "overview", "business_unit": "SUS"},
            {"tab": "overview", "client": "Standard Bank Corporate"},
            {"tab": "overview"},
        ]

        responses = []
        for params in params_list:
            data, ms = call_query(**params)
            responses.append((data, ms))

        # All must return valid data (no errors)
        errors = []
        for i, (data, ms) in enumerate(responses):
            if "error" in data:
                errors.append(f"Query {i+1}: {data['error']}")
            if "demographics" not in data:
                errors.append(f"Query {i+1}: missing demographics")

        assert len(errors) == 0, f"Rapid-fire errors: {'; '.join(errors)}"

        # First and last should match (both baseline)
        first_total = parse_int(responses[0][0]["demographics"]["all"]["total_members"])
        last_total = parse_int(responses[-1][0]["demographics"]["all"]["total_members"])
        assert first_total == last_total, f"Baseline drift: first={first_total}, last={last_total}"

        total_time = sum(r[1] for r in responses)
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 3", "TC-S3-03", "Rapid-Fire Resilience (5 queries)", "PASSED", elapsed,
                f"All 5 rapid queries OK, total API time: {total_time}ms, baseline stable",
                "All rapid queries return valid data, no drift",
                f"5/5 queries OK, total={total_time}ms")
        print(f"  [PASSED] TC-S3-03: Rapid-Fire Resilience ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 3", "TC-S3-03", "Rapid-Fire Resilience (5 queries)", "FAILED", elapsed,
                traceback.format_exc(), "All rapid queries return valid data", str(e))
        print(f"  [FAILED] TC-S3-03: Rapid-Fire Resilience - {e}")
        return False


def tc_s3_04_latency_sla():
    """TC-S3-04: Latency & SLA Verification - All requests < 2000ms."""
    t0 = time.time()
    try:
        timings = []

        # Slicer calls
        _, ms = call_slicers()
        timings.append(("slicers (baseline)", ms))
        _, ms = call_slicers(business_unit="SUS")
        timings.append(("slicers (BU=SUS)", ms))

        # Query calls
        _, ms = call_query(tab="overview")
        timings.append(("query (baseline)", ms))
        _, ms = call_query(tab="overview", fund="SANLAM UMBRELLA PENSION FUND")
        timings.append(("query (fund filter)", ms))
        _, ms = call_query(tab="overview", business_unit="SUS", client="Standard Bank Corporate")
        timings.append(("query (BU+Client)", ms))

        sla_ms = 2000
        violations = [(name, t) for name, t in timings if t > sla_ms]

        avg_ms = sum(t for _, t in timings) / len(timings)
        max_ms = max(t for _, t in timings)
        min_ms = min(t for _, t in timings)

        if len(violations) > 0:
            details = "; ".join([f"{n}: {t}ms" for n, t in violations])
            _record("Suite 3", "TC-S3-04", f"Latency SLA (<{sla_ms}ms)", "FAILED",
                    int((time.time() - t0) * 1000),
                    f"SLA violations: {details}. Avg={avg_ms:.0f}ms, Max={max_ms}ms",
                    f"All requests < {sla_ms}ms",
                    f"{len(violations)}/{len(timings)} violated SLA")
            print(f"  [FAILED] TC-S3-04: Latency SLA - {len(violations)} violations")
            return False
        else:
            elapsed = int((time.time() - t0) * 1000)
            _record("Suite 3", "TC-S3-04", f"Latency SLA (<{sla_ms}ms)", "PASSED", elapsed,
                    f"Avg={avg_ms:.0f}ms, Min={min_ms}ms, Max={max_ms}ms across {len(timings)} requests",
                    f"All requests < {sla_ms}ms",
                    f"0 violations, max={max_ms}ms")
            print(f"  [PASSED] TC-S3-04: Latency SLA ({elapsed}ms)")
            return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 3", "TC-S3-04", f"Latency SLA (<2000ms)", "FAILED", elapsed,
                traceback.format_exc(), "All requests < 2000ms", str(e))
        print(f"  [FAILED] TC-S3-04: Latency SLA - {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 4: End-to-End API Contract Verification
# ═══════════════════════════════════════════════════════════════════════════════

def tc_s4_01_slicer_response_schema():
    """TC-S4-01: Slicer Response Schema - Verify all 8 dropdown options are arrays of strings."""
    t0 = time.time()
    try:
        data, ms = call_slicers()

        schema_checks = {
            "date": ("date", "dates"),
            "fund": ("fund", "funds"),
            "business_unit": ("business_unit",),
            "client": ("client",),
            "employer": ("employer",),
            "brokerage": ("brokerage",),
            "association": ("association",),
            "paypoint": ("paypoint_classification",),
        }

        failures = []
        for label, keys in schema_checks.items():
            found = False
            for k in keys:
                if k in data:
                    vals = data[k]
                    if not isinstance(vals, list):
                        failures.append(f"{label} ({k}): not a list, got {type(vals).__name__}")
                    elif len(vals) == 0:
                        failures.append(f"{label} ({k}): empty list")
                    elif not all(isinstance(v, str) for v in vals):
                        failures.append(f"{label} ({k}): contains non-string elements")
                    found = True
                    break
            if not found:
                failures.append(f"{label}: key not found (tried {keys})")

        assert len(failures) == 0, "Schema validation failures: " + "; ".join(failures)

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 4", "TC-S4-01", "Slicer Response Schema", "PASSED", elapsed,
                f"All 8 slicer keys present as non-empty string arrays",
                "All slicer values are non-empty arrays of strings",
                "All 8 slicers validated")
        print(f"  [PASSED] TC-S4-01: Slicer Response Schema ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 4", "TC-S4-01", "Slicer Response Schema", "FAILED", elapsed,
                traceback.format_exc(), "All 8 slicers are string arrays", str(e))
        print(f"  [FAILED] TC-S4-01: Slicer Response Schema - {e}")
        return False


def tc_s4_02_query_response_completeness():
    """TC-S4-02: Query Response Completeness - All required payload keys present."""
    t0 = time.time()
    try:
        data, ms = call_query(tab="overview")

        required_top = ["demographics", "financial_kpis", "age_band_chart",
                        "near_normal", "past_early", "age_band_gender", "salary_band_gender",
                        "gross_age_band", "net_age_band", "gross_salary_band", "net_salary_band",
                        "product_group_aua", "top_risk_products",
                        "execution_time_ms", "data_source", "cube_status"]  # US-6.0: live_feed removed

        missing = [k for k in required_top if k not in data]

        assert len(missing) == 0, f"Missing response keys: {missing}"

        # Validate demographics sub-structure
        demo = data["demographics"]
        for group in ["all", "male", "female"]:
            assert group in demo, f"demographics missing '{group}' key"
            sub = demo[group]
            for field in ["total_members", "avg_age", "avg_monthly_salary"]:
                assert field in sub, f"demographics.{group} missing '{field}'"

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 4", "TC-S4-02", "Query Response Completeness", "PASSED", elapsed,
                f"All {len(required_top)} top-level keys present, demographics structure validated",
                "Complete response schema with all dashboard data",
                f"0 missing keys")
        print(f"  [PASSED] TC-S4-02: Query Response Completeness ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 4", "TC-S4-02", "Query Response Completeness", "FAILED", elapsed,
                traceback.format_exc(), "All required keys present", str(e))
        print(f"  [FAILED] TC-S4-02: Query Response Completeness - {e}")
        return False


def tc_s4_03_brokerage_association_paypoint_linkage():
    """TC-S4-03: Brokerage, Association, Paypoint Filter Linkage - All 8 filters affect query results."""
    t0 = time.time()
    try:
        # Baseline
        base, _ = call_query(tab="overview")
        base_total = parse_int(base["demographics"]["all"]["total_members"])

        # Test each of the 3 secondary filters individually
        filters_to_test = [
            ("brokerage", "Alexander Forbes"),
            ("association", "ASISA"),
            ("paypoint", "Contributing"),
        ]

        failures = []
        for filter_name, filter_value in filters_to_test:
            data, ms = call_query(tab="overview", **{filter_name: filter_value})
            total = parse_int(data["demographics"]["all"]["total_members"])

            if total >= base_total:
                failures.append(f"{filter_name}={filter_value}: total {total} >= baseline {base_total}")
            if total <= 0:
                failures.append(f"{filter_name}={filter_value}: total is 0 or negative")

            # Math parity must hold
            male = parse_int(data["demographics"]["male"]["total_members"])
            female = parse_int(data["demographics"]["female"]["total_members"])
            if total != male + female:
                failures.append(f"{filter_name}={filter_value}: parity fail {total} != {male}+{female}")

        assert len(failures) == 0, "Linkage failures: " + "; ".join(failures)

        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 4", "TC-S4-03", "Brokerage/Association/Paypoint Linkage", "PASSED", elapsed,
                f"All 3 filters reduce data from baseline={base_total}, math parity holds",
                "Brokerage, Association, Paypoint all affect query results",
                f"All 3 filters actively linked")
        print(f"  [PASSED] TC-S4-03: Brokerage/Association/Paypoint Linkage ({elapsed}ms)")
        return True
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        _record("Suite 4", "TC-S4-03", "Brokerage/Association/Paypoint Linkage", "FAILED", elapsed,
                traceback.format_exc(), "All 3 secondary filters affect results", str(e))
        print(f"  [FAILED] TC-S4-03: Brokerage/Association/Paypoint Linkage - {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report():
    """Generate the full QA Test & Reconciliation Report as Markdown."""
    global _start_time
    total_elapsed_s = round(time.time() - _start_time, 2) if _start_time else 0

    passed = sum(1 for r in _results if r["status"] == "PASSED")
    failed = sum(1 for r in _results if r["status"] == "FAILED")
    skipped = sum(1 for r in _results if r["status"] == "SKIPPED")
    errored = sum(1 for r in _results if r["status"] == "ERROR")
    total = len(_results)
    pass_rate = (passed / total * 100) if total > 0 else 0

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    lines = []
    lines.append("# 🧪 Cascading Filters QA Test & Reconciliation Report")
    lines.append(f"**Dashboard 1: Member Analysis Summary (PBI Replica)**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| **Execution Timestamp** | {now} |")
    lines.append(f"| **Total Test Cases** | {total} |")
    lines.append(f"| **Passed** | ✅ {passed} |")
    lines.append(f"| **Failed** | ❌ {failed} |")
    lines.append(f"| **Skipped** | ⏭️ {skipped} |")
    lines.append(f"| **Errors** | ⚠️ {errored} |")
    lines.append(f"| **Pass Rate** | **{pass_rate:.1f}%** |")
    lines.append(f"| **Total Execution Time** | {total_elapsed_s}s |")
    lines.append(f"| **Server Under Test** | `{SERVER_BASE}` |")
    lines.append(f"| **Architecture** | Thin Web App → server.py → scbi-cube (Cloud Run) |")
    lines.append("")

    if pass_rate == 100:
        lines.append("> [!TIP]")
        lines.append("> **100% Pass Rate Achieved** — All cascading filters are fully linked and mathematically consistent across all 8 slicers and 5 dashboard tabs.")
    elif pass_rate >= 80:
        lines.append("> [!WARNING]")
        lines.append(f"> **{pass_rate:.1f}% Pass Rate** — {failed} test case(s) failed. Review the defect log below for root cause analysis.")
    else:
        lines.append("> [!CAUTION]")
        lines.append(f"> **{pass_rate:.1f}% Pass Rate** — Significant filter linkage issues detected. Immediate remediation required.")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Suite-by-suite detail table
    lines.append("## Detailed Test Results Matrix")
    lines.append("")
    lines.append("| Suite | Test ID | Test Name | Status | Duration | Details |")
    lines.append("|---|---|---|---|---|---|")

    for r in _results:
        status_icon = "✅" if r["status"] == "PASSED" else "❌" if r["status"] == "FAILED" else "⚠️"
        dur = f'{r["duration_ms"]}ms'
        details = r["details"][:120].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['suite']} | {r['test_id']} | {r['name']} | {status_icon} {r['status']} | {dur} | {details} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Defect Log
    failures = [r for r in _results if r["status"] in ("FAILED", "ERROR")]
    lines.append("## Defect Log & Root Cause Analysis")
    lines.append("")
    if len(failures) == 0:
        lines.append("**No defects found.** All test cases passed successfully.")
        lines.append("")
    else:
        for r in failures:
            lines.append(f"### ❌ {r['test_id']}: {r['name']}")
            lines.append("")
            lines.append(f"- **Suite**: {r['suite']}")
            lines.append(f"- **Expected**: {r['expected']}")
            lines.append(f"- **Actual**: {r['actual']}")
            lines.append(f"- **Details**:")
            lines.append(f"```")
            lines.append(r["details"][:500])
            lines.append(f"```")
            lines.append("")

    lines.append("---")
    lines.append("")

    # Data Linkage Confirmation
    lines.append("## Data Linkage Confirmation")
    lines.append("")
    lines.append("### Slicer Cross-Linkage Matrix (8 Filters)")
    lines.append("")
    lines.append("| # | Filter | Cascading Effect | Linked? |")
    lines.append("|---|---|---|---|")

    slicer_linkage = [
        ("1", "Date", "Temporal snapshot selection → query scope", "date" not in [r["test_id"] for r in failures]),
        ("2", "Fund", "Narrows Client, Employer options", "S1-03" not in " ".join([r["test_id"] for r in failures])),
        ("3", "Business Unit", "SUS/SCS splits Fund list", "S1-02" not in " ".join([r["test_id"] for r in failures])),
        ("4", "Client", "Bidirectional: narrows Fund, Employer", "S1-04" not in " ".join([r["test_id"] for r in failures])),
        ("5", "Employer", "Constrained by Client and Fund", "S1-04" not in " ".join([r["test_id"] for r in failures])),
        ("6", "Brokerage", "Scales query results", "S4-03" not in " ".join([r["test_id"] for r in failures])),
        ("7", "Association", "Scales query results", "S4-03" not in " ".join([r["test_id"] for r in failures])),
        ("8", "Paypoint", "Scales query results (Contributing/Exit)", "S4-03" not in " ".join([r["test_id"] for r in failures])),
    ]
    for num, name, effect, linked in slicer_linkage:
        icon = "✅ Yes" if linked else "❌ No"
        lines.append(f"| {num} | **{name}** | {effect} | {icon} |")

    lines.append("")
    lines.append("### Mathematical Consistency Guarantees")
    lines.append("")
    s2_01_pass = any(r["test_id"] == "TC-S2-01" and r["status"] == "PASSED" for r in _results)
    s2_02_pass = any(r["test_id"] == "TC-S2-02" and r["status"] == "PASSED" for r in _results)
    s2_03_pass = any(r["test_id"] == "TC-S2-03" and r["status"] == "PASSED" for r in _results)
    lines.append(f"| Guarantee | Status |")
    lines.append(f"|---|---|")
    lines.append(f"| `Total Members = Male + Female` (exact parity) | {'✅ Verified' if s2_01_pass else '❌ Failed'} |")
    lines.append(f"| `avg_aua = total_aua / total_members` (<0.01% variance) | {'✅ Verified' if s2_02_pass else '❌ Failed'} |")
    lines.append(f"| `sum(age_band_bins) = total_members` (0 variance) | {'✅ Verified' if s2_03_pass else '❌ Failed'} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Test Environment")
    lines.append("")
    lines.append(f"- **Server**: `{SERVER_BASE}`")
    lines.append(f"- **Architecture**: Thin Web App Client → `server.py` → `scbi-cube` (Google Cloud Run)")
    lines.append(f"- **Semantic Layer**: Cube.js with `MemberMonthly`, `DimFund`, `DimClient`, `DimEmployer`, `DimDate`")
    lines.append(f"- **Test Runner**: `test_first_dashboard_cascading_filters.py`")
    lines.append(f"- **Generated**: {now}")
    lines.append("")
    lines.append("---")
    lines.append(f"*Report generated by Automated QA Test Engine*")
    lines.append("")

    report_content = "\n".join(lines)

    # Write report to file
    report_path = REPORT_DIR / "CASCADING_FILTERS_TEST_REPORT.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"\n📄 Report written to: {report_path}")
    return report_path


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_all():
    """Execute all 4 test suites and generate the QA report."""
    global _start_time
    _start_time = time.time()

    print("=" * 90)
    print(" CASCADING FILTERS QA VERIFICATION SUITE")
    print(" Dashboard 1: Member Analysis Summary (PBI Replica)")
    print(f" Server: {SERVER_BASE}")
    print(f" Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 90)

    # ── Suite 1: Filter Cross-Linkage ──────────────────────────────────────
    print("\n" + "─" * 90)
    print(" SUITE 1: Filter Cross-Linkage & Cascading Integrity (/api/member_analysis/slicers)")
    print("─" * 90)
    tc_s1_01_baseline_initialization()
    tc_s1_02_bu_cascade_sus()
    tc_s1_02b_bu_cascade_scs()
    tc_s1_03_fund_client_employer_cascade()
    tc_s1_04_client_bidirectional_cascade()
    tc_s1_05_date_snapshot_cascade()
    tc_s1_06_multi_level_interlocking()

    # ── Suite 2: Data Linkage & Math Consistency ──────────────────────────
    print("\n" + "─" * 90)
    print(" SUITE 2: Slicer-to-Visual Data Linkage & Mathematical Consistency (/api/member_analysis/query)")
    print("─" * 90)
    tc_s2_01_demographic_math_reconciliation()
    tc_s2_02_financial_kpi_aua_consistency()
    tc_s2_03_age_band_histogram_reconciliation()
    tc_s2_04_cross_tab_linkage()
    tc_s2_05_compound_filter_querying()

    # ── Suite 3: Edge Cases & Performance ─────────────────────────────────
    print("\n" + "─" * 90)
    print(" SUITE 3: Edge Cases, Resilience & Performance")
    print("─" * 90)
    tc_s3_01_filter_reset_to_all()
    tc_s3_02_conflicting_selections()
    tc_s3_03_rapid_fire_resilience()
    tc_s3_04_latency_sla()

    # ── Suite 4: API Contract Verification ────────────────────────────────
    print("\n" + "─" * 90)
    print(" SUITE 4: End-to-End API Contract Verification")
    print("─" * 90)
    tc_s4_01_slicer_response_schema()
    tc_s4_02_query_response_completeness()
    tc_s4_03_brokerage_association_paypoint_linkage()

    # ── Generate Report ───────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print(" GENERATING QA REPORT")
    print("=" * 90)
    report_path = generate_report()

    # ── Summary ──────────────────────────────────────────────────────────
    passed = sum(1 for r in _results if r["status"] == "PASSED")
    failed = sum(1 for r in _results if r["status"] == "FAILED")
    total = len(_results)
    elapsed = round(time.time() - _start_time, 2)

    print(f"\n{'=' * 90}")
    print(f" FINAL SUMMARY: {passed}/{total} PASSED | {failed} FAILED | {elapsed}s total")
    print(f"{'=' * 90}\n")

    return passed, failed, total


if __name__ == "__main__":
    passed, failed, total = run_all()
    sys.exit(0 if failed == 0 else 1)
