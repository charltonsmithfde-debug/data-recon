"""
Test suite for Ticket V2-3.3: Downstream BI DirectQuery & Metabase Rewiring

Verifies all 4 Acceptance Criteria:
1. Metabase database connection configured to query `scbi-cube-sql:5432` via internal VPC peering with scrypt-authenticated service credentials.
2. Power BI DirectQuery connection procedure verified over `gcloud compute start-iap-tunnel scbi-cube-sql 5432`.
3. Validates that analytical BI queries resolve against Cube semantic models without bypass.
4. Generates step-by-step connection guide in `docs/METABASE_CUBE_SQL.md`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
METABASE_DIR = PROJECT_ROOT / "version-two" / "metabase"
CUBE_DIR = PROJECT_ROOT / "version-two" / "cube"
GUIDE_PATH = PROJECT_ROOT / "docs" / "METABASE_CUBE_SQL.md"


def _load_metabase_setup():
    if str(METABASE_DIR) not in sys.path:
        sys.path.insert(0, str(METABASE_DIR))
    spec = importlib.util.spec_from_file_location("setup", METABASE_DIR / "setup.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["setup"] = mod
    spec.loader.exec_module(mod)
    return mod


setup_mod = _load_metabase_setup()


class TestV233DownstreamBiRewire(unittest.TestCase):
    """Validates V2-3.3 Metabase & Power BI DirectQuery rewiring to Cube SQL API (port 5432)."""

    def test_ac1_metabase_connection_targets_cube_sql_5432_and_blocks_bypass(self) -> None:
        """AC 1: Metabase database connection configured to query scbi-cube-sql:5432 with scrypt service credentials."""
        ds = setup_mod.build_metabase_cube_sql_datasource()
        self.assertEqual(ds["engine"], "postgres")
        self.assertEqual(ds["details"]["host"], "scbi-cube-sql")
        self.assertEqual(ds["details"]["port"], 5432)
        self.assertEqual(ds["details"]["dbname"], "cube")
        self.assertEqual(ds["governance"]["auth_mechanism"], "checkSqlAuth_scrypt")
        self.assertFalse(ds["governance"]["direct_storage_bypass"])

        # Attempting to configure direct DuckDB, Snowflake, or Cloud SQL port 5433 must raise BiBypassViolationError
        with self.assertRaises(setup_mod.BiBypassViolationError):
            setup_mod.validate_no_storage_bypass({"engine": "duckdb", "details": {"host": "local"}})

        with self.assertRaises(setup_mod.BiBypassViolationError):
            setup_mod.validate_no_storage_bypass(
                {"engine": "postgres", "details": {"host": "127.0.0.1", "port": 5433, "dbname": "ducklake_catalog"}}
            )

        with self.assertRaises(setup_mod.BiBypassViolationError):
            setup_mod.validate_no_storage_bypass(
                {"engine": "postgres", "details": {"host": "scbi-ducklake-catalog", "port": 5432, "dbname": "cube"}}
            )

    def test_ac2_powerbi_directquery_iap_tunnel_procedure_and_postgres_ssl_handshake(self) -> None:
        """AC 2: Power BI DirectQuery connection procedure verified over gcloud compute start-iap-tunnel scbi-cube-sql 5432."""
        tunnel = setup_mod.build_powerbi_iap_tunnel_command()
        self.assertIn("gcloud compute start-iap-tunnel scbi-cube-sql 5432", tunnel["command"])
        self.assertIn("--local-host-port=localhost:5432", tunnel["command"])
        self.assertEqual(tunnel["powerbi_connector"], "PostgreSQL database (DirectQuery)")
        self.assertEqual(tunnel["powerbi_server"], "localhost:5432")
        self.assertEqual(tunnel["powerbi_database"], "cube")

    def test_ac3_sql_api_resolves_semantic_models_and_prohibits_bypass(self) -> None:
        """AC 3: Validates that analytical BI queries resolve against Cube semantic models without bypass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = str(Path(tmpdir) / "bi_sql_catalog.db")
            node_runner = f"""
const cube = require({json.dumps(str(CUBE_DIR / "cube.js"))});
(async () => {{
  const srv = await cube.startCubeSqlServer({{
    sqlPort: 0,
    catalogDbPath: {json.dumps(catalog_path)}
  }});
  console.log(JSON.stringify({{ port: srv.port }}));
  process.stdin.resume();
  process.stdin.on('data', async () => {{
    await srv.close();
    process.exit(0);
  }});
}})();
"""
            proc = subprocess.Popen(
                ["node", "-e", node_runner],
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert proc.stdout is not None
                line = proc.stdout.readline().strip()
                sql_port = int(json.loads(line)["port"])

                client = setup_mod.CubeSqlWireClient(
                    host="127.0.0.1",
                    port=sql_port,
                    user="cube_audit_compliance",
                    password="scbi_audit_v2_pass",
                )

                # 1. Verify Postgres SSLRequest wire handshake returns 'N'
                ssl_reply = client.negotiate_postgres_ssl()
                self.assertEqual(ssl_reply, "N")

                # 2. Verify schema reflection exposes governed semantic Cubes
                tables = client.reflect_tables()
                table_names = {t["table_name"] for t in tables}
                self.assertIn("AnnuityQuotation", table_names)
                self.assertIn("InvestmentAnalysis", table_names)
                self.assertIn("MemberAnalysis", table_names)
                self.assertIn("SharedDimensions", table_names)

                # 3. Verify analytical BI query against AnnuityQuotation and MemberAnalysis
                annuity_res = client.execute_sql("SELECT quotationCount, averageCommissionRate FROM AnnuityQuotation")
                self.assertEqual(annuity_res["status"], "OK")
                self.assertEqual(annuity_res["rows"][0]["AnnuityQuotation.quotationCount"], 129954)
                self.assertAlmostEqual(annuity_res["rows"][0]["AnnuityQuotation.averageCommissionRate"], 2.75)

                member_res = client.execute_sql("SELECT activeMemberCount, totalAua, id_number FROM MemberAnalysis")
                self.assertEqual(member_res["status"], "OK")
                self.assertEqual(member_res["rows"][0]["MemberAnalysis.activeMemberCount"], 29209326)
                # Audit compliance role has canViewPii=false -> id_number is masked with sha256
                self.assertIn("sha256(", member_res["compiledDimensions"]["MemberAnalysis.id_number"])

                # 4. Verify direct bypass query to raw storage/catalog tables is blocked with 403
                bypass_res = client.execute_sql("SELECT * FROM scbi_cdp_mart.cnf__fact_annuity_quotations")
                self.assertEqual(bypass_res["status"], "ERROR")
                self.assertEqual(bypass_res["code"], 403)
                self.assertIn("prohibited on Cube SQL API", bypass_res["error"])

                # 5. Verify forged scrypt password is rejected
                bad_client = setup_mod.CubeSqlWireClient(
                    host="127.0.0.1",
                    port=sql_port,
                    user="cube_audit_compliance",
                    password="forged_wrong_password",
                )
                bad_res = bad_client.execute_sql("SELECT 1")
                self.assertEqual(bad_res["status"], "ERROR")
                self.assertEqual(bad_res["code"], 403)
            finally:
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    if pipe:
                        try:
                            pipe.close()
                        except OSError:
                            pass
                proc.terminate()
                proc.wait(timeout=5)

    def test_ac4_metabase_cube_sql_guide_completeness(self) -> None:
        """AC 4: Generates step-by-step connection guide in docs/METABASE_CUBE_SQL.md."""
        self.assertTrue(GUIDE_PATH.exists(), f"Missing {GUIDE_PATH}")
        content = GUIDE_PATH.read_text(encoding="utf-8")

        self.assertIn("scbi-cube-sql", content)
        self.assertIn("5432", content)
        self.assertIn("gcloud compute start-iap-tunnel scbi-cube-sql 5432", content)
        self.assertIn("DirectQuery", content)
        self.assertIn("AnnuityQuotation", content)
        self.assertIn("MemberAnalysis", content)


if __name__ == "__main__":
    unittest.main()
