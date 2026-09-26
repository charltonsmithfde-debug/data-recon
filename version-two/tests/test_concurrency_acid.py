"""
Concurrency & Zero-Torn-Reads Verification Harness
Ticket: V2-4.2 — Concurrency & Zero-Torn-Reads Verification Harness

Verifies all 4 Acceptance Criteria:
1. Background workers execute continuous high-frequency aggregation queries against
   `AnnuityQuotation` during a live table reload.
2. Asserts that every query returns data strictly from either the pre-reload snapshot
   (v_old) or post-reload snapshot (v_new) without intermediate states.
3. Proves zero lock timeouts or table unavailable exceptions during the commit window.
4. Generates concurrency verification telemetry proving 100% snapshot isolation under load.

Compatible with both standard library `unittest` and `pytest`.
"""

from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSION_TWO_DIR = PROJECT_ROOT / "version-two"
CUBE_DIR = VERSION_TWO_DIR / "cube"
PORTAL_DIR = VERSION_TWO_DIR / "portal"
METABASE_DIR = VERSION_TWO_DIR / "metabase"
TELEMETRY_REPORT_PATH = (
    VERSION_TWO_DIR / "tests" / "reports" / "concurrency_acid_telemetry.json"
)

if str(VERSION_TWO_DIR) not in sys.path:
    sys.path.insert(0, str(VERSION_TWO_DIR))

from ducklake.init_catalog import initialize_catalog  # noqa: E402
from ducklake.reload_pipeline import (  # noqa: E402
    ReloadValidationError,
    StageTablePayload,
    build_staging_uri,
    commit_reload_batch,
)


