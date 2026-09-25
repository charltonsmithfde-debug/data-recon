"""
Automated Verification Suite for Ticket V2-1.2:
Atomic Staging & Snapshot Commit Pipeline

Compatible with both standard library `unittest` and `pytest`.
"""

import os
import sys
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
)
from ducklake.reload_pipeline import (
    StageTablePayload,
    ReloadValidationError,
    build_staging_uri,
    commit_reload_batch,
    resolve_table_snapshot,
    rollback_to_snapshot,
)


class TestV212ReloadPipeline(unittest.TestCase):
    """Test suite validating atomic staging, snapshot commits, time-travel, and rollback (V2-1.2)."""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = tmp.name
        tmp.close()
        self.temp_db_url = f"sqlite:///{self.db_path}"
        initialize_catalog(db_url=self.temp_db_url)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_atomic_reload_creates_v2_snapshot(self):
        """AC1 & AC3: Staging and committing a batch advances snapshot v1 -> v2 atomically."""
        target_table = "scbi_cdp_mart.cnf__fact_annuity_quotations"
        staged_uri = build_staging_uri("scbi_cdp_mart", "cnf__fact_annuity_quotations", version_id=2)

        payload = StageTablePayload(
            table_id=target_table,
            staged_gcs_uri=staged_uri,
            row_count=210500,
            byte_size=18500000,
            expected_rows=210500,
        )

        res = commit_reload_batch([payload], db_url=self.temp_db_url)
        self.assertEqual(res["status"], "COMMITTED")
        self.assertEqual(res["previous_version"], 1)
        self.assertEqual(res["active_version"], 2)
        self.assertEqual(res["tables_reloaded"], 1)

        # Verify all 44 tables exist in v2 manifest
        with CatalogConnection(self.temp_db_url) as conn:
            v2_manifest_count = conn.execute(
                "SELECT count(*) FROM ducklake_manifests WHERE version_id = 2;"
            ).fetchone()[0]
            active_versions = conn.execute(
                "SELECT DISTINCT active_version FROM ducklake_tables;"
            ).fetchall()

        self.assertEqual(v2_manifest_count, 44)
        self.assertEqual(len(active_versions), 1)
        self.assertEqual(active_versions[0][0], 2)

    def test_precommit_validation_blocks_corrupt_stage(self):
        """AC2: Row count mismatch or empty unload raises ReloadValidationError and leaves v1 untouched."""
        target_table = "scbi_cdp_mart.cnf__fact_annuity_quotations"
        staged_uri = build_staging_uri("scbi_cdp_mart", "cnf__fact_annuity_quotations", version_id=2)

        # Case 1: Row count mismatch against Snowflake expected_rows
        bad_payload_mismatch = StageTablePayload(
            table_id=target_table,
            staged_gcs_uri=staged_uri,
            row_count=150000,
            byte_size=12000000,
            expected_rows=188832,
        )
        with self.assertRaises(ReloadValidationError):
            commit_reload_batch([bad_payload_mismatch], db_url=self.temp_db_url)

        # Case 2: Zero rows unloaded
        bad_payload_zero = StageTablePayload(
            table_id=target_table,
            staged_gcs_uri=staged_uri,
            row_count=0,
            byte_size=0,
        )
        with self.assertRaises(ReloadValidationError):
            commit_reload_batch([bad_payload_zero], db_url=self.temp_db_url)

        # Verify catalog remained strictly at Snapshot v1
        health = verify_catalog(db_url=self.temp_db_url)
        self.assertEqual(health["active_snapshot"]["version_id"], 1)

    def test_time_travel_and_snapshot_isolation(self):
        """AC4: Readers can pin historical Snapshot v1 while active pointer serves Snapshot v2."""
        target_table = "scbi_cdp_mart.cnf__fact_annuity_quotations"
        v1_snap = resolve_table_snapshot(target_table, version_id=1, db_url=self.temp_db_url)
        v1_original_rows = v1_snap["row_count"]

        staged_uri = build_staging_uri("scbi_cdp_mart", "cnf__fact_annuity_quotations", version_id=2)
        payload = StageTablePayload(
            table_id=target_table,
            staged_gcs_uri=staged_uri,
            row_count=v1_original_rows + 5000,
            byte_size=19000000,
            expected_rows=v1_original_rows + 5000,
        )
        commit_reload_batch([payload], db_url=self.temp_db_url)

        # Active snapshot resolution returns v2
        active_snap = resolve_table_snapshot(target_table, db_url=self.temp_db_url)
        self.assertEqual(active_snap["version_id"], 2)
        self.assertEqual(active_snap["row_count"], v1_original_rows + 5000)
        self.assertIn("/staging/scbi_cdp_mart/cnf__fact_annuity_quotations/v2/", active_snap["file_uri"])

        # Time-travel query to v1 still returns exact original state
        historical_v1 = resolve_table_snapshot(target_table, version_id=1, db_url=self.temp_db_url)
        self.assertEqual(historical_v1["version_id"], 1)
        self.assertEqual(historical_v1["row_count"], v1_original_rows)
        self.assertNotIn("/staging/", historical_v1["file_uri"])

    def test_instant_snapshot_rollback(self):
        """Rollback: Atomically restores all tables to Snapshot v1 after v2 commit."""
        target_table = "scbi_cdp_mart.cnf__fact_annuity_quotations"
        v1_snap = resolve_table_snapshot(target_table, version_id=1, db_url=self.temp_db_url)

        staged_uri = build_staging_uri("scbi_cdp_mart", "cnf__fact_annuity_quotations", version_id=2)
        payload = StageTablePayload(
            table_id=target_table,
            staged_gcs_uri=staged_uri,
            row_count=999999,
            byte_size=25000000,
        )
        commit_reload_batch([payload], db_url=self.temp_db_url)
        self.assertEqual(resolve_table_snapshot(target_table, db_url=self.temp_db_url)["version_id"], 2)

        # Rollback to v1
        rb = rollback_to_snapshot(1, db_url=self.temp_db_url)
        self.assertEqual(rb["status"], "ROLLED_BACK")
        self.assertEqual(rb["active_version"], 1)
        self.assertEqual(rb["tables_restored"], 44)

        restored = resolve_table_snapshot(target_table, db_url=self.temp_db_url)
        self.assertEqual(restored["version_id"], 1)
        self.assertEqual(restored["row_count"], v1_snap["row_count"])


if __name__ == "__main__":
    unittest.main()
