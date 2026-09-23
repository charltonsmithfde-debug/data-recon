"""
pbi_to_ducklake_transpiler.py

Automated transpiler that reads SAP HANA -> Power BI migration models from
pbi-scbi and generates:
  1. DuckDB external views over GCS Parquet (gs://scbi-ducklake-myanalyticsproduct/)
  2. Cube.js semantic model definitions (*.js)
  3. Catalog metadata for the Sanlam Online branded web application
"""

import os
import re
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PBI_DIR = BASE_DIR / "pbi-scbi" / "semantic_models"
CUBES_SPEC_DIR = PBI_DIR / "cubes"
USE_CASE_DIR = PBI_DIR / "use-case"

OUT_VIEWS_DIR = BASE_DIR / "data-recon" / "scripts" / "views"
OUT_CUBEJS_DIR = BASE_DIR / "data-recon" / "cube" / "model" / "cubes"
OUT_WEB_DIR = BASE_DIR / "data-recon" / "web"

GCS_BUCKET = "scbi-ducklake-myanalyticsproduct"

# All 12 Cubes & their canonical slugs
ALL_CUBES = [
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

def slug_to_pascal(slug):
    return "".join(part.capitalize() for part in slug.split("_"))

def parse_markdown_cube(md_path):
    """Extracts tables, relationships, and measures from a cube markdown spec."""
    if not os.path.exists(md_path):
        return None
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    cube_data = {
        "title": "",
        "central_facts": [],
        "dimensions": [],
        "relationships": [],
        "measures": []
    }

    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if title_match:
        cube_data["title"] = title_match.group(1).strip()

    # Extract central fact
    fact_matches = re.findall(r"`(CNF__FACT_[A-Z0-9_]+|CNF__AGG_[A-Z0-9_]+|CNF__PROD_[A-Z0-9_]+)`", text)
    if fact_matches:
        cube_data["central_facts"] = list(dict.fromkeys(fact_matches))

    # Extract table mapping table
    table_rows = re.findall(r"\|\s*`([^`]+)`\s*\|\s*`?(CNF__[A-Z0-9_]+|DIM_DATE)`?\s*\|\s*([A-Z_]+)\s*\|\s*([A-Za-z0-9_\s]+)\s*\|", text)
    for row in table_rows:
        src, tbl, schema, t_type = row
        if "DIM" in tbl or "Dimension" in t_type:
            cube_data["dimensions"].append({"table": tbl, "schema": schema, "source": src})

    # Extract relationships
    rel_rows = re.findall(r"\|\s*`([A-Z0-9_]+)`\s*\|\s*`([A-Z0-9_]+)`\s*\|\s*`([A-Z0-9_]+)`\s*\|\s*`([A-Z0-9_]+)`\s*\|\s*([^\s|]+)\s*\|\s*(\*\*Yes\*\*|Yes|No)\s*\|", text)
    for r in rel_rows:
        from_tbl, from_col, to_tbl, to_col, card, active = r
        cube_data["relationships"].append({
            "from_table": from_tbl,
            "from_col": from_col,
            "to_table": to_tbl,
            "to_col": to_col,
            "cardinality": card,
            "is_active": "Yes" in active
        })

    # Extract measures from markdown tables
    measure_rows = re.findall(r"\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*`([^`\n]+)`\s*\|\s*`([^`\n]+)`\s*\|", text)
    for m in measure_rows:
        hana_meas, dax_name, dax_expr, fmt = m
        if "DAX Name" in dax_name or "---" in dax_name:
            continue
        cube_data["measures"].append({
            "hana_name": hana_meas.strip(),
            "name": dax_name.strip(),
            "dax": dax_expr.strip(),
            "format": fmt.strip()
        })

    return cube_data

def transpile_dax_to_sql(dax_expr):
    """Converts common DAX patterns to ANSI/DuckDB SQL and Cube.js expressions."""
    dax = dax_expr.strip()

    # SUM(Table[Col]) -> SUM(Col)
    sum_m = re.match(r"^SUM\([A-Z0-9_]+\[([A-Z0-9_]+)\]\)$", dax, re.IGNORECASE)
    if sum_m:
        col = sum_m.group(1)
        return f"SUM({col})", "sum", col

    # DISTINCTCOUNT(Table[Col]) -> COUNT(DISTINCT Col)
    dc_m = re.match(r"^DISTINCTCOUNT\([A-Z0-9_]+\[([A-Z0-9_]+)\]\)$", dax, re.IGNORECASE)
    if dc_m:
        col = dc_m.group(1)
        return f"COUNT(DISTINCT {col})", "countDistinct", col

    # CALCULATE(SUM(Table[Col]), Table[FilterCol] = "val")
    calc_m = re.match(r"^CALCULATE\(SUM\([A-Z0-9_]+\[([A-Z0-9_]+)\]\),\s*[A-Z0-9_]+\[([A-Z0-9_]+)\]\s*(=|<>)\s*\"([^\"]+)\"\)$", dax, re.IGNORECASE)
    if calc_m:
        col, f_col, op, val = calc_m.groups()
        sql_op = "=" if op == "=" else "<>"
        return f"SUM(CASE WHEN {f_col} {sql_op} '{val}' THEN {col} ELSE 0 END)", "sum", col

    # TOTALYTD([Measure], DIM_DATE[DATE_NK])
    ytd_m = re.match(r"^TOTALYTD\(\[([^\]]+)\],\s*DIM_DATE\[DATE_NK\]\)$", dax, re.IGNORECASE)
    if ytd_m:
        meas = ytd_m.group(1)
        return f"SUM({meas})", "ytd", meas

    # Default fallback
    clean_expr = re.sub(r"[A-Z0-9_]+\[([A-Z0-9_]+)\]", r"\1", dax)
    return clean_expr, "number", None

def generate_duckdb_views():
    """Creates create_duckdb_views.sql for all 44 tables in GCS."""
    from migrate_cube_data_to_parquet import CUBE_REGISTRY, get_table_schema
    all_tables = sorted(list(set(t for c in CUBE_REGISTRY.values() for t in c["tables"])))

    ddl_lines = [
        "-- Auto-generated DuckDB External Views over GCS Parquet",
        "-- Bucket: gs://scbi-ducklake-myanalyticsproduct/",
        "-- Total Tables: 44 conformed facts, aggregations, and dimensions",
        "",
        "INSTALL httpfs;",
        "LOAD httpfs;",
        "",
        "CREATE SCHEMA IF NOT EXISTS scbi_cdp_mart;",
        "CREATE SCHEMA IF NOT EXISTS scbi_sdp_mart;",
        "CREATE SCHEMA IF NOT EXISTS scbi_cdp_product;",
        ""
    ]

    for tbl in all_tables:
        schema = get_table_schema(tbl).lower()
        tbl_l = tbl.lower()
        gcs_uri = f"gs://{GCS_BUCKET}/{schema}/{tbl_l}/*.parquet"
        ddl = f"CREATE OR REPLACE VIEW {schema}.{tbl_l} AS SELECT * FROM read_parquet('{gcs_uri}');"
        ddl_lines.append(ddl)

    return "\n".join(ddl_lines)

def generate_cubejs_model(cube_slug, cube_data):
    """Generates a Cube.js JavaScript file for a given cube."""
    pascal_name = slug_to_pascal(cube_slug)
    facts = cube_data.get("central_facts", [])
    primary_fact = facts[0] if facts else f"CNF__FACT_{cube_slug.upper()}"
    schema = "scbi_cdp_mart"
    if "PROD" in primary_fact:
        schema = "scbi_cdp_product"
    elif primary_fact == "DIM_DATE":
        schema = "scbi_sdp_mart"

    measures_js = []
    for idx, m in enumerate(cube_data.get("measures", [])):
        meas_id = re.sub(r"[^a-zA-Z0-9_]", "", m["name"].replace(" ", ""))
        meas_id = meas_id[0].lower() + meas_id[1:] if meas_id else f"measure{idx}"
        sql_expr, m_type, col = transpile_dax_to_sql(m["dax"])
        
        type_str = "sum" if m_type in ["sum", "ytd"] else "countDistinct" if m_type == "countDistinct" else "number"
        format_str = "currency" if "0.00" in m["format"] or "$" in m["format"] or "Price" in m["name"] or "Payment" in m["name"] else "number"

        measures_js.append(f"""    {meas_id}: {{
      title: `{m['name']}`,
      sql: `${{CUBE}}.{col if col else 'DATE_SK'}`,
      type: `{type_str}`,
      format: `{format_str}`
    }}""")

    if not measures_js:
        measures_js.append("""    totalRecords: {
      title: `Total Records`,
      type: `count`
    }""")

    joins_js = [
        f"""    DimDate: {{
      sql: `${{CUBE}}.DATE_SK = ${{DimDate}}.DATE_SK`,
      relationship: `manyToOne`
    }}"""
    ]

    for rel in cube_data.get("relationships", []):
        if rel["is_active"] and rel["to_table"] != "DIM_DATE":
            target_alias = slug_to_pascal(rel["to_table"].replace("CNF__", "").lower())
            joins_js.append(f"""    {target_alias}: {{
      sql: `${{CUBE}}.{rel['from_col']} = ${{{target_alias}}}.{rel['to_col']}`,
      relationship: `manyToOne`
    }}""")

    cube_code = f"""/**
 * Cube.js Semantic Schema: {pascal_name}
 * Auto-transpiled from pbi-scbi / {cube_slug}.md
 */

cube(`{pascal_name}`, {{
  sql: `SELECT * FROM {schema}.{primary_fact.lower()}`,

  joins: {{
{',\n'.join(joins_js)}
  }},

  measures: {{
{',\n'.join(measures_js)}
  }},

  dimensions: {{
    dateSk: {{
      sql: `${{CUBE}}.DATE_SK`,
      type: `number`,
      primaryKey: false
    }},
    dateNk: {{
      sql: `${{CUBE}}.DATE_NK`,
      type: `time`
    }}
  }}
}});
"""
    return cube_code

def main():
    print("=" * 80)
    print(" Starting pbi-scbi Semantic Models & Reports Transpiler")
    print(" Target: DuckLake, DuckDB, Cube.js, and Sanlam Online Web Portal")
    print("=" * 80)

    OUT_VIEWS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_CUBEJS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_WEB_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Generate DuckDB Views
    views_sql = generate_duckdb_views()
    views_file = OUT_VIEWS_DIR / "create_duckdb_views.sql"
    with open(views_file, "w", encoding="utf-8") as f:
        f.write(views_sql)
    print(f" [1/3] Generated DuckDB External Views: {views_file} (44 tables)")

    # 2. Parse all Cubes and Reports
    catalog = {}
    cube_count = 0
    for slug in ALL_CUBES:
        md_file = CUBES_SPEC_DIR / f"{slug}.md"
        cube_data = parse_markdown_cube(md_file)
        if not cube_data:
            cube_data = {
                "title": slug_to_pascal(slug),
                "central_facts": [f"CNF__FACT_{slug.upper()}"],
                "measures": []
            }

        # Check for report file
        rep_file = CUBES_SPEC_DIR / f"{slug}_report.md"
        report_visuals = []
        if os.path.exists(rep_file):
            with open(rep_file, "r", encoding="utf-8") as f:
                rep_text = f.read()
                cards = re.findall(r"###\s+([^\n]+)\n([^#]+)", rep_text)
                for c_title, c_body in cards:
                    report_visuals.append({"title": c_title.strip(), "description": c_body.strip()[:200]})

        cube_data["report_visuals"] = report_visuals
        catalog[slug] = cube_data

        # Generate Cube.js file
        js_code = generate_cubejs_model(slug, cube_data)
        out_js = OUT_CUBEJS_DIR / f"{slug_to_pascal(slug)}.js"
        with open(out_js, "w", encoding="utf-8") as f:
            f.write(js_code)
        cube_count += 1

    print(f" [2/3] Generated Cube.js Models: {cube_count} files in {OUT_CUBEJS_DIR}")

    # 3. Output Web Catalog JSON
    catalog_path = OUT_WEB_DIR / "catalog.json"
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)
    print(f" [3/3] Generated Web Catalog JSON: {catalog_path}")

    print("=" * 80)
    print(" Transpilation Complete! Ready to assemble Sanlam Online Web Portal.")
    print("=" * 80)

if __name__ == "__main__":
    main()
