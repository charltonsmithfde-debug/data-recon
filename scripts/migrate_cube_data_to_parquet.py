"""
migrate_cube_data_to_parquet.py

Data pipeline to migrate Snowflake tables to Parquet with per-cube delivery tracking and deduplication.
Ensures that any table referenced by multiple cubes is exported only ONCE, while immediately
marking all referencing cubes as having that table completed.

Usage:
    python scripts/migrate_cube_data_to_parquet.py --status
    python scripts/migrate_cube_data_to_parquet.py --cube fund_analytics_monthly_metrics --dry-run
    python scripts/migrate_cube_data_to_parquet.py --cube fund_analytics_monthly_metrics
    python scripts/migrate_cube_data_to_parquet.py --cube digital_portal
    python scripts/migrate_cube_data_to_parquet.py --all
"""

import os
import sys
import json
import argparse
import datetime
import shutil
from decimal import Decimal
import snowflake.connector
import webbrowser
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def _custom_browser_open(url, new=0, autoraise=True):
    sys.stdout.write("\n" + "#" * 90 + "\n")
    sys.stdout.write(" >>> ACTION REQUIRED: SNOWFLAKE SSO BROWSER AUTHENTICATION NEEDED <<<\n")
    sys.stdout.write(" If your browser did not automatically open, please click or copy/paste this URL:\n\n")
    sys.stdout.write(f"   {url}\n\n")
    sys.stdout.write("#" * 90 + "\n\n")
    sys.stdout.flush()
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", f'Start-Process "{url}"'], shell=False)
    except Exception as e:
        sys.stdout.write(f"[NOTE] Automatic browser launch failed ({e}). Please click the link above directly.\n")
        sys.stdout.flush()
    return True

class _CustomBrowserController:
    def open(self, url, new=0, autoraise=True):
        return _custom_browser_open(url, new, autoraise)
    def open_new(self, url):
        return _custom_browser_open(url, 1, True)
    def open_new_tab(self, url):
        return _custom_browser_open(url, 2, True)

webbrowser.open = _custom_browser_open
webbrowser.open_new = _custom_browser_open
webbrowser.get = lambda using=None: _CustomBrowserController()

try:
    import snowflake.connector.auth_webbrowser
    snowflake.connector.auth_webbrowser.webbrowser.open = _custom_browser_open
    snowflake.connector.auth_webbrowser.webbrowser.open_new = _custom_browser_open
    snowflake.connector.auth_webbrowser.webbrowser.get = lambda using=None: _CustomBrowserController()
except Exception:
    pass

