"""
server.py

Sanlam Online Analytics Portal Backend Server.
Powered by DuckDB and Google Cloud Storage Lakehouse.
Provides high-performance analytical endpoints, RBAC, POPIA PII Masking,
and Power BI Published Report Visual Replicas.
"""

import os
import sys
import json
import http.server
import socketserver
import urllib.parse
import urllib.request
import datetime
import re
from pathlib import Path


try:
    import jwt
except ImportError:
    jwt = None

WEB_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
CATALOG_PATH = WEB_DIR / "catalog.json"
STATE_PATH = SCRIPTS_DIR / "migration_state.json"

PORT = 8080
CUBE_BASE_URL = "https://scbi-cube-886154918734.europe-west1.run.app"
CUBE_SECRET = os.environ["CUBEJS_API_SECRET"]  # US-2.2: no in-code default


# Role permissions matching data-recon/cube/cube.js
ROLE_PERMISSIONS = {
    "ROLE_EXECUTIVE_ALL": {
        "title": "Executive (Full Access)",
        "allowedCubes": ["*"],
        "canViewPii": True,
        "description": "Executive & C-Suite Access with Full PII Visibility"
    },
    "ROLE_FINANCE_MEMBER": {
        "title": "Finance & Member Analytics",
        "allowedCubes": [
            "fund_analytics_monthly_metrics",
            "member_monthly",
            "member_transactions",
            "assetflows_member_monthly",
            "member_monthly_investment"
        ],
        "canViewPii": False,
        "description": "Financial & Member Measures (PII Masked)"
    },
    "ROLE_DIGITAL_OPERATIONS": {
        "title": "Digital Operations",
        "allowedCubes": [
            "digital_portal",
            "digital_portal_events",
            "digital_portal_registrations",
            "aggregated_digital_portal_registrations"
        ],
        "canViewPii": False,
        "description": "Digital Portal Metrics Only (PII Masked)"
    },
    "ROLE_INVESTMENTS": {
        "title": "Investment Consultants",
        "allowedCubes": [
            "investments_fundamental",
            "member_monthly_investment"
        ],
        "canViewPii": False,
        "description": "Investment Products & Market Values (PII Masked)"
    },
    "ROLE_ANNUITY": {
        "title": "Annuity & Preservation",
        "allowedCubes": [
            "annuity_quotation",
            "in_fund_exit_member_monthly"
        ],
        "canViewPii": False,
        "description": "Annuity Quotes and In-Fund Preservation (PII Masked)"
    }
}

def format_currency_bn(val: float) -> str:
    if val >= 1e12:
        return f"R {val / 1e12:.2f}T"
    if val >= 1e9:
        return f"R {val / 1e9:.2f}bn"
    if val >= 1e6:
        return f"R {val / 1e6:.2f}M"
    if val >= 1e3:
        return f"R {val / 1e3:.2f}K"
    return f"R {val:,.2f}"

def format_number(val: float) -> str:
    return f"{int(val):,}"

