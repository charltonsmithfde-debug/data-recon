#!/usr/bin/env python3
"""
DuckLake Atomic Staging & Snapshot Commit Pipeline.
Ticket: V2-1.2 (Atomic Staging & Snapshot Commit Pipeline)

Prevents torn reads and stale-file double counting by staging Parquet reloads
into versioned GCS prefixes, verifying row/byte integrity pre-commit, and
switching active catalog pointers in a single atomic SQL transaction.
"""

import os
import sys
import json
import hashlib
import argparse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from ducklake.init_catalog import CatalogConnection, initialize_catalog


class ReloadValidationError(ValueError):
    """Raised when staged Parquet unload fails pre-commit integrity checks."""


@dataclass
class StageTablePayload:
    """Represents a staged table unload ready for atomic catalog registration."""
    table_id: str
    staged_gcs_uri: str
    row_count: int
    byte_size: int
    expected_rows: Optional[int] = None
    checksum: Optional[str] = None


def build_staging_uri(
    schema_name: str,
    table_name: str,
    version_id: int,
    bucket: str = "scbi-ducklake-myanalyticsproduct"
) -> str:
    """Constructs an isolated versioned staging URI in GCS."""
    s_clean = schema_name.lower().strip()
    t_clean = table_name.lower().strip()
    return f"gs://{bucket}/staging/{s_clean}/{t_clean}/v{version_id}/*.parquet"


def validate_staged_payloads(payloads: List[StageTablePayload]) -> None:
    """
    Validates staged table payloads prior to opening a catalog transaction.
    Raises ReloadValidationError if any check fails.
    """
    if not payloads:
        raise ReloadValidationError("Reload batch cannot be empty.")

    for p in payloads:
        if not p.table_id or "." not in p.table_id:
            raise ReloadValidationError(f"Invalid table_id '{p.table_id}'; expected '<schema>.<table>'.")
        if not p.staged_gcs_uri.startswith("gs://") or not p.staged_gcs_uri.endswith(".parquet"):
            raise ReloadValidationError(
                f"Invalid staged_gcs_uri '{p.staged_gcs_uri}' for {p.table_id}; must be a gs:// Parquet URI."
            )
        if p.row_count <= 0:
            raise ReloadValidationError(
                f"Staged unload for {p.table_id} has non-positive row_count ({p.row_count})."
            )
        if p.byte_size <= 0:
            raise ReloadValidationError(
                f"Staged unload for {p.table_id} has non-positive byte_size ({p.byte_size})."
            )
        if p.expected_rows is not None and p.row_count != p.expected_rows:
            raise ReloadValidationError(
                f"Row count mismatch for {p.table_id}: staged={p.row_count}, expected={p.expected_rows}."
            )


