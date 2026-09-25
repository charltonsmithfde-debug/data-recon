"""
Automated Verification Suite for Ticket V2-1.1:
Initialize DuckLake PostgreSQL Metadata Catalog

Compatible with both standard library `unittest` and `pytest`.
"""

import os
import re
import sys
import json
import tempfile
import unittest
from pathlib import Path

# Add version-two to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "version-two"))

from ducklake.init_catalog import (
    CatalogConnection,
    initialize_catalog,
    verify_catalog,
    DEFAULT_MIGRATION_STATE,
)


class TestV211CatalogInit(unittest.TestCase):
    """Test suite validating DuckLake Catalog initialization (V2-1.1)."""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = tmp.name
        tmp.close()
        self.temp_db_url = f"sqlite:///{self.db_path}"

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_schema_ddl_creation(self):
        """AC1: DDL script establishes snapshots, manifests, commits, and tables."""
        initialize_catalog(db_url=self.temp_db_url)

        with CatalogConnection(self.temp_db_url) as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            )
            tables = {row[0] for row in cur.fetchall()}

        expected_tables = {
            "ducklake_snapshots",
            "ducklake_tables",
            "ducklake_manifests",
            "ducklake_commits",
        }
        self.assertTrue(
            expected_tables.issubset(tables),
            f"Missing tables: {expected_tables - tables}",
        )

    def test_catalog_idempotency(self):
        """AC2: Running initialization multiple times is strictly idempotent."""
        res1 = initialize_catalog(db_url=self.temp_db_url)
        res2 = initialize_catalog(db_url=self.temp_db_url)
        res3 = initialize_catalog(db_url=self.temp_db_url)

        self.assertEqual(res1["tables_registered"], 44)
        self.assertEqual(res2["tables_registered"], 44)
        self.assertEqual(res3["tables_registered"], 44)
        self.assertEqual(res1["total_rows"], res3["total_rows"])

        with CatalogConnection(self.temp_db_url) as conn:
            snap_count = conn.execute("SELECT count(*) FROM ducklake_snapshots;").fetchone()[0]
            table_count = conn.execute("SELECT count(*) FROM ducklake_tables;").fetchone()[0]
            manifest_count = conn.execute("SELECT count(*) FROM ducklake_manifests;").fetchone()[0]
            commit_count = conn.execute("SELECT count(*) FROM ducklake_commits;").fetchone()[0]

        self.assertEqual(snap_count, 1)
        self.assertEqual(table_count, 44)
        self.assertEqual(manifest_count, 44)
        self.assertEqual(commit_count, 1)

    def test_all_44_mart_tables_registered(self):
        """AC3: Successfully registers initial table metadata for all 44 migrated mart tables."""
        initialize_catalog(db_url=self.temp_db_url)
        health = verify_catalog(db_url=self.temp_db_url)

        self.assertEqual(health["status"], "HEALTHY")
        self.assertEqual(health["tables_registered"], 44)
        self.assertEqual(health["manifests_registered"], 44)
        self.assertEqual(health["total_rows"], 647792599)
        self.assertEqual(health["total_bytes"], 47669105706)

        with open(DEFAULT_MIGRATION_STATE, "r", encoding="utf-8") as f:
            expected_state = json.load(f)["tables"]

        with CatalogConnection(self.temp_db_url) as conn:
            rows = conn.execute(
                "SELECT table_id, schema_name, table_name, gcs_prefix, row_count FROM ducklake_tables;"
            ).fetchall()
            registered = {r["table_name"].upper(): dict(r) for r in rows}

        self.assertEqual(len(registered), 44)
        self.assertEqual(len(expected_state), 44)
        for tbl_key, meta in expected_state.items():
            self.assertIn(tbl_key, registered)
            self.assertEqual(registered[tbl_key]["row_count"], meta["rows_unloaded"])
            self.assertTrue(
                registered[tbl_key]["gcs_prefix"].startswith("gs://scbi-ducklake-myanalyticsproduct/")
            )

    def test_active_snapshot_pointer_queryable(self):
        """AC4: Snapshot pointers are queryable via standard SQL join."""
        initialize_catalog(db_url=self.temp_db_url)

        with CatalogConnection(self.temp_db_url) as conn:
            row = conn.execute(
                """
                SELECT
                    t.table_id,
                    s.version_id,
                    s.status,
                    m.file_uri,
                    m.row_count
                FROM ducklake_tables t
                JOIN ducklake_snapshots s ON t.active_version = s.version_id
                JOIN ducklake_manifests m ON m.table_id = t.table_id AND m.version_id = s.version_id
                WHERE t.table_name = 'cnf__fact_annuity_quotations';
                """
            ).fetchone()

        self.assertIsNotNone(
            row, "cnf__fact_annuity_quotations must be resolvable via active snapshot join"
        )
        self.assertEqual(row["version_id"], 1)
        self.assertEqual(row["status"], "COMMITTED")
        self.assertTrue(row["file_uri"].endswith("/*.parquet"))
        self.assertGreater(row["row_count"], 0)

    def test_zero_hardcoded_credentials(self):
        """Security Invariant: No hardcoded secrets or keys in version-two/ducklake/."""
        ducklake_dir = PROJECT_ROOT / "version-two" / "ducklake"
        forbidden_patterns = [
            r"GOOG1E[A-Za-z0-9]+",
            r"ScbiCubeSecretToken",
            r"password\s*=\s*['\"][^'\"]+['\"]",
            r"secret\s*=\s*['\"][^'\"]+['\"]",
        ]
        for path in ducklake_dir.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".sql", ".sh", ".json"}:
                content = path.read_text(encoding="utf-8", errors="ignore")
                for pat in forbidden_patterns:
                    self.assertIsNone(
                        re.search(pat, content, re.IGNORECASE),
                        f"Hardcoded credential pattern '{pat}' found in {path}",
                    )


if __name__ == "__main__":
    unittest.main()