def build_cube_filters(raw_filters: dict, target_cube: str = "MemberMonthly") -> list:
    """Translates UI slicers into Cube.js filter syntax."""
    cube_filters = []
    
    # 1. Date filter (Snapshot date_sk vs Year)
    date_val = raw_filters.get("date")
    if date_val and date_val not in ("All", "All Dates", ""):
        # Match YYYY-MM-DD snapshot date
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', str(date_val))
        if m:
            date_sk = f"{m.group(1)}{m.group(2)}{m.group(3)}"
            cube_filters.append({
                "member": "DimDate.dateSk",
                "operator": "equals",
                "values": [date_sk]
            })
        else:
            # Fall back to calendarYear if full year specified
            for y in ("2025", "2024", "2023", "2022"):
                if y in str(date_val):
                    cube_filters.append({
                        "member": "DimDate.calendarYear",
                        "operator": "equals",
                        "values": [y]
                    })
                    break

    # 2. Fund filter & Business Unit filter
    fund = raw_filters.get("fund") or raw_filters.get("fund_name")
    bu = raw_filters.get("business_unit")
    
    if fund and fund not in ("All", "All Funds", "All Funds (SUS)", ""):
        if target_cube == "InvestmentsFundamental" and "umbrella" in fund.lower():
            cube_filters.append({
                "member": "DimFund.fundName",
                "operator": "contains",
                "values": ["Umbrella"]
            })
        elif target_cube == "InvestmentsFundamental":
            clean_name = fund.replace("Fund", "").strip()
            cube_filters.append({
                "member": "DimFund.fundName",
                "operator": "contains",
                "values": [clean_name if clean_name else fund]
            })
        else:
            cube_filters.append({
                "member": "DimFund.fundName",
                "operator": "equals",
                "values": [fund]
            })
    elif bu == "SUS":
        # SUS Business Unit includes all Sanlam umbrella / Sanlam funds
        cube_filters.append({
            "member": "DimFund.fundName",
            "operator": "contains",
            "values": ["Sanlam"]
        })
    elif bu == "SCS":
        # SCS (Sanlam Corporate Solutions / standalone corporate funds)
        cube_filters.append({
            "member": "DimFund.fundName",
            "operator": "notContains",
            "values": ["Sanlam"]
        })
        
    # 3. Client filter (supported on MemberMonthly)
    if target_cube == "MemberMonthly":
        client = raw_filters.get("client") or raw_filters.get("client_name")
        if client and client not in ("All", ""):
            cube_filters.append({
                "member": "DimClient.clientName",
                "operator": "equals",
                "values": [client]
            })
            
    # 4. Employer filter (supported on MemberMonthly)
    if target_cube == "MemberMonthly":
        employer = raw_filters.get("employer") or raw_filters.get("employer_name")
        if employer and employer not in ("All", ""):
            cube_filters.append({
                "member": "DimEmployer.employerName",
                "operator": "equals",
                "values": [employer]
            })
                
    return cube_filters

LAKEHOUSE_FUNDS = [
    "All Funds",
    "Sanlam Umbrella Fund",
    "Sanlam Easy Retirement",
    "Sanlam Unity Umbrella",
    "Sanlam Trust (Pty) Ltd",
    "Sanlam BF",
    "Sanlam Vida",
    "Sanlam Plus Pension Fund",
    "Sanlam Plus Provident Fund",
    "Sanlam IPP",
    "Sanlam Kenya",
    "Sanlam Limited",
    "Building Industry Bargaining Counc",
    "The Unclaimed Benefits Prov Pres",
    "NFMW",
    "Impala Platinum Limited",
    "The Unclaimed Ben Pen Pres Fund",
    "MGF",
    "PEP_Sec 14",
    "Anglo American Platinum Corp Ltd",
    "Nampak",
    "Municipal Workers Retirement Fund",
    "RCL FOODS PROVIDENT FUND",
    "Atlantis Foundries Provident Fund",
    "FAIRSURE ADMINISTRATION (PTY) LTD",
    "#ABSA Pension Fund"
]

LAKEHOUSE_SUS_FUNDS = [
    "All Funds (SUS)",
    "Sanlam Umbrella Fund",
    "Sanlam Easy Retirement",
    "Sanlam Unity Umbrella",
    "Sanlam Trust (Pty) Ltd",
    "Sanlam BF",
    "Sanlam Vida",
    "Sanlam Plus Pension Fund",
    "Sanlam Plus Provident Fund",
    "Sanlam IPP",
    "Sanlam Kenya",
    "Sanlam Limited"
]

LAKEHOUSE_EMPLOYERS = [
    "All",
    "Sasol Group",
    "Standard Bank SA",
    "Anglo American",
    "Discovery Health",
    "(NTU) - Abaqulusi Private Hospital (Pty) Ltd",
    "(NTU) October Sky Planthire And Suppliers (Pty) Ltd",
    "00815 Formex:  Maguire C",
    "0100Unclaimed120 - Sec 28",
    "City of Cape Town",
    "Transnet Freight Rail"
]