# ── 1. Cube Registry (All 12 Cubes & Their Mapped Snowflake Tables) ───────────────
CUBE_REGISTRY = {
    "fund_analytics_monthly_metrics": {
        "description": "Consolidated member monthly metrics (flagship 4-in-1 fact)",
        "tables": [
            "CNF__AGG_CONSOLIDATED_MEMBER_MEASURES_MONTHLY",
            "CNF__FACT_MEMBER_SEGMENTATION",
            "DIM_DATE",
            "CNF__DIM_CLIENT",
            "CNF__DIM_FUND",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_EMPLOYER_BRANCH",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_MEMBER",
            "CNF__DIM_ADMIN_PRODUCT",
            "CNF__DIM_INVESTMENT_PRODUCT",
            "CNF__DIM_REVISION_ASSOCIATION",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_SERVICE_OFFERING",
            "CNF__DIM_RISK_PRODUCT",
            "CNF__DIM_INSURER",
            "CNF__DIM_TRANSACTION_TYPE",
            "CNF__DIM_CLAIM_TYPE",
            "CNF__DIM_CLAIM_STATUS",
            "CNF__DIM_BENEFICIARY",
            "CNF__DIM_BANK_ACCOUNT"
        ]
    },
    "member_monthly": {
        "description": "Unconsolidated member monthly galaxy (5 facts)",
        "tables": [
            "CNF__FACT_MEMBER_INVESTMENT_AUA",
            "CNF__FACT_MEMBER_INVESTMENT_AUM",
            "CNF__FACT_MEMBER_BASE_CONTRIBUTION",
            "CNF__FACT_MEMBER_MONTHLY_FEES",
            "CNF__FACT_MEMBER_BASE_RISK_PREMIUM",
            "DIM_DATE",
            "CNF__DIM_CLIENT",
            "CNF__DIM_FUND",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_EMPLOYER_BRANCH",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_MEMBER",
            "CNF__DIM_ADMIN_PRODUCT",
            "CNF__DIM_INVESTMENT_PRODUCT",
            "CNF__DIM_RISK_PRODUCT",
            "CNF__DIM_INSURER",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_REVISION_ASSOCIATION",
            "CNF__DIM_SERVICE_OFFERING",
            "CNF__FACT_MEMBER_SEGMENTATION"
        ]
    },
    "member_transactions": {
        "description": "Member transaction history and transaction types",
        "tables": [
            "CNF__FACT_MEMBER_TRANSACTIONS",
            "DIM_DATE",
            "CNF__DIM_CLIENT",
            "CNF__DIM_FUND",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_EMPLOYER_BRANCH",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_MEMBER",
            "CNF__DIM_ADMIN_PRODUCT",
            "CNF__DIM_INVESTMENT_PRODUCT",
            "CNF__DIM_TRANSACTION_TYPE",
            "CNF__DIM_RISK_PRODUCT",
            "CNF__DIM_INSURER",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_REVISION_ASSOCIATION",
            "CNF__DIM_SERVICE_OFFERING",
            "CNF__FACT_MEMBER_SEGMENTATION"
        ]
    },
    "assetflows_member_monthly": {
        "description": "Claims, claim payments, and AUA/AUM asset flows",
        "tables": [
            "CNF__FACT_MEMBER_INVESTMENT_AUA",
            "CNF__FACT_MEMBER_INVESTMENT_AUM",
            "CNF__FACT_MEMBER_CLAIMS",
            "CNF__FACT_MEMBER_CLAIM_PAYMENT",
            "DIM_DATE",
            "CNF__DIM_CLIENT",
            "CNF__DIM_FUND",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_EMPLOYER_BRANCH",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_MEMBER",
            "CNF__DIM_INVESTMENT_PRODUCT",
            "CNF__DIM_ADMIN_PRODUCT",
            "CNF__DIM_REVISION_ASSOCIATION",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_INSURER",
            "CNF__DIM_CLAIM_TYPE",
            "CNF__DIM_CLAIM_STATUS",
            "CNF__DIM_BENEFICIARY",
            "CNF__FACT_MEMBER_SEGMENTATION"
        ]
    },
    "digital_portal": {
        "description": "Complete digital portal suite (registrations, events, YTD/TD)",
        "tables": [
            "CNF__FACT_DIGITAL_PORTAL_REGISTRATIONS",
            "CNF__FACT_DIGITAL_PORTAL_EVENTS",
            "CNF__AGG_DIGITAL_PORTAL_REGISTRATIONS_YTD",
            "CNF__AGG_DIGITAL_PORTAL_REGISTRATIONS_TD",
            "DIM_DATE",
            "CNF__DIM_CLIENT",
            "CNF__DIM_FUND",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_EMPLOYER_BRANCH",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_MEMBER",
            "CNF__DIM_ADMIN_PRODUCT",
            "CNF__DIM_REVISION_ASSOCIATION",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_RISK_PRODUCT",
            "CNF__DIM_INSURER",
            "CNF__DIM_SERVICE_OFFERING",
            "CNF__DIM_DIGITAL_PORTAL",
            "CNF__DIM_DIGITAL_PORTAL_USER",
            "CNF__FACT_MEMBER_SEGMENTATION"
        ]
    },
    "digital_portal_events": {
        "description": "Digital portal user interaction events",
        "tables": [
            "CNF__FACT_DIGITAL_PORTAL_EVENTS",
            "CNF__AGG_DIGITAL_PORTAL_EVENTS_YTD",
            "DIM_DATE",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_MEMBER",
            "CNF__DIM_DIGITAL_PORTAL",
            "CNF__DIM_DIGITAL_PORTAL_USER",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_FUND",
            "CNF__FACT_MEMBER_SEGMENTATION",
            "CNF__DIM_CLIENT",
            "CNF__DIM_EMPLOYER_BRANCH",
            "CNF__DIM_ADMIN_PRODUCT",
            "CNF__DIM_REVISION_ASSOCIATION",
            "CNF__DIM_RISK_PRODUCT",
            "CNF__DIM_INSURER",
            "CNF__DIM_SERVICE_OFFERING"
        ]
    },
    "digital_portal_registrations": {
        "description": "Digital portal user registrations",
        "tables": [
            "CNF__FACT_DIGITAL_PORTAL_REGISTRATIONS",
            "CNF__AGG_DIGITAL_PORTAL_REGISTRATIONS_YTD",
            "CNF__AGG_DIGITAL_PORTAL_REGISTRATIONS_TD",
            "DIM_DATE",
            "CNF__DIM_CLIENT",
            "CNF__DIM_FUND",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_MEMBER",
            "CNF__DIM_DIGITAL_PORTAL",
            "CNF__DIM_DIGITAL_PORTAL_USER",
            "CNF__FACT_MEMBER_SEGMENTATION",
            "CNF__DIM_EMPLOYER_BRANCH",
            "CNF__DIM_ADMIN_PRODUCT",
            "CNF__DIM_REVISION_ASSOCIATION",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_RISK_PRODUCT",
            "CNF__DIM_INSURER",
            "CNF__DIM_SERVICE_OFFERING"
        ]
    },
    "aggregated_digital_portal_registrations": {
        "description": "Digital portal registration counts aggregated by demographic bands",
        "tables": [
            "CNF__FACT_DIGITAL_PORTAL_REGISTRATIONS",
            "CNF__AGG_DIGITAL_PORTAL_REGISTRATIONS_YTD",
            "CNF__AGG_DIGITAL_PORTAL_REGISTRATIONS_TD",
            "CNF__DIM_CLIENT",
            "CNF__DIM_FUND",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_EMPLOYER_BRANCH",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_MEMBER",
            "CNF__DIM_ADMIN_PRODUCT",
            "CNF__DIM_REVISION_ASSOCIATION",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_RISK_PRODUCT",
            "CNF__DIM_INSURER",
            "CNF__DIM_SERVICE_OFFERING",
            "CNF__DIM_DIGITAL_PORTAL",
            "CNF__DIM_DIGITAL_PORTAL_USER",
            "CNF__FACT_MEMBER_SEGMENTATION",
            "DIM_DATE"
        ]
    },
    "annuity_quotation": {
        "description": "Annuity quotations and broker consultants",
        "tables": [
            "CNF__FACT_ANNUITY_QUOTATIONS",
            "CNF__DIM_FUND",
            "CNF__DIM_MEMBER",
            "CNF__DIM_BENEFICIARY",
            "CNF__DIM_BROKER_CONSULTANT",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_ANNUITY_PRODUCT",
            "DIM_DATE"
        ]
    },
    "in_fund_exit_member_monthly": {
        "description": "In-fund preservation and exit analysis",
        "tables": [
            "CNF__PROD_IN_FUND_EXIT_MEMBER_MONTHLY",
            "CNF__FACT_IN_FUND_EXIT_MEMBER_AUA_MONTHLY",
            "CNF__FACT_IN_FUND_EXIT_MEMBER_AUM_MONTHLY",
            "DIM_DATE",
            "CNF__DIM_MEMBER",
            "CNF__DIM_FUND",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_INVESTMENT_PRODUCT"
        ]
    },
    "investments_fundamental": {
        "description": "Client market values and fund transactions",
        "tables": [
            "CNF__FACT_INVESTMENT_TRANSACTIONS",
            "CNF__FACT_INV_MONTHLY_MARKET_VALUE",
            "CNF__DIM_INVESTMENT_PRODUCT",
            "CNF__DIM_FUND",
            "CNF__DIM_TRANSACTION_TYPE",
            "DIM_DATE"
        ]
    },
    "member_monthly_investment": {
        "description": "Member monthly investment subset",
        "tables": [
            "CNF__FACT_MEMBER_INVESTMENT_AUA",
            "CNF__DIM_CLIENT",
            "CNF__DIM_INVESTMENT_PRODUCT",
            "CNF__FACT_MEMBER_SEGMENTATION",
            "CNF__DIM_MEMBER",
            "CNF__DIM_FUND",
            "CNF__DIM_EMPLOYER",
            "CNF__DIM_EMPLOYER_BRANCH",
            "CNF__DIM_PAYPOINT",
            "CNF__DIM_REVISION_ASSOCIATION",
            "CNF__DIM_ADMIN_PRODUCT",
            "CNF__DIM_AGGREGATOR",
            "CNF__DIM_RISK_PRODUCT",
            "CNF__DIM_INSURER",
            "DIM_DATE"
        ]
    }
}

