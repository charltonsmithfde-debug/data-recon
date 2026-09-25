"""
Automated Verification Suite for Ticket V2-2.1:
Cube.js 1.7.x Core Engine with Embedded DuckDB & DuckLake Extension

Compatible with both standard library `unittest` and `pytest`.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_TWO_DIR = PROJECT_ROOT / "version-two"
CUBE_DIR = VERSION_TWO_DIR / "cube"
PACKAGE_JSON_PATH = CUBE_DIR / "package.json"
CUBE_JS_PATH = CUBE_DIR / "cube.js"

if str(VERSION_TWO_DIR) not in sys.path:
    sys.path.insert(0, str(VERSION_TWO_DIR))

from ducklake.init_catalog import initialize_catalog


class TestV221CubeSemanticEngine(unittest.TestCase):
    """Test suite validating Cube.js 1.7.x embedded DuckDB & DuckLake engine (V2-2.1)."""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = tmp.name
        tmp.close()
        self.temp_db_url = f"sqlite:///{self.db_path}"
        initialize_catalog(db_url=self.temp_db_url)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_package_json_cube_1_7_and_duckdb_node_api(self):
        """AC1: Node package manifest installs Cube 1.7.x and @duckdb/node-api without deprecated deps."""
        self.assertTrue(PACKAGE_JSON_PATH.is_file(), "version-two/cube/package.json must exist")
        manifest = json.loads(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))

        deps = manifest.get("dependencies", {})
        dev_deps = manifest.get("devDependencies", {})

        self.assertIn("@cubejs-backend/server", deps)
        self.assertIn("@cubejs-backend/duckdb-driver", deps)
        self.assertIn("@cubejs-backend/postgres-driver", deps)
        self.assertIn("@duckdb/node-api", deps)

        self.assertTrue(deps["@cubejs-backend/server"].startswith("^1.7."))
        self.assertTrue(deps["@cubejs-backend/duckdb-driver"].startswith("^1.7."))
        self.assertTrue(deps["@cubejs-backend/postgres-driver"].startswith("^1.7."))
        self.assertTrue(dev_deps.get("@cubejs-backend/server-core", "").startswith("^1.7."))

        # Ensure zero legacy 0.35.x dependencies
        raw_text = PACKAGE_JSON_PATH.read_text(encoding="utf-8")
        self.assertNotIn("0.35", raw_text)

    def test_cube_js_initializes_duckdb_httpfs_and_ducklake(self):
        """AC2: cube.js initializes in-process DuckDB, installs/loads httpfs and ducklake at boot."""
        self.assertTrue(CUBE_JS_PATH.is_file(), "version-two/cube/cube.js must exist")
        content = CUBE_JS_PATH.read_text(encoding="utf-8")

        # Must not contain legacy s3:// read_parquet globbing views
        self.assertNotIn("read_parquet('s3://", content)

        # Must not contain hardcoded secrets
        forbidden_patterns = [
            r"GOOG1E[A-Za-z0-9]+",
            r"ScbiCubeSecretToken",
            r"a714a688c5d0d354fad31fa06c11531fe47ab43f37c479c8cce2372ebcac7281",
        ]
        for pat in forbidden_patterns:
            self.assertIsNone(re.search(pat, content), f"Forbidden secret pattern {pat} found")

        node_script = f"""
        const cube = require({json.dumps(str(CUBE_JS_PATH))});
        const sql = cube.buildDuckLakeInitSql({{
          DUCKLAKE_DB_URL: 'postgresql://ducklake_dev:secret@127.0.0.1:5433/ducklake_catalog',
          DUCKDB_MEMORY_LIMIT: '3.5GB'
        }});
        const driver = cube.driverFactory();
        console.log(JSON.stringify({{
          sql,
          engine: driver.engine,
          extensions: driver.extensionsLoaded,
          attachedCatalog: driver.attachedCatalog
        }}));
        """
        proc = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(proc.stdout.strip())

        self.assertEqual(payload["engine"], "@duckdb/node-api")
        self.assertEqual(payload["extensions"], ["httpfs", "ducklake"])
        self.assertEqual(payload["attachedCatalog"], "lake")
        self.assertIn("INSTALL httpfs;\nLOAD httpfs;", payload["sql"])
        self.assertIn("INSTALL ducklake;\nLOAD ducklake;", payload["sql"])
        self.assertIn(
            "ATTACH 'ducklake:postgres://ducklake_dev:secret@127.0.0.1:5433/ducklake_catalog' AS lake;",
            payload["sql"],
        )

    def test_driver_executes_annuity_quotations_count_query(self):
        """AC3: Executes SELECT count(*) FROM lake.scbi_cdp_mart.cnf__fact_annuity_quotations via Cube driver."""
        env = os.environ.copy()
        env["DUCKLAKE_DB_URL"] = self.temp_db_url

        proc = subprocess.run(
            [
                "node",
                str(CUBE_JS_PATH),
                "--verify-query",
                "SELECT count(*) FROM lake.scbi_cdp_mart.cnf__fact_annuity_quotations",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(proc.stdout.strip())

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["engine"], "@duckdb/node-api")
        self.assertEqual(result["attachedCatalog"], "lake")
        self.assertEqual(len(result["rows"]), 1)

        row = result["rows"][0]
        self.assertEqual(row["count(*)"], 129954)
        self.assertEqual(row["count"], 129954)
        self.assertEqual(row["version_id"], 1)
        self.assertTrue(
            row["file_uri"].endswith("scbi_cdp_mart/cnf__fact_annuity_quotations/*.parquet")
        )

    def test_server_starts_cleanly_on_port_4000_and_reports_healthy(self):
        """AC4: Server starts up cleanly on port 4000 locally and reports healthy status."""
        node_script = f"""
        const cube = require({json.dumps(str(CUBE_JS_PATH))});
        (async () => {{
          let instance;
          try {{
            instance = await cube.startCubeHttpServer({{
              port: 4000,
              catalogDbPath: {json.dumps(self.db_path)}
            }});
          }} catch (err) {{
            if (err && err.code === 'EADDRINUSE') {{
              instance = await cube.startCubeHttpServer({{
                port: 0,
                catalogDbPath: {json.dumps(self.db_path)}
              }});
            }} else {{
              throw err;
            }}
          }}
          try {{
            const healthRes = await fetch(`http://127.0.0.1:${{instance.port}}/readyz`);
            const healthJson = await healthRes.json();

            const queryRes = await fetch(`http://127.0.0.1:${{instance.port}}/cubejs-api/v1/driver-query`, {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{
                sql: 'SELECT count(*) FROM lake.scbi_cdp_mart.cnf__fact_annuity_quotations'
              }})
            }});
            const queryJson = await queryRes.json();

            console.log(JSON.stringify({{
              httpStatus: healthRes.status,
              health: healthJson,
              query: queryJson
            }}));
          }} finally {{
            await instance.close();
          }}
        }})().catch((e) => {{
          console.error(e);
          process.exit(1);
        }});
        """
        proc = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=True,
        )
        out = json.loads(proc.stdout.strip())

        self.assertEqual(out["httpStatus"], 200)
        self.assertEqual(out["health"]["status"], "HEALTHY")
        self.assertEqual(out["health"]["cubeVersion"], "1.7.x")
        self.assertEqual(out["health"]["engine"], "@duckdb/node-api")
        self.assertEqual(out["health"]["extensions"], ["httpfs", "ducklake"])
        self.assertEqual(out["health"]["attachedCatalog"], "lake")
        self.assertEqual(out["query"]["status"], "OK")
        self.assertEqual(out["query"]["data"][0]["count(*)"], 129954)


if __name__ == "__main__":
    unittest.main()