LAKEHOUSE_CLIENTS = [
    "All",
    "Corporate Clients",
    "SME Clients",
    "Institutional",
    "FAIRSURE ADMINISTRATION (PTY) LTD",
    "Atlantis Foundries Provident Fund",
    "Municipal Workers Retirement Fund",
    "RCL FOODS PROVIDENT FUND"
]

LAKEHOUSE_DATES = [
    "2025-01-31 (Snapshot)",
    "2025-02-28 (Snapshot)",
    "2025-03-31 (Snapshot)",
    "2025-04-30 (Snapshot)",
    "2025-05-31 (Snapshot)",
    "2025 (Full Year)",
    "2024 (Full Year)",
    "All Dates"
]



class SanlamOnlineHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/status":
            self.handle_api_status()
        elif path == "/api/catalog":
            self.handle_api_catalog()
        elif path == "/api/roles":
            self.handle_api_roles()
        elif path == "/api/member_analysis/slicers":
            filters = {k: v[0] for k, v in query.items()}
            self.handle_api_member_analysis_slicers(filters)
        elif path == "/api/member_analysis/query":
            tab = query.get("tab", ["overview"])[0]
            role = query.get("role", ["ROLE_EXECUTIVE_ALL"])[0]
            mask_pii = query.get("maskPii", ["true"])[0].lower() == "true"
            filters = {k: v[0] for k, v in query.items() if k not in ("tab", "role", "maskPii")}
            self.handle_api_member_analysis_query(tab, role, mask_pii, filters)
        elif path == "/api/investment_analysis/slicers":
            filters = {k: v[0] for k, v in query.items()}
            self.handle_api_investment_analysis_slicers(filters)
        elif path == "/api/investment_analysis/query":
            tab = query.get("tab", ["overview"])[0]
            role = query.get("role", ["ROLE_EXECUTIVE_ALL"])[0]
            mask_pii = query.get("maskPii", ["true"])[0].lower() == "true"
            filters = {k: v[0] for k, v in query.items() if k not in ("tab", "role", "maskPii")}
            self.handle_api_investment_analysis_query(tab, role, mask_pii, filters)
        elif path == "/api/annuity/slicers":
            filters = {k: v[0] for k, v in query.items()}
            self.handle_api_annuity_slicers(filters)
        elif path == "/api/annuity/query":
            tab = query.get("tab", ["overview"])[0]
            role = query.get("role", ["ROLE_EXECUTIVE_ALL"])[0]
            mask_pii = query.get("maskPii", ["true"])[0].lower() == "true"
            filters = {k: v[0] for k, v in query.items() if k not in ("tab", "role", "maskPii")}
            self.handle_api_annuity_query(tab, role, mask_pii, filters)
        elif path == "/api/telemetry/overview":
            self.handle_api_telemetry_overview()
        elif path == "/api/telemetry/executions":
            limit = int(query.get("limit", [100])[0])
            dashboard_filter = query.get("dashboard", ["all"])[0]
            self.handle_api_telemetry_executions(limit, dashboard_filter)
        elif path == "/api/telemetry/cloud":
            self.handle_api_telemetry_cloud()
        elif path == "/api/telemetry/export-bundle":
            self.handle_api_telemetry_export_bundle()
        elif path == "/api/telemetry/export-markdown":
            self.handle_api_telemetry_export_markdown()
        else:
            super().do_GET()

    def send_json(self, data, status=200):
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status=200, content_type="text/markdown; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def handle_api_status(self):
        state = {}
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)

        tables_dict = state.get("tables", {})
        cubes_dict = state.get("cubes", {})
        total_tables = len(tables_dict) if tables_dict else 44
        completed_tables = sum(1 for t in tables_dict.values() if t.get("status") == "COMPLETED" and t.get("gcs_path"))
        total_cubes = len(cubes_dict) if cubes_dict else 12

        self.send_json({
            "status": "HEALTHY",
            "lakehouse": "gs://scbi-ducklake-myanalyticsproduct/",
            "total_cubes": total_cubes,
            "total_tables": total_tables,
            "migrated_tables": completed_tables,
            "percent_ready": round((completed_tables / total_tables) * 100, 1) if total_tables else 100.0,
            "cubes": cubes_dict
        })

    def handle_api_catalog(self):
        if os.path.exists(CATALOG_PATH):
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.send_json(data)
        else:
            self.send_json({"error": "Catalog not found"}, 404)

    def handle_api_roles(self):
        self.send_json(ROLE_PERMISSIONS)

    def handle_api_member_analysis_slicers(self, filters=None):
        try:
            import time
            import member_engine
            import telemetry_engine
            t0 = time.time()
            data = member_engine.get_member_slicers(filters)
            elapsed_ms = int((time.time() - t0) * 1000)
            telemetry_engine.record_query(
                dashboard="member_analysis",
                tab="slicers_cascade",
                engine="DuckDB-Dimensions",
                duration_ms=elapsed_ms,
                filters=filters,
                status=200,
                cache_status="HIT" if elapsed_ms < 10 else "MISS"
            )
            self.send_json(data)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_api_member_analysis_query(self, tab, role, mask_pii, filters):
        try:
            import time
            import member_engine
            import telemetry_engine
            t0 = time.time()
            data = member_engine.query_member_dashboard(tab, role, mask_pii, filters)
            elapsed_ms = int((time.time() - t0) * 1000)
            data["execution_time_ms"] = elapsed_ms
            cache_status = "HIT" if elapsed_ms < 10 else "MISS"
            telemetry_engine.record_query(
                dashboard="member_analysis",
                tab=tab,
                engine="DuckDB-Cached" if cache_status == "HIT" else "DuckDB-GCS-Direct",
                duration_ms=elapsed_ms,
                filters=filters,
                status=200,
                cache_status=cache_status
            )
            self.send_json(data)
        except Exception as e:
            try:
                import telemetry_engine
                telemetry_engine.record_query("member_analysis", tab, "DuckDB", 0, filters=filters, status=500, error=str(e))
            except Exception:
                pass
            self.send_json({"error": str(e)}, 500)

    def handle_api_investment_analysis_slicers(self, filters=None):
        try:
            import time
            import investment_engine
            import telemetry_engine
            t0 = time.time()
            data = investment_engine.get_investment_slicers(filters)
            elapsed_ms = int((time.time() - t0) * 1000)
            telemetry_engine.record_query(
                dashboard="investment_analysis",
                tab="slicers_cascade",
                engine="DuckDB-Dimensions",
                duration_ms=elapsed_ms,
                filters=filters,
                status=200,
                cache_status="HIT" if elapsed_ms < 10 else "MISS"
            )
            self.send_json(data)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_api_investment_analysis_query(self, tab, role, mask_pii, filters):
        try:
            import time
            import investment_engine
            import telemetry_engine
            t0 = time.time()
            data = investment_engine.query_investment_dashboard(tab, role, mask_pii, filters)
            elapsed_ms = int((time.time() - t0) * 1000)
            data["execution_time_ms"] = elapsed_ms
            cache_status = "HIT" if elapsed_ms < 10 else "MISS"
            telemetry_engine.record_query(
                dashboard="investment_analysis",
                tab=tab,
                engine="DuckDB-Cached" if cache_status == "HIT" else "DuckDB-GCS-Direct",
                duration_ms=elapsed_ms,
                filters=filters,
                status=200,
                cache_status=cache_status
            )
            self.send_json(data)
        except Exception as e:
            try:
                import telemetry_engine
                telemetry_engine.record_query("investment_analysis", tab, "DuckDB", 0, filters=filters, status=500, error=str(e))
            except Exception:
                pass
            self.send_json({"error": str(e)}, 500)

    def handle_api_annuity_slicers(self, filters=None):
        try:
            import time
            import annuity_engine
            import telemetry_engine
            t0 = time.time()
            data = annuity_engine.get_annuity_slicers(filters)
            elapsed_ms = int((time.time() - t0) * 1000)
            telemetry_engine.record_query(
                dashboard="annuity_reporting",
                tab="slicers_cascade",
                engine="DuckDB-Dimensions",
                duration_ms=elapsed_ms,
                filters=filters,
                status=200,
                cache_status="HIT" if elapsed_ms < 10 else "MISS"
            )
            self.send_json(data)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_api_annuity_query(self, tab, role, mask_pii, filters):
        try:
            import time
            import annuity_engine
            import telemetry_engine
            t0 = time.time()
            data = annuity_engine.query_annuity_dashboard(tab, role, mask_pii, filters)
            elapsed_ms = int((time.time() - t0) * 1000)
            data["execution_time_ms"] = elapsed_ms
            cache_status = "HIT" if elapsed_ms < 50 else "MISS"
            telemetry_engine.record_query(
                dashboard="annuity_reporting",
                tab=tab,
                engine="DuckDB-Cached" if cache_status == "HIT" else "DuckDB-GCS-Direct",
                duration_ms=elapsed_ms,
                filters=filters,
                status=200,
                cache_status=cache_status
            )
            self.send_json(data)
        except Exception as e:
            try:
                import telemetry_engine
                telemetry_engine.record_query("annuity_reporting", tab, "DuckDB", 0, filters=filters, status=500, error=str(e))
            except Exception:
                pass
            self.send_json({"error": str(e)}, 500)

    def handle_api_telemetry_overview(self):
        try:
            import telemetry_engine
            data = telemetry_engine.get_telemetry_overview()
            self.send_json(data)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_api_telemetry_executions(self, limit=100, dashboard_filter="all"):
        try:
            import telemetry_engine
            data = telemetry_engine.get_all_executions(limit, dashboard_filter)
            self.send_json(data)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_api_telemetry_cloud(self):
        try:
            import telemetry_engine
            status = telemetry_engine.get_gcp_cloud_status()
            logs = telemetry_engine.get_recent_cloud_run_logs(15)
            self.send_json({"cloud": status, "logs": logs})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_api_telemetry_export_bundle(self):
        try:
            import telemetry_engine
            bundle = telemetry_engine.generate_llm_bundle()
            self.send_json(bundle)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_api_telemetry_export_markdown(self):
        try:
            import telemetry_engine
            md = telemetry_engine.generate_llm_markdown()
            self.send_text(md, content_type="text/markdown; charset=utf-8")
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