# Tables requiring date partitioning (all remaining tables filtered to 2024-2025 are < 25 GB and unload as 256MB chunks)
PARTITIONED_FACTS = {}

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migration_state.json")

# ── 2. State Management ────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"tables": {}, "cubes": {}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)

def get_table_schema(table_name):
    if table_name == "DIM_DATE":
        return "SCBI_SDP_MART"
    elif table_name == "CNF__PROD_IN_FUND_EXIT_MEMBER_MONTHLY":
        return "SCBI_CDP_PRODUCT"
    return "SCBI_CDP_MART"

# ── 3. Snowflake Connection ───────────────────────────────────────────────────
def get_snowflake_connection(warehouse, database):
    account = os.environ.get("SNOWFLAKE_ACCOUNT", "gw52249.eu-west-1").strip('"')
    user = os.environ.get("SNOWFLAKE_USER", "G988557").strip('"')
    role = os.environ.get("SNOWFLAKE_ROLE", "ARDEVSCBIPRODUCTDEVELOPERSF").strip('"')
    
    print(f"Connecting to Snowflake (Account: {account}, User: {user}, Role: {role}, WH: {warehouse})...", flush=True)
    conn = snowflake.connector.connect(
        account=account,
        user=user,
        authenticator="externalbrowser",
        role=role,
        warehouse=warehouse,
        database=database,
        client_session_keep_alive=True
    )
    return conn

# ── 4. Migration Execution ────────────────────────────────────────────────────
def get_column_select_expr(conn, database, schema, table_name):
    if not conn:
        return "*"
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT COLUMN_NAME, DATA_TYPE
            FROM {database}.INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table_name}'
            ORDER BY ORDINAL_POSITION
        """)
        cols = cur.fetchall()
        cur.close()
        if not cols:
            return "*"
            
        has_tz = any(r[1] in ['TIMESTAMP_LTZ', 'TIMESTAMP_TZ'] for r in cols)
        if not has_tz:
            return "*"
            
        select_parts = []
        for col_name, dtype in cols:
            if dtype in ['TIMESTAMP_LTZ', 'TIMESTAMP_TZ']:
                select_parts.append(f"{col_name}::TIMESTAMP_NTZ AS {col_name}")
            else:
                select_parts.append(col_name)
        return ",\n        ".join(select_parts)
    except Exception as e:
        return "*"

def build_copy_sql(database, schema, table_name, stage_name, select_expr="*", date_filter=None):
    target_path = f"{stage_name}/{table_name.lower()}/"
    where_clause = f"\n    WHERE {date_filter}" if date_filter else ""
    if select_expr == "*" and not date_filter:
        from_clause = f"{database}.{schema}.{table_name}"
    else:
        from_clause = f"(\n    SELECT\n        {select_expr}\n    FROM {database}.{schema}.{table_name}{where_clause}\n)"
    
    if table_name in PARTITIONED_FACTS:
        partition_expr = PARTITIONED_FACTS[table_name]
        sql = f"""