def commit_reload_batch(
    payloads: List[StageTablePayload],
    db_url: Optional[str] = None,
    author: str = "SC BI Reload Pipeline",
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validates staged tables and commits a new lakehouse snapshot version in one atomic transaction.
    Carries forward unchanged table manifests so every snapshot version is self-contained.
    """
    # 1. Pre-commit validation (fails fast before touching database)
    validate_staged_payloads(payloads)

    now_iso = datetime.now(timezone.utc).isoformat()

    with CatalogConnection(db_url) as conn:
        # Verify catalog is initialized and get current max version
        cur = conn.execute("SELECT max(version_id) FROM ducklake_snapshots;")
        row = cur.fetchone()
        current_version = row[0] if row and row[0] is not None else None
        if current_version is None:
            raise RuntimeError("Catalog has no existing snapshots; run init_catalog first.")

        next_version = int(current_version) + 1
        commit_notes = notes or f"Atomic reload of {len(payloads)} table(s) -> Snapshot v{next_version}"

        # Verify all target tables exist in catalog
        payload_by_id = {p.table_id.lower(): p for p in payloads}
        existing_rows = conn.execute(
            "SELECT table_id, schema_name, table_name, gcs_prefix, row_count, output_bytes FROM ducklake_tables;"
        ).fetchall()
        existing_tables = {
            (r["table_id"] if hasattr(r, "keys") else r[0]).lower(): dict(r) if hasattr(r, "keys") else {
                "table_id": r[0], "schema_name": r[1], "table_name": r[2],
                "gcs_prefix": r[3], "row_count": r[4], "output_bytes": r[5]
            }
            for r in existing_rows
        }

        for tid in payload_by_id:
            if tid not in existing_tables:
                raise ReloadValidationError(f"Target table '{tid}' is not registered in ducklake_tables.")

        # 2. Insert new snapshot record
        conn.execute(
            """
            INSERT INTO ducklake_snapshots (version_id, committed_at, author, status, notes)
            VALUES (?, ?, ?, 'COMMITTED', ?);
            """,
            (next_version, now_iso, author, commit_notes)
        )

        # 3. Carry forward current manifests and override updated tables for next_version
        prev_manifests = conn.execute(
            """
            SELECT table_id, file_uri, row_count, byte_size, checksum
            FROM ducklake_manifests
            WHERE version_id = ?;
            """,
            (current_version,)
        ).fetchall()

        total_rows_reloaded = 0
        total_bytes_reloaded = 0

        for m_row in prev_manifests:
            tid = (m_row["table_id"] if hasattr(m_row, "keys") else m_row[0]).lower()
            manifest_id = f"{tid}:v{next_version}"

            if tid in payload_by_id:
                p = payload_by_id[tid]
                checksum = p.checksum or hashlib.sha256(
                    f"{tid}:{p.staged_gcs_uri}:{p.row_count}:{p.byte_size}".encode("utf-8")
                ).hexdigest()[:16]
                conn.execute(
                    """
                    INSERT INTO ducklake_manifests (
                        manifest_id, table_id, version_id, file_uri, row_count, byte_size, checksum, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (manifest_id, tid, next_version, p.staged_gcs_uri, p.row_count, p.byte_size, checksum, now_iso)
                )
                # Update active table metadata
                new_prefix = p.staged_gcs_uri.rsplit("/", 1)[0] + "/"
                conn.execute(
                    """
                    UPDATE ducklake_tables
                    SET active_version = ?,
                        gcs_prefix = ?,
                        row_count = ?,
                        output_bytes = ?,
                        updated_at = ?
                    WHERE table_id = ?;
                    """,
                    (next_version, new_prefix, p.row_count, p.byte_size, now_iso, tid)
                )
                total_rows_reloaded += p.row_count
                total_bytes_reloaded += p.byte_size
            else:
                # Carry forward unchanged manifest to new snapshot version
                f_uri = m_row["file_uri"] if hasattr(m_row, "keys") else m_row[1]
                r_cnt = m_row["row_count"] if hasattr(m_row, "keys") else m_row[2]
                b_sz = m_row["byte_size"] if hasattr(m_row, "keys") else m_row[3]
                chk = m_row["checksum"] if hasattr(m_row, "keys") else m_row[4]
                conn.execute(
                    """
                    INSERT INTO ducklake_manifests (
                        manifest_id, table_id, version_id, file_uri, row_count, byte_size, checksum, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (manifest_id, tid, next_version, f_uri, r_cnt, b_sz, chk, now_iso)
                )
                # Advance table active_version pointer
                conn.execute(
                    """
                    UPDATE ducklake_tables
                    SET active_version = ?, updated_at = ?
                    WHERE table_id = ?;
                    """,
                    (next_version, now_iso, tid)
                )

        # 4. Record transactional commit audit log
        commit_id = f"commit-v{next_version}-reload"
        conn.execute(
            """
            INSERT INTO ducklake_commits (
                commit_id, version_id, operation, tables_affected, total_rows, total_bytes, committed_at
            )
            VALUES (?, ?, 'ATOMIC_STAGE_RELOAD', ?, ?, ?, ?);
            """,
            (commit_id, next_version, len(payloads), total_rows_reloaded, total_bytes_reloaded, now_iso)
        )

        # 5. Atomic commit
        conn.commit()

    return {
        "status": "COMMITTED",
        "previous_version": current_version,
        "active_version": next_version,
        "tables_reloaded": len(payloads),
        "rows_reloaded": total_rows_reloaded,
        "bytes_reloaded": total_bytes_reloaded,
        "committed_at": now_iso,
    }


def resolve_table_snapshot(
    table_id: str,
    version_id: Optional[int] = None,
    db_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resolves a table's manifest for either the current active snapshot or a specific
    historical snapshot version (Time Travel).
    """
    tid = table_id.lower().strip()
    with CatalogConnection(db_url) as conn:
        if version_id is None:
            row = conn.execute(
                """
                SELECT
                    t.table_id,
                    t.active_version AS version_id,
                    s.status,
                    m.file_uri,
                    m.row_count,
                    m.byte_size,
                    m.checksum,
                    s.committed_at
                FROM ducklake_tables t
                JOIN ducklake_snapshots s ON s.version_id = t.active_version
                JOIN ducklake_manifests m ON m.table_id = t.table_id AND m.version_id = t.active_version
                WHERE t.table_id = ?;
                """,
                (tid,)
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT
                    m.table_id,
                    m.version_id,
                    s.status,
                    m.file_uri,
                    m.row_count,
                    m.byte_size,
                    m.checksum,
                    s.committed_at
                FROM ducklake_manifests m
                JOIN ducklake_snapshots s ON s.version_id = m.version_id
                WHERE m.table_id = ? AND m.version_id = ?;
                """,
                (tid, int(version_id))
            ).fetchone()

    if not row:
        raise KeyError(f"No snapshot manifest found for table '{tid}' at version={version_id or 'ACTIVE'}")

    return {
        "table_id": row["table_id"] if hasattr(row, "keys") else row[0],
        "version_id": row["version_id"] if hasattr(row, "keys") else row[1],
        "status": row["status"] if hasattr(row, "keys") else row[2],
        "file_uri": row["file_uri"] if hasattr(row, "keys") else row[3],
        "row_count": row["row_count"] if hasattr(row, "keys") else row[4],
        "byte_size": row["byte_size"] if hasattr(row, "keys") else row[5],
        "checksum": row["checksum"] if hasattr(row, "keys") else row[6],
        "committed_at": row["committed_at"] if hasattr(row, "keys") else row[7],
    }


def rollback_to_snapshot(
    target_version_id: int,
    db_url: Optional[str] = None,
    author: str = "SC BI Rollback Operator"
) -> Dict[str, Any]:
    """Atomically rolls back all catalog tables to a prior committed snapshot version."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with CatalogConnection(db_url) as conn:
        snap = conn.execute(
            "SELECT version_id, status FROM ducklake_snapshots WHERE version_id = ?;",
            (target_version_id,)
        ).fetchone()
        if not snap:
            raise ValueError(f"Target snapshot version {target_version_id} does not exist.")

        manifests = conn.execute(
            """
            SELECT table_id, file_uri, row_count, byte_size
            FROM ducklake_manifests
            WHERE version_id = ?;
            """,
            (target_version_id,)
        ).fetchall()

        for m in manifests:
            tid = m["table_id"] if hasattr(m, "keys") else m[0]
            f_uri = m["file_uri"] if hasattr(m, "keys") else m[1]
            r_cnt = m["row_count"] if hasattr(m, "keys") else m[2]
            b_sz = m["byte_size"] if hasattr(m, "keys") else m[3]
            prefix = f_uri.rsplit("/", 1)[0] + "/"
            conn.execute(
                """
                UPDATE ducklake_tables
                SET active_version = ?,
                    gcs_prefix = ?,
                    row_count = ?,
                    output_bytes = ?,
                    updated_at = ?
                WHERE table_id = ?;
                """,
                (target_version_id, prefix, r_cnt, b_sz, now_iso, tid)
            )

        commit_id = f"commit-rollback-to-v{target_version_id}-{int(datetime.now(timezone.utc).timestamp())}"
        conn.execute(
            """
            INSERT INTO ducklake_commits (
                commit_id, version_id, operation, tables_affected, total_rows, total_bytes, committed_at
            )
            VALUES (?, ?, 'SNAPSHOT_ROLLBACK', ?, 0, 0, ?);
            """,
            (commit_id, target_version_id, len(manifests), now_iso)
        )
        conn.commit()

    return {
        "status": "ROLLED_BACK",
        "active_version": target_version_id,
        "tables_restored": len(manifests),
        "rolled_back_at": now_iso,
    }


def main():
    parser = argparse.ArgumentParser(description="DuckLake Atomic Staging & Snapshot Commit Pipeline")
    parser.add_argument("--db-url", help="Database connection URL")
    parser.add_argument("--simulate-table", default="scbi_cdp_mart.cnf__fact_annuity_quotations", help="Table ID to simulate reload")
    parser.add_argument("--rows", type=int, default=195000, help="Simulated row count")
    parser.add_argument("--bytes", type=int, default=16200000, help="Simulated byte size")
    parser.add_argument("--rollback", type=int, help="Rollback to specified snapshot version ID")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if args.rollback is not None:
        res = rollback_to_snapshot(args.rollback, db_url=args.db_url)
    else:
        schema_name, table_name = args.simulate_table.split(".", 1)
        staged_uri = build_staging_uri(schema_name, table_name, version_id=2)
        payload = StageTablePayload(
            table_id=args.simulate_table,
            staged_gcs_uri=staged_uri,
            row_count=args.rows,
            byte_size=args.bytes,
            expected_rows=args.rows,
        )
        res = commit_reload_batch([payload], db_url=args.db_url)

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"[OK] {res['status']} -> Active Snapshot v{res['active_version']}")


if __name__ == "__main__":
    main()