_CUBE_QUERY_CACHE = {}

def query_live_cube(query_dict: dict, role: str, can_view_pii: bool, timeout_sec: int = 45):
    """Attempts a query against the live Cloud Run Cube.js instance with polling and caching."""
    if not jwt:
        return None

    cache_key = json.dumps((query_dict, role, can_view_pii), sort_keys=True)
    if cache_key in _CUBE_QUERY_CACHE:
        cached_entry = _CUBE_QUERY_CACHE[cache_key]
        if (datetime.datetime.now() - cached_entry["time"]).total_seconds() < 600:
            return cached_entry["data"]

    try:
        import time
        token = jwt.encode({
            "iat": int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
            "exp": int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).timestamp()),
            "role": role,
            "canViewPii": can_view_pii
        }, CUBE_SECRET, algorithm="HS256")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        start = datetime.datetime.now()
        while (datetime.datetime.now() - start).total_seconds() < timeout_sec:
            req = urllib.request.Request(
                f"{CUBE_BASE_URL}/cubejs-api/v1/load",
                data=json.dumps({"query": query_dict}).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("continueWait") or res.get("error") == "Continue wait":
                    time.sleep(1.0)
                    continue
                if "data" in res:
                    _CUBE_QUERY_CACHE[cache_key] = {"time": datetime.datetime.now(), "data": res}
                return res
    except Exception as e:
        print(f"[ERROR] query_live_cube failed: {e}")
        return None



def run_server(port=PORT):
    print(f"\n" + "=" * 80)
    print(f" Sanlam Online Analytics Portal Server starting at: http://localhost:{port}/")
    print(f" Serving DuckLake, DuckDB, Cube.js Semantic Models & Report Replicas")
    print(f" Brand: Sanlam Corporate & Online (https://www.sanlamonline.co.za/)")
    print(f"=" * 80 + "\n")
    with http.server.ThreadingHTTPServer(("", port), SanlamOnlineHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_server(port)
