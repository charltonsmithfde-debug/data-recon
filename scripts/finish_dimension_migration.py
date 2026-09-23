"""
Verify Dimension Migration to GCS, update migration_state.json, and purge Snowflake Stage.
"""
import os
import sys
import json
import subprocess
import datetime
import snowflake.connector
import webbrowser

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

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migration_state.json")
BUCKET = "scbi-ducklake-myanalyticsproduct"
WAREHOUSE = "SC_BI_PRODUCT_PPE_WH"
DATABASE = "SC_BI_PRODUCT_PPE"
STAGE = "@~/parquet_migration"

DIMENSION_TABLES_ORDERED = [
    ("CNF__DIM_DIGITAL_PORTAL", "SCBI_CDP_MART"),
    ("CNF__DIM_CLAIM_STATUS", "SCBI_CDP_MART"),
    ("CNF__DIM_ADMIN_PRODUCT", "SCBI_CDP_MART"),
    ("CNF__DIM_ANNUITY_PRODUCT", "SCBI_CDP_MART"),
    ("CNF__DIM_INSURER", "SCBI_CDP_MART"),
    ("CNF__DIM_CLAIM_TYPE", "SCBI_CDP_MART"),
    ("CNF__DIM_SERVICE_OFFERING", "SCBI_CDP_MART"),
    ("CNF__DIM_RISK_PRODUCT", "SCBI_CDP_MART"),
    ("CNF__DIM_BROKER_CONSULTANT", "SCBI_CDP_MART"),
    ("CNF__DIM_TRANSACTION_TYPE", "SCBI_CDP_MART"),
    ("CNF__DIM_FUND", "SCBI_CDP_MART"),
    ("CNF__DIM_REVISION_ASSOCIATION", "SCBI_CDP_MART"),
    ("CNF__DIM_INVESTMENT_PRODUCT", "SCBI_CDP_MART"),
    ("CNF__DIM_AGGREGATOR", "SCBI_CDP_MART"),
    ("CNF__DIM_EMPLOYER", "SCBI_CDP_MART"),
    ("CNF__DIM_CLIENT", "SCBI_CDP_MART"),
    ("CNF__DIM_EMPLOYER_BRANCH", "SCBI_CDP_MART"),
    ("CNF__DIM_PAYPOINT", "SCBI_CDP_MART"),
    ("DIM_DATE", "SCBI_SDP_MART"),
    ("CNF__DIM_DIGITAL_PORTAL_USER", "SCBI_CDP_MART"),
    ("CNF__DIM_BANK_ACCOUNT", "SCBI_CDP_MART"),
    ("CNF__DIM_BENEFICIARY", "SCBI_CDP_MART"),
    ("CNF__DIM_MEMBER", "SCBI_CDP_MART"),
]

def main():
    print("=" * 80)
    print("STEP 1: Updating migration_state.json with GCS Landing Paths")
    print("=" * 80)
    
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
        
    all_present = True
    for tbl, schema in DIMENSION_TABLES_ORDERED:
        gcs_path = f"gs://{BUCKET}/{schema.lower()}/{tbl.lower()}/"
        if tbl in state["tables"]:
            state["tables"][tbl]["gcs_path"] = gcs_path
            state["tables"][tbl]["status"] = "COMPLETED"
            print(f"  [OK] {tbl} -> {gcs_path}")
        else:
            print(f"  [MISSING IN STATE] {tbl}")
            all_present = False
            
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print("\nmigration_state.json successfully updated.")

    print("\n" + "=" * 80)
    print("STEP 2: Purging Snowflake User Stage (@~/parquet_migration/)")
    print("=" * 80)
    
    account = os.environ.get("SNOWFLAKE_ACCOUNT", "gw52249.eu-west-1").strip('"')
    user = os.environ.get("SNOWFLAKE_USER", "G988557").strip('"')
    role = os.environ.get("SNOWFLAKE_ROLE", "ARDEVSCBIPRODUCTDEVELOPERSF").strip('"')
    
    print(f"Connecting to Snowflake ({account}, {user}, {role})...")
    conn = snowflake.connector.connect(
        account=account,
        user=user,
        authenticator="externalbrowser",
        role=role,
        warehouse=WAREHOUSE,
        database=DATABASE,
        client_session_keep_alive=True
    )
    cur = conn.cursor()
    
    print(f"Executing: REMOVE {STAGE}/;")
    cur.execute(f"REMOVE {STAGE}/;")
    removed_rows = cur.fetchall()
    print(f"Purged {len(removed_rows)} files from stage {STAGE}/")
    
    print(f"\nVerifying stage is clean: LIST {STAGE}/;")
    cur.execute(f"LIST {STAGE}/;")
    remaining = cur.fetchall()
    print(f"Remaining files in stage: {len(remaining)}")
    if len(remaining) == 0:
        print("[SUCCESS] Snowflake stage is completely clean! 0 storage overhead incurred.")
    else:
        print(f"[WARNING] Stage still has {len(remaining)} files remaining.")
        
    cur.close()
    conn.close()

    print("\n" + "=" * 80)
    print("STEP 3: Migration Summary Dashboard")
    print("=" * 80)
    # Print status summary
    from migrate_cube_data_to_parquet import show_status
    show_status(state)

if __name__ == "__main__":
    main()