COPY INTO '{target_path}'
FROM {from_clause}
PARTITION BY ({partition_expr})
FILE_FORMAT = (TYPE = PARQUET COMPRESSION = SNAPPY)
HEADER = TRUE
MAX_FILE_SIZE = 268435456;
"""
    else:
        sql = f"""
COPY INTO '{target_path}'
FROM {from_clause}
FILE_FORMAT = (TYPE = PARQUET COMPRESSION = SNAPPY)
HEADER = TRUE
MAX_FILE_SIZE = 268435456
OVERWRITE = TRUE;
"""
    return sql.strip(), target_path

def migrate_table(conn, database, table_name, stage_name, cube_name, state, dry_run=False, date_filter=None):
    schema = get_table_schema(table_name)
    select_expr = get_column_select_expr(conn, database, schema, table_name)
    sql, target_path = build_copy_sql(database, schema, table_name, stage_name, select_expr, date_filter)
    
    print(f"  --> [MIGRATING] {database}.{schema}.{table_name}", flush=True)
    if dry_run:
        print(f"      [DRY-RUN SQL]:\n      " + sql.replace("\n", "\n      "))
        return {
            "status": "COMPLETED_DRY_RUN",
            "schema": schema,
            "stage_path": target_path,
            "migrated_for_cube": cube_name,
            "completed_at": datetime.datetime.now().isoformat()
        }
    
    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        # Snowflake COPY INTO returns: file, rows_unloaded, input_bytes, output_bytes
        total_rows_unloaded = 0
        total_output_bytes = 0
        for r in rows:
            if len(r) == 3:
                total_rows_unloaded += int(r[0] or 0)
                total_output_bytes += int(r[2] or 0)
            elif len(r) >= 4:
                total_rows_unloaded += int(r[1] or 0)
                total_output_bytes += int(r[3] or 0)
        
        cur.close()
        return {
            "status": "COMPLETED",
            "schema": schema,
            "stage_path": target_path,
            "rows_unloaded": total_rows_unloaded,
            "output_bytes": total_output_bytes,
            "migrated_for_cube": cube_name,
            "completed_at": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        cur.close()
        print(f"      [ERROR] Failed to export {table_name}: {e}", flush=True)
        return {
            "status": "FAILED",
            "schema": schema,
            "error": str(e),
            "migrated_for_cube": cube_name,
            "failed_at": datetime.datetime.now().isoformat()
        }

# ── 5. End-to-End Single-Table Pipeline (Option A) ───────────────────────────
def check_gcs_landing(bucket, schema_lower, tbl_lower):
    """
    Verify that Parquet files exist in GCS for the given table and are non-empty.
    """
    gcs_dest = f"gs://{bucket}/{schema_lower}/{tbl_lower}/"
    check_cmd = f'gcloud storage ls --recursive "{gcs_dest}"'
    res = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        return False, f"GCS check returned code {res.returncode}: {res.stderr.strip()}"
    files = [line.strip() for line in res.stdout.splitlines() if line.strip().endswith(".parquet")]
    if not files:
        return False, f"No .parquet files found in {gcs_dest}"
    return True, files

def migrate_table_end_to_end(conn, database, tbl, stage_name, bucket, cube_name, state, dry_run=False, keep_local=False, date_filter=None):
    """
    Option A End-to-End Pipeline for ONE table:
      1. Verify if already completed in GCS (deduplication check).
      2. Unload from Snowflake to User Stage (@~/parquet_migration/<table>/).
      3. Download Parquet from Stage to Local Temporary Buffer.
      4. Upload from Local Buffer to GCS (gs://<bucket>/<schema>/<table>/).
      5. CHECK & VERIFY GCS landing.
      6. DELETE local temporary parquet files immediately.
      7. PURGE Snowflake stage files (REMOVE @~/parquet_migration/<table>/).
      8. Persist table state to migration_state.json.
      9. Return result and proceed to next table.
    """
    tbl_state = state["tables"].get(tbl)
    if tbl_state and tbl_state.get("status") in ["COMPLETED", "COMPLETED_DRY_RUN"] and tbl_state.get("gcs_path"):
        print(f"  [ALREADY COMPLETE] Table '{tbl}' already landed in GCS ({tbl_state.get('gcs_path')}). Skipping.", flush=True)
        if "referencing_cubes" not in tbl_state:
            tbl_state["referencing_cubes"] = []
        if cube_name and cube_name not in tbl_state["referencing_cubes"]:
            tbl_state["referencing_cubes"].append(cube_name)
            save_state(state)
        return tbl_state, True

    schema = get_table_schema(tbl)
    tbl_lower = tbl.lower()
    schema_lower = schema.lower()
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_dir = os.path.join(root_dir, "data", schema_lower, tbl_lower)

    # 0. Pre-clean target stage path to ensure fresh unload
    if not dry_run and conn:
        try:
            cur = conn.cursor()
            cur.execute(f"REMOVE {stage_name}/{tbl_lower}/;")
            cur.close()
        except Exception:
            pass

    # 1. Unload from Snowflake
    result = migrate_table(conn, database, tbl, stage_name, cube_name, state, dry_run, date_filter)
    if dry_run or result.get("status") != "COMPLETED":
        return result, False

    # 2. Download from Stage to Local Temp Buffer
    os.makedirs(local_dir, exist_ok=True)
    formatted_local_dir = local_dir.replace("\\", "/")

    cur = conn.cursor()
    cur.execute(f"LIST {stage_name}/{tbl_lower}/")
    stage_files = cur.fetchall()

    # Check for partition subdirectories (e.g. date_month=YYYYMM/) to avoid Windows flat-download collisions
    subdirs = set()
    stage_key = f"/{tbl_lower}/"
    for r in stage_files:
        path = str(r[0])
        if stage_key in path:
            rel = path.split(stage_key, 1)[1]
            if "/" in rel:
                subdirs.add(rel.rsplit("/", 1)[0])

    if subdirs:
        print(f"      [1/5 STAGE -> LOCAL] Downloading {len(subdirs)} partition folder(s) to {local_dir}...", flush=True)
        for s in sorted(subdirs):
            sub_local = os.path.join(local_dir, s).replace("\\", "/")
            os.makedirs(sub_local, exist_ok=True)
            cur.execute(f"GET {stage_name}/{tbl_lower}/{s}/ file://{sub_local}")
    else:
        print(f"      [1/5 STAGE -> LOCAL] Downloading Parquet to {local_dir}...", flush=True)
        cur.execute(f"GET {stage_name}/{tbl_lower}/ file://{formatted_local_dir}")
    cur.close()

    # 3. Upload from Local to GCS
    gcs_dest = f"gs://{bucket}/{schema_lower}/{tbl_lower}/"
    print(f"      [2/5 LOCAL -> GCS] Uploading to {gcs_dest}...", flush=True)
    upload_cmd = f'gcloud storage cp --recursive "{local_dir}" "gs://{bucket}/{schema_lower}/"'
    upload_res = subprocess.run(upload_cmd, shell=True, capture_output=True, text=True)
    if upload_res.returncode != 0:
        raise RuntimeError(f"GCS upload failed for {tbl}: {upload_res.stderr}")

    # 4. Check & Verify GCS landing
    print(f"      [3/5 VERIFY GCS] Checking Parquet objects at {gcs_dest}...", flush=True)
    verified, files = check_gcs_landing(bucket, schema_lower, tbl_lower)
    if not verified:
        raise RuntimeError(f"GCS verification failed for {tbl}: {files}")
    print(f"      [VERIFIED] Found {len(files)} Parquet file(s) in GCS.", flush=True)

    # 5. Delete Local Temporary Copy
    if not keep_local:
        print(f"      [4/5 LOCAL CLEANUP] Deleting local copy: {local_dir}...", flush=True)
        shutil.rmtree(local_dir, ignore_errors=True)
        # Prune empty parent schema directory
        parent_dir = os.path.dirname(local_dir)
        try:
            if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                os.rmdir(parent_dir)
        except Exception:
            pass
        print(f"      [LOCAL CLEANUP] Local copy deleted successfully.", flush=True)
    else:
        print(f"      [LOCAL KEPT] Local copy preserved (--keep-local).", flush=True)

    # 6. Purge Snowflake User Stage
    print(f"      [5/5 STAGE CLEANUP] Purging Snowflake stage {stage_name}/{tbl_lower}/...", flush=True)
    cur = conn.cursor()
    cur.execute(f"REMOVE {stage_name}/{tbl_lower}/;")
    cur.close()
    print(f"      [STAGE CLEANUP] Stage purged successfully.", flush=True)

    # 7. Update and persist state
    result["gcs_path"] = gcs_dest
    result["status"] = "COMPLETED"
    if "referencing_cubes" not in result:
        result["referencing_cubes"] = []
    if cube_name and cube_name not in result["referencing_cubes"]:
        result["referencing_cubes"].append(cube_name)
    state["tables"][tbl] = result

    # Immediately update progress and readiness for all referencing cubes
    for c_name, c_info in CUBE_REGISTRY.items():
        if tbl in c_info["tables"]:
            c_tables = c_info["tables"]
            c_completed = sum(1 for t in c_tables if state["tables"].get(t, {}).get("status") in ["COMPLETED", "COMPLETED_DRY_RUN"] and state["tables"].get(t, {}).get("gcs_path"))
            state["cubes"][c_name] = {
                "total_tables": len(c_tables),
                "completed_tables": c_completed,
                "percent_complete": round((c_completed / len(c_tables)) * 100, 1),
                "is_ready": (c_completed == len(c_tables)),
                "updated_at": datetime.datetime.now().isoformat()
            }

    save_state(state)
    print(f"      [SUCCESS] Table '{tbl}' migrated end-to-end.\n", flush=True)
    return result, False

def clean_local_verified_data():
    """
    Cleans up all local temporary data directories in data-recon/data/.
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(root_dir, "data")
    if not os.path.exists(data_dir):
        print("No local data cache found in data-recon/data/.")
        return
        
    freed_bytes = 0
    file_count = 0
    for root, dirs, files in os.walk(data_dir, topdown=False):
        for f in files:
            fp = os.path.join(root, f)
            freed_bytes += os.path.getsize(fp)
            os.remove(fp)
            file_count += 1
        if not os.listdir(root):
            try:
                os.rmdir(root)
            except Exception:
                pass
                
    print(f"[CLEANUP COMPLETE] Removed {file_count} local cached files ({freed_bytes / (1024*1024):.2f} MB freed).")

DIMENSION_TABLES_ORDERED = [
    "CNF__DIM_DIGITAL_PORTAL",
    "CNF__DIM_CLAIM_STATUS",
    "CNF__DIM_ADMIN_PRODUCT",
    "CNF__DIM_ANNUITY_PRODUCT",
    "CNF__DIM_INSURER",
    "CNF__DIM_CLAIM_TYPE",
    "CNF__DIM_SERVICE_OFFERING",
    "CNF__DIM_RISK_PRODUCT",
    "CNF__DIM_BROKER_CONSULTANT",
    "CNF__DIM_TRANSACTION_TYPE",
    "CNF__DIM_FUND",
    "CNF__DIM_REVISION_ASSOCIATION",
    "CNF__DIM_INVESTMENT_PRODUCT",
    "CNF__DIM_AGGREGATOR",
    "CNF__DIM_EMPLOYER",
    "CNF__DIM_CLIENT",
    "CNF__DIM_EMPLOYER_BRANCH",
    "CNF__DIM_PAYPOINT",
    "DIM_DATE",
    "CNF__DIM_DIGITAL_PORTAL_USER",
    "CNF__DIM_BANK_ACCOUNT",
    "CNF__DIM_BENEFICIARY",
    "CNF__DIM_MEMBER"
]

REMAINING_TABLES_UNDER_25GB = [
    "CNF__PROD_IN_FUND_EXIT_MEMBER_MONTHLY",
    "CNF__FACT_INV_MONTHLY_MARKET_VALUE",
    "CNF__FACT_ANNUITY_QUOTATIONS",
    "CNF__FACT_INVESTMENT_TRANSACTIONS",
    "CNF__FACT_IN_FUND_EXIT_MEMBER_AUM_MONTHLY",
    "CNF__FACT_MEMBER_CLAIMS",
    "CNF__FACT_DIGITAL_PORTAL_REGISTRATIONS",
    "CNF__FACT_IN_FUND_EXIT_MEMBER_AUA_MONTHLY",
    "CNF__AGG_DIGITAL_PORTAL_REGISTRATIONS_YTD",
    "CNF__FACT_MEMBER_CLAIM_PAYMENT",
    "CNF__AGG_DIGITAL_PORTAL_REGISTRATIONS_TD",
    "CNF__AGG_DIGITAL_PORTAL_EVENTS_YTD",
    "CNF__FACT_MEMBER_MONTHLY_FEES",
    "CNF__FACT_MEMBER_INVESTMENT_AUM",
    "CNF__FACT_DIGITAL_PORTAL_EVENTS",
    "CNF__FACT_MEMBER_INVESTMENT_AUA",
    "CNF__FACT_MEMBER_BASE_RISK_PREMIUM"
]

# 9 Remaining Tables to reach 100% cube readiness, ordered smallest to largest by 2024-2025 volume
REMAINING_TABLES_2024_2025 = [
    "CNF__FACT_MEMBER_MONTHLY_FEES",              # ~9.05M rows (2024-2025)
    "CNF__FACT_MEMBER_INVESTMENT_AUM",             # ~10.94M rows (2024-2025)
    "CNF__FACT_MEMBER_INVESTMENT_AUA",             # ~29.21M rows (2024-2025)
    "CNF__FACT_DIGITAL_PORTAL_EVENTS",             # ~39.41M rows (2024-2025)
    "CNF__FACT_MEMBER_BASE_CONTRIBUTION",          # ~32.72M rows (2024-2025)
    "CNF__FACT_MEMBER_SEGMENTATION",               # ~32.50M rows (2024-2025)
    "CNF__FACT_MEMBER_BASE_RISK_PREMIUM",          # ~35.49M rows (2024-2025)
    "CNF__FACT_MEMBER_TRANSACTIONS",               # ~156.87M rows (2024-2025)
    "CNF__AGG_CONSOLIDATED_MEMBER_MEASURES_MONTHLY"# ~212.50M rows (2024-2025)
]

# ── 6. Cube Migration Orchestration ──────────────────────────────────────────
def process_cube(cube_name, conn, database, stage_name, bucket, state, dry_run=False, keep_local=False):
    if cube_name not in CUBE_REGISTRY:
        print(f"Error: Unknown cube '{cube_name}'. Use --status to see available cubes.")
        return
    
    cube_info = CUBE_REGISTRY[cube_name]
    tables = cube_info["tables"]
    total_tables = len(tables)
    
    print(f"\n================================================================================")
    print(f" Processing Cube Delivery: {cube_name}")
    print(f" Description: {cube_info['description']}")
    print(f" Total Tables Required: {total_tables}")
    print(f"================================================================================")
    
    new_tables_migrated = 0
    reused_tables = 0
    
    for tbl in tables:
        date_filter = "DATE_SK >= 20240101 AND DATE_SK <= 20251231" if tbl in REMAINING_TABLES_2024_2025 else None
        result, was_reused = migrate_table_end_to_end(
            conn, database, tbl, stage_name, bucket, cube_name, state, dry_run, keep_local, date_filter=date_filter
        )
        if was_reused:
            reused_tables += 1
        elif result.get("status") in ["COMPLETED", "COMPLETED_DRY_RUN"]:
            new_tables_migrated += 1
            
    # Calculate cube completion status
    completed_count = sum(1 for t in tables if state["tables"].get(t, {}).get("status") in ["COMPLETED", "COMPLETED_DRY_RUN"] and state["tables"].get(t, {}).get("gcs_path"))
    pct = round((completed_count / total_tables) * 100, 1)
    is_ready = (completed_count == total_tables)
    
    state["cubes"][cube_name] = {
        "total_tables": total_tables,
        "completed_tables": completed_count,
        "percent_complete": pct,
        "is_ready": is_ready,
        "updated_at": datetime.datetime.now().isoformat()
    }
    save_state(state)
    
    status_str = "READY FOR REPORTING" if is_ready else f"IN PROGRESS ({pct}%)"
    print(f" Cube [{cube_name}] Status: {status_str} ({completed_count}/{total_tables} tables)")
    print(f"================================================================================\n")

# ── Status Dashboard ──────────────────────────────────────────────────────────
def show_status(state):
    print("\n" + "=" * 90)
    print("                    CUBE DELIVERY MIGRATION DASHBOARD")
    print("=" * 90)
    print(f"{'CUBE NAME':<40} | {'PROGRESS':>10} | {'PERCENT':>10} | {'READY?':>10}")
    print("-" * 90)
    
    for cube_name, info in CUBE_REGISTRY.items():
        cube_tables = info["tables"]
        total = len(cube_tables)
        completed = sum(1 for t in cube_tables if state["tables"].get(t, {}).get("status") in ["COMPLETED", "COMPLETED_DRY_RUN"] and state["tables"].get(t, {}).get("gcs_path"))
        pct = (completed / total) * 100
        ready = "[YES]" if completed == total else f"[{completed}/{total}]"
        print(f"{cube_name:<40} | {completed:>4}/{total:<4} | {pct:>9.1f}% | {ready:>10}")
        
    print("-" * 90)
    
    # Table summary
    total_unique_tables = len(set(t for c in CUBE_REGISTRY.values() for t in c["tables"]))
    tables_migrated = sum(1 for t in state["tables"].values() if t.get("status") in ["COMPLETED", "COMPLETED_DRY_RUN"] and t.get("gcs_path"))
    print(f"Distinct Tables Total: {total_unique_tables} | Migrated: {tables_migrated} | Remaining: {total_unique_tables - tables_migrated}")
    print("=" * 90 + "\n")

# ── Main Entrypoint ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Migrate Snowflake Cube Tables to Parquet with Deduplication (Option A End-to-End)")
    parser.add_argument("--remaining", action="store_true", help="Migrate all 9 remaining tables filtered to 2024 and 2025 ordered smallest to largest")
    parser.add_argument("--years", nargs="+", default=["2024", "2025"], help="Years to filter by (default: 2024 2025)")
    parser.add_argument("--dims", action="store_true", help="Migrate all 23 dimension tables (CNF__DIM_* and DIM_DATE) ordered smallest to largest")
    parser.add_argument("--under-25gb", action="store_true", help="Migrate all 17 tables < 25GB ordered smallest to largest")
    parser.add_argument("--only-unpartitioned", action="store_true", help="Filter out 'Queued (Partitioned)' tables, migrating only unpartitioned 'Queued' tables")
    parser.add_argument("--bucket", type=str, default="scbi-ducklake-myanalyticsproduct", help="Target GCS bucket name")
    parser.add_argument("--table", type=str, help="Name of specific single table to migrate end-to-end")
    parser.add_argument("--cube", type=str, help="Name of specific cube to migrate end-to-end")
    parser.add_argument("--all", action="store_true", help="Migrate all cubes in priority sequence end-to-end")
    parser.add_argument("--status", action="store_true", help="Show migration status dashboard across all cubes")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without running COPY INTO")
    parser.add_argument("--keep-local", action="store_true", help="Keep local parquet copies instead of deleting after GCS check")
    parser.add_argument("--clean-local", action="store_true", help="Delete all local parquet copies in data-recon/data/ to free disk space")
    parser.add_argument("--stage", type=str, default="@~/parquet_migration", help="Snowflake Stage name (default: @~/parquet_migration)")
    parser.add_argument("--warehouse", type=str, default="SC_BI_PRODUCT_PPE_WH", help="Snowflake Warehouse")
    parser.add_argument("--database", type=str, default="SC_BI_PRODUCT_PPE", help="Snowflake Database")
    parser.add_argument("--reset-state", action="store_true", help="Reset local migration state tracking")
    
    args = parser.parse_args()
    
    if args.reset_state:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        print("State reset complete.")
        return
        
    if args.clean_local:
        clean_local_verified_data()
        return
        
    state = load_state()
    
    if args.status:
        show_status(state)
        return
        
    if not args.cube and not args.all and not args.table and not args.dims and not args.under_25gb and not args.only_unpartitioned and not args.remaining:
        show_status(state)
        print("Tip: Run with --remaining, --under-25gb, --only-unpartitioned, --dims, --table <name>, --cube <name>, or --all to execute migrations. Use --dry-run to test.")
        return
        
    conn = None
    if not args.dry_run:
        conn = get_snowflake_connection(args.warehouse, args.database)
        
    date_filter_expr = None
    if args.years:
        years_int = [int(y) for y in args.years]
        min_yr = min(years_int)
        max_yr = max(years_int)
        date_filter_expr = f"DATE_SK >= {min_yr}0101 AND DATE_SK <= {max_yr}1231"
        
    try:
        if args.remaining:
            print(f"\n================================================================================")
            print(f" Starting Remaining Tables Migration (Option A End-to-End: Smallest to Largest)")
            print(f" Scope: Filtered strictly to years {', '.join(args.years)} ({date_filter_expr})")
            print(f" Total Tables in Sequence: {len(REMAINING_TABLES_2024_2025)}")
            print(f" Target GCS Bucket: gs://{args.bucket}/")
            print(f" Policy: Each table is unloaded, downloaded, GCS-uploaded, verified, local deleted, stage purged before next table.")
            print(f"================================================================================")
            for idx, tbl in enumerate(REMAINING_TABLES_2024_2025, 1):
                print(f"[{idx}/{len(REMAINING_TABLES_2024_2025)}] Processing: {tbl}")
                migrate_table_end_to_end(
                    conn, args.database, tbl, args.stage, args.bucket, "remaining_2024_2025", state, args.dry_run, args.keep_local, date_filter=date_filter_expr
                )
            show_status(state)
        elif args.under_25gb or args.only_unpartitioned:
            if args.only_unpartitioned:
                sequence_tables = [t for t in REMAINING_TABLES_UNDER_25GB if t not in PARTITIONED_FACTS]
                print(f"\n================================================================================")
                print(f" Starting Unpartitioned Tables Migration (Option A End-to-End: Smallest to Largest)")
                print(f" Filter Policy: Migrating only Status = 'Queued' (Excluded 'Queued (Partitioned)')")
            else:
                sequence_tables = REMAINING_TABLES_UNDER_25GB
                print(f"\n================================================================================")
                print(f" Starting Tables < 25GB Migration Sequence (Option A End-to-End: Smallest to Largest)")
                print(f" Policy: Each table is unloaded, downloaded, GCS-uploaded, verified, local deleted, stage purged before next table.")
            
            print(f" Total Tables in Sequence: {len(sequence_tables)}")
            print(f" Target GCS Bucket: gs://{args.bucket}/")
            print(f"================================================================================")
            for idx, tbl in enumerate(sequence_tables, 1):
                print(f"[{idx}/{len(sequence_tables)}] Processing: {tbl}")
                migrate_table_end_to_end(
                    conn, args.database, tbl, args.stage, args.bucket, "under_25gb_migration", state, args.dry_run, args.keep_local
                )
            show_status(state)
        elif args.dims:
            print(f"\n================================================================================")
            print(f" Starting Dimension Migration Sequence (Option A End-to-End: Smallest to Largest)")
            print(f" Total Dimension Tables: {len(DIMENSION_TABLES_ORDERED)}")
            print(f" Target GCS Bucket: gs://{args.bucket}/")
            print(f" Policy: Each table is unloaded, downloaded, GCS-uploaded, verified, local deleted, stage purged before next table.")
            print(f"================================================================================")
            for idx, tbl in enumerate(DIMENSION_TABLES_ORDERED, 1):
                print(f"[{idx}/{len(DIMENSION_TABLES_ORDERED)}] Processing: {tbl}")
                migrate_table_end_to_end(
                    conn, args.database, tbl, args.stage, args.bucket, "dimension_migration", state, args.dry_run, args.keep_local
                )
            show_status(state)
        elif args.table:
            tbl = args.table.upper()
            date_filter = date_filter_expr if tbl in REMAINING_TABLES_2024_2025 else None
            print(f"\n================================================================================")
            print(f" Processing Single Table Migration (Option A End-to-End): {tbl}")
            if date_filter:
                print(f" Filter Applied: {date_filter}")
            print(f"================================================================================")
            migrate_table_end_to_end(
                conn, args.database, tbl, args.stage, args.bucket, "standalone_table", state, args.dry_run, args.keep_local, date_filter=date_filter
            )
            show_status(state)
        elif args.cube:
            process_cube(args.cube, conn, args.database, args.stage, args.bucket, state, args.dry_run, args.keep_local)
            show_status(state)
        elif args.all:
            order = [
                "fund_analytics_monthly_metrics",
                "member_monthly",
                "member_transactions",
                "assetflows_member_monthly",
                "digital_portal",
                "digital_portal_events",
                "digital_portal_registrations",
                "aggregated_digital_portal_registrations",
                "annuity_quotation",
                "in_fund_exit_member_monthly",
                "investments_fundamental",
                "member_monthly_investment"
            ]
            for c in order:
                process_cube(c, conn, args.database, args.stage, args.bucket, state, args.dry_run, args.keep_local)
                
            show_status(state)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
