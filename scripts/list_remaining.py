import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_cube_data_to_parquet import CUBE_REGISTRY, get_table_schema

state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migration_state.json")
with open(state_file, "r") as f:
    state = json.load(f)

completed = set(state.get("tables", {}).keys())
all_tables = set(t for c in CUBE_REGISTRY.values() for t in c["tables"])
remaining = all_tables - completed

metrics_file = r"C:\Users\G988557\.gemini\antigravity-ide\brain\cf53bf97-9171-42ee-b0f3-92a7c15c5c07\scratch\all_cubes_metrics.json"
table_sizes = {}
if os.path.exists(metrics_file):
    with open(metrics_file, "r") as f:
        metrics = json.load(f)
    for tname, tinfo in metrics.get("table_metrics", {}).items():
        b = tinfo.get("BYTES") or 0
        table_sizes[tname] = {
            "rows": tinfo.get("ROW_COUNT") or 0,
            "bytes": b,
            "mb": (tinfo.get("SIZE_MB") or 0.0),
            "gb": (tinfo.get("SIZE_GB") or 0.0)
        }

sorted_rem = sorted(remaining, key=lambda x: (table_sizes.get(x, {}).get("bytes") or 0))

print("=" * 100)
print(f"REMAINING TABLES TO MIGRATE ({len(sorted_rem)} Total) - Sorted Ascending by Size")
print("=" * 100)
print(f"{'#':<3} | {'SCHEMA':<18} | {'TABLE NAME':<46} | {'ROWS':>13} | {'SIZE (MB)':>10} | {'SIZE (GB)':>9} | {'< 25GB?'}")
print("-" * 100)

under_25gb = []
over_25gb = []

for idx, t in enumerate(sorted_rem, 1):
    schema = get_table_schema(t)
    info = table_sizes.get(t, {})
    rows = info.get("rows", 0)
    mb = info.get("mb", 0.0)
    gb = info.get("gb", 0.0)
    is_under = gb < 25.0
    if is_under:
        under_25gb.append(t)
    else:
        over_25gb.append(t)
    flag = "[YES]" if is_under else "[NO - >= 25GB]"
    print(f"{idx:<3} | {schema:<18} | {t:<46} | {rows:>13,} | {mb:>10.2f} | {gb:>9.2f} | {flag}")

print("-" * 100)
print(f"Tables < 25 GB  : {len(under_25gb)} tables ({sum(table_sizes.get(t, {}).get('gb', 0) for t in under_25gb):.2f} GB)")
print(f"Tables >= 25 GB : {len(over_25gb)} tables ({sum(table_sizes.get(t, {}).get('gb', 0) for t in over_25gb):.2f} GB)")
print("=" * 100)