def _load_module(mod_name: str, file_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


auth_mod = _load_module("portal_auth_v2_4_2", PORTAL_DIR / "auth.py")
metabase_setup_mod = _load_module("metabase_setup_v2_4_2", METABASE_DIR / "setup.py")

TARGET_TABLE_ID = "scbi_cdp_mart.cnf__fact_annuity_quotations"

# Valid committed snapshot states for AnnuityQuotation:
# Snapshot v1 (initial seed): 129,954 rows
# Snapshot v2 (first live reload): 210,500 rows
# Snapshot v3 (second live reload): 245,000 rows
VALID_SNAPSHOT_SIGNATURES: dict[int, dict[str, float | int]] = {
    1: {
        "row_count": 129954,
        "AnnuityQuotation.quotationCount": 129954,
        "AnnuityQuotation.acceptedQuotations": math.floor(129954 * 0.25),
        "AnnuityQuotation.quotedPurchasePrice": 129954 * 1250.5,
        "AnnuityQuotation.averageCommissionRate": 2.75,
    },
    2: {
        "row_count": 210500,
        "AnnuityQuotation.quotationCount": 210500,
        "AnnuityQuotation.acceptedQuotations": math.floor(210500 * 0.25),
        "AnnuityQuotation.quotedPurchasePrice": 210500 * 1250.5,
        "AnnuityQuotation.averageCommissionRate": 2.75,
    },
    3: {
        "row_count": 245000,
        "AnnuityQuotation.quotationCount": 245000,
        "AnnuityQuotation.acceptedQuotations": math.floor(245000 * 0.25),
        "AnnuityQuotation.quotedPurchasePrice": 245000 * 1250.5,
        "AnnuityQuotation.averageCommissionRate": 2.75,
    },
}


def is_valid_atomic_snapshot_observation(obs: dict[str, Any]) -> bool:
    """
    Verifies that a single query observation matches one of the valid committed snapshots
    (`v1`, `v2`, or `v3`) across every measure simultaneously, with zero partial or torn values.
    """
    version = obs.get("snapshot_version")
    if version not in VALID_SNAPSHOT_SIGNATURES:
        return False

    expected = VALID_SNAPSHOT_SIGNATURES[version]
    row = obs.get("row") or {}
    for measure_key in (
        "AnnuityQuotation.quotationCount",
        "AnnuityQuotation.acceptedQuotations",
        "AnnuityQuotation.quotedPurchasePrice",
        "AnnuityQuotation.averageCommissionRate",
    ):
        if measure_key not in row:
            return False
        if abs(float(row[measure_key]) - float(expected[measure_key])) > 1e-9:
            return False
    return True


def run_concurrency_acid_harness(
    catalog_db_path: str,
    rest_base_url: str,
    sql_port: int,
    jwt_token: str,
    num_workers: int = 8,
    iterations_per_worker: int = 28,
) -> dict[str, Any]:
    """
    Executes `num_workers` concurrent reader threads continuously querying `AnnuityQuotation`
    (over both Cube REST API and Cube SQL API) while the writer thread stages and commits
    live DuckLake snapshot reloads (`v1 -> v2 -> v3`) plus an aborted corrupt stage.
    """
    db_url = f"sqlite:///{catalog_db_path}"
    barrier = threading.Barrier(num_workers + 1)
    v1_sampled_event = threading.Event()
    v2_sampled_event = threading.Event()
    observations_lock = threading.Lock()
    version_live_counts: dict[int, int] = {1: 0, 2: 0, 3: 0}
    all_observations: list[dict[str, Any]] = []
    errors_recorded: list[dict[str, Any]] = []
    lock_timeouts = 0
    non_monotonic_transitions = 0
    reload_events: list[dict[str, Any]] = []

    rest_payload_bytes = json.dumps(
        {
            "query": {
                "measures": [
                    "AnnuityQuotation.quotationCount",
                    "AnnuityQuotation.acceptedQuotations",
                    "AnnuityQuotation.quotedPurchasePrice",
                    "AnnuityQuotation.averageCommissionRate",
                ],
                "dimensions": [
                    "AnnuityQuotation.derivedQuotationStatus",
                    "DimScheme.schemeName",
                ],
            }
        }
    ).encode("utf-8")

    sql_query_str = (
        "SELECT AnnuityQuotation.quotationCount, AnnuityQuotation.acceptedQuotations, "
        "AnnuityQuotation.quotedPurchasePrice, AnnuityQuotation.averageCommissionRate, "
        "AnnuityQuotation.derivedQuotationStatus, DimScheme.schemeName "
        "FROM AnnuityQuotation"
    )

    def reader_worker(worker_id: int) -> list[dict[str, Any]]:
        nonlocal lock_timeouts, non_monotonic_transitions
        worker_obs: list[dict[str, Any]] = []
        highest_version_seen = 1
        sql_client = metabase_setup_mod.CubeSqlWireClient(
            host="127.0.0.1",
            port=sql_port,
            user="cube_annuity_analyst",
            password="scbi_annuity_v2_pass",
            timeout=10.0,
        )

        barrier.wait()

        for seq in range(iterations_per_worker):
            t0 = time.perf_counter()
            protocol = "rest" if (seq % 2 == 0) else "sql_wire"
            try:
                if protocol == "rest":
                    req = urllib.request.Request(
                        url=f"{rest_base_url}/cubejs-api/v1/load",
                        data=rest_payload_bytes,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {jwt_token}",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=10.0) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    row = body["data"][0]
                    snap_ver = int(body.get("snapshotVersion", 1))
                else:
                    res = sql_client.execute_sql(sql_query_str)
                    if res.get("status") != "OK":
                        raise RuntimeError(f"SQL wire error: {res.get('error')}")
                    row = res["rows"][0]
                    snap_ver = int(res.get("snapshotVersion", 1))

                latency_ms = (time.perf_counter() - t0) * 1000.0
                obs = {
                    "worker_id": worker_id,
                    "seq": seq,
                    "protocol": protocol,
                    "snapshot_version": snap_ver,
                    "quotation_count": row.get("AnnuityQuotation.quotationCount"),
                    "accepted_quotations": row.get("AnnuityQuotation.acceptedQuotations"),
                    "quoted_purchase_price": row.get("AnnuityQuotation.quotedPurchasePrice"),
                    "row": row,
                    "latency_ms": round(latency_ms, 3),
                    "valid_snapshot": False,
                }
                obs["valid_snapshot"] = is_valid_atomic_snapshot_observation(obs)

                with observations_lock:
                    version_live_counts[snap_ver] = version_live_counts.get(snap_ver, 0) + 1
                    if version_live_counts.get(1, 0) >= 24:
                        v1_sampled_event.set()
                    if version_live_counts.get(2, 0) >= 24:
                        v2_sampled_event.set()
                    if snap_ver < highest_version_seen:
                        non_monotonic_transitions += 1
                    else:
                        highest_version_seen = snap_ver

                worker_obs.append(obs)
            except Exception as exc:
                msg = str(exc)
                with observations_lock:
                    if "locked" in msg.lower() or "timeout" in msg.lower() or "busy" in msg.lower():
                        lock_timeouts += 1
                    errors_recorded.append(
                        {
                            "worker_id": worker_id,
                            "seq": seq,
                            "protocol": protocol,
                            "error": msg,
                        }
                    )
            time.sleep(0.004)

        with observations_lock:
            all_observations.extend(worker_obs)
        return worker_obs

    def reload_writer() -> None:
        barrier.wait()
        # Wait until background workers have actively sampled v1 under load
        v1_sampled_event.wait(timeout=10.0)

        # 1. Simulate an aborted/partial stage (row count mismatch) during live reads
        corrupt_payload = StageTablePayload(
            table_id=TARGET_TABLE_ID,
            staged_gcs_uri=build_staging_uri(
                "scbi_cdp_mart", "cnf__fact_annuity_quotations", version_id=99
            ),
            row_count=64977,  # Half-unloaded partial partition
            byte_size=8000000,
            expected_rows=210500,
        )
        try:
            commit_reload_batch([corrupt_payload], db_url=db_url)
        except ReloadValidationError as exc:
            reload_events.append(
                {
                    "event": "ABORTED_PARTIAL_STAGE_BLOCKED",
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        # 2. Commit atomic reload v1 -> v2 (129,954 -> 210,500 rows) while workers are mid-flight
        v2_payload = StageTablePayload(
            table_id=TARGET_TABLE_ID,
            staged_gcs_uri=build_staging_uri(
                "scbi_cdp_mart", "cnf__fact_annuity_quotations", version_id=2
            ),
            row_count=210500,
            byte_size=18500000,
            expected_rows=210500,
        )
        v2_commit = commit_reload_batch(
            [v2_payload],
            db_url=db_url,
            author="V2-4.2 Concurrency Harness",
            notes="Atomic reload v1 -> v2 under concurrent read load",
        )
        reload_events.append(v2_commit)

        # Wait until background workers have actively sampled v2 under load
        v2_sampled_event.wait(timeout=10.0)

        # 3. Commit second atomic reload v2 -> v3 (210,500 -> 245,000 rows) while workers are mid-flight
        v3_payload = StageTablePayload(
            table_id=TARGET_TABLE_ID,
            staged_gcs_uri=build_staging_uri(
                "scbi_cdp_mart", "cnf__fact_annuity_quotations", version_id=3
            ),
            row_count=245000,
            byte_size=21400000,
            expected_rows=245000,
        )
        v3_commit = commit_reload_batch(
            [v3_payload],
            db_url=db_url,
            author="V2-4.2 Concurrency Harness",
            notes="Atomic reload v2 -> v3 under concurrent read load",
        )
        reload_events.append(v3_commit)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers + 1) as pool:
        writer_future = pool.submit(reload_writer)
        reader_futures = [pool.submit(reader_worker, wid) for wid in range(num_workers)]
        writer_future.result(timeout=30.0)
        for rf in reader_futures:
            rf.result(timeout=30.0)

    total_queries = len(all_observations)
    torn_reads = sum(1 for o in all_observations if not o["valid_snapshot"])
    counts_by_version: dict[str, int] = {}
    for o in all_observations:
        v_key = f"v{o['snapshot_version']}"
        counts_by_version[v_key] = counts_by_version.get(v_key, 0) + 1

    latencies = sorted(o["latency_ms"] for o in all_observations) if all_observations else [0.0]
    p50_ms = latencies[len(latencies) // 2]
    p99_ms = latencies[min(len(latencies) - 1, int(len(latencies) * 0.99))]

    telemetry = {
        "ticket": "V2-4.2",
        "title": "Concurrency & Zero-Torn-Reads Verification Harness",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_cube": "AnnuityQuotation",
        "target_table": TARGET_TABLE_ID,
        "worker_threads": num_workers,
        "iterations_per_worker": iterations_per_worker,
        "total_queries_executed": total_queries,
        "snapshots_observed": counts_by_version,
        "torn_reads_detected": torn_reads,
        "partial_partition_reads": torn_reads,
        "non_monotonic_transitions": non_monotonic_transitions,
        "lock_timeouts": lock_timeouts,
        "failed_queries": len(errors_recorded),
        "errors": errors_recorded,
        "reload_events": reload_events,
        "latency_ms": {
            "min": round(latencies[0], 3),
            "p50": round(p50_ms, 3),
            "p99": round(p99_ms, 3),
            "max": round(latencies[-1], 3),
        },
        "snapshot_isolation_rate_pct": 100.0
        if (total_queries > 0 and torn_reads == 0 and len(errors_recorded) == 0)
        else 0.0,
        "verdict": "PASS"
        if (
            total_queries > 0
            and torn_reads == 0
            and lock_timeouts == 0
            and len(errors_recorded) == 0
            and non_monotonic_transitions == 0
        )
        else "FAIL",
    }

    TELEMETRY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TELEMETRY_REPORT_PATH.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")
    return {
        "telemetry": telemetry,
        "observations": all_observations,
    }


class TestV242ConcurrencyAcidVerificationHarness(unittest.TestCase):
    """
    Validates V2-4.2 Concurrency & Zero-Torn-Reads Verification Harness under live
    multi-threaded read load and concurrent DuckLake table reloads.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.catalog_db_path = str(Path(cls._tmpdir.name) / "concurrency_acid_catalog.db")
        cls.db_url = f"sqlite:///{cls.catalog_db_path}"
        initialize_catalog(db_url=cls.db_url)

        cls.api_secret = "v2-4-2-concurrency-acid-shared-secret-key-32b!"
        identity = auth_mod.VerifiedIdentity(
            email="charltonsmithfde@gmail.com",
            role="ROLE_EXECUTIVE_ALL",
            can_view_pii=True,
            groups=("sys_admin",),
        )
        cls.jwt_token = auth_mod.mint_cube_jwt(identity, secret=cls.api_secret)

        node_runner = f"""
const cube = require({json.dumps(str(CUBE_DIR / "cube.js"))});
(async () => {{
  const restSrv = await cube.startCubeHttpServer({{
    port: 0,
    catalogDbPath: {json.dumps(cls.catalog_db_path)},
    apiSecret: {json.dumps(cls.api_secret)}
  }});
  const sqlSrv = await cube.startCubeSqlServer({{
    sqlPort: 0,
    catalogDbPath: {json.dumps(cls.catalog_db_path)}
  }});
  console.log(JSON.stringify({{ restPort: restSrv.port, sqlPort: sqlSrv.port }}));
  process.stdin.resume();
  process.stdin.on('data', async () => {{
    await restSrv.close();
    await sqlSrv.close();
    process.exit(0);
  }});
}})();
"""
        cls._proc = subprocess.Popen(
            ["node", "-e", node_runner],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert cls._proc.stdout is not None
        ports = json.loads(cls._proc.stdout.readline().strip())
        cls.rest_base_url = f"http://127.0.0.1:{ports['restPort']}"
        cls.sql_port = int(ports["sqlPort"])

        cls.harness_result = run_concurrency_acid_harness(
            catalog_db_path=cls.catalog_db_path,
            rest_base_url=cls.rest_base_url,
            sql_port=cls.sql_port,
            jwt_token=cls.jwt_token,
            num_workers=8,
            iterations_per_worker=28,
        )
        cls.telemetry = cls.harness_result["telemetry"]
        cls.observations = cls.harness_result["observations"]

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_proc") and cls._proc:
            for pipe in (cls._proc.stdin, cls._proc.stdout, cls._proc.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except OSError:
                        pass
            cls._proc.terminate()
            cls._proc.wait(timeout=5)
        if hasattr(cls, "_tmpdir") and cls._tmpdir:
            cls._tmpdir.cleanup()

    def test_ac1_background_workers_execute_continuous_high_frequency_queries_during_live_reload(
        self,
    ) -> None:
        """AC 1: Background workers execute continuous high-frequency aggregation queries against AnnuityQuotation during a live table reload."""
        self.assertEqual(self.telemetry["worker_threads"], 8)
        self.assertGreaterEqual(self.telemetry["total_queries_executed"], 200)

        # Verify both REST and SQL Wire protocols were exercised under load
        protocols = {o["protocol"] for o in self.observations}
        self.assertEqual(protocols, {"rest", "sql_wire"})

        # Verify queries spanned pre-reload (v1) and post-reload (v2 / v3) snapshots
        snapshots_seen = self.telemetry["snapshots_observed"]
        self.assertGreater(
            snapshots_seen.get("v1", 0),
            0,
            f"Expected pre-reload v1 queries to be observed, got {snapshots_seen}",
        )
        post_reload_count = snapshots_seen.get("v2", 0) + snapshots_seen.get("v3", 0)
        self.assertGreater(
            post_reload_count,
            0,
            f"Expected post-reload v2/v3 queries to be observed, got {snapshots_seen}",
        )

    def test_ac2_zero_torn_reads_or_intermediate_states_between_snapshots(self) -> None:
        """AC 2: Asserts that every query returns data strictly from either the pre-reload snapshot (v_old) or post-reload snapshot (v_new) without intermediate states."""
        self.assertEqual(self.telemetry["torn_reads_detected"], 0)
        self.assertEqual(self.telemetry["partial_partition_reads"], 0)
        self.assertEqual(self.telemetry["non_monotonic_transitions"], 0)

        valid_counts = {129954, 210500, 245000}
        for obs in self.observations:
            self.assertTrue(
                obs["valid_snapshot"],
                f"Torn or inconsistent snapshot observation detected: {obs}",
            )
            self.assertIn(
                obs["quotation_count"],
                valid_counts,
                f"Unexpected intermediate quotationCount {obs['quotation_count']} (corrupt stage 64977 must never leak)",
            )
            self.assertNotEqual(obs["quotation_count"], 64977)

    def test_ac3_zero_lock_timeouts_or_table_unavailable_exceptions(self) -> None:
        """AC 3: Proves zero lock timeouts or table unavailable exceptions during the commit window."""
        self.assertEqual(self.telemetry["lock_timeouts"], 0)
        self.assertEqual(self.telemetry["failed_queries"], 0)
        self.assertEqual(self.telemetry["errors"], [])

    def test_ac4_generates_concurrency_verification_telemetry_proving_snapshot_isolation(
        self,
    ) -> None:
        """AC 4: Generates concurrency verification telemetry proving 100% snapshot isolation under load."""
        self.assertTrue(
            TELEMETRY_REPORT_PATH.is_file(),
            f"Expected concurrency telemetry file at {TELEMETRY_REPORT_PATH}",
        )
        persisted = json.loads(TELEMETRY_REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(persisted["ticket"], "V2-4.2")
        self.assertEqual(persisted["verdict"], "PASS")
        self.assertEqual(persisted["snapshot_isolation_rate_pct"], 100.0)
        self.assertEqual(persisted["torn_reads_detected"], 0)
        self.assertEqual(persisted["lock_timeouts"], 0)
        self.assertGreaterEqual(len(persisted["reload_events"]), 3)


if __name__ == "__main__":
    unittest.main()
