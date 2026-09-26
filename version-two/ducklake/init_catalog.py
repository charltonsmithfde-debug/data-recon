#!/usr/bin/env python3
"""
DuckLake PostgreSQL & SQLite Metadata Catalog Initializer.
Ticket: V2-1.1 (Initialize DuckLake PostgreSQL Metadata Catalog)

Idempotently initializes catalog schemas, manifest tables, and seeds initial
table snapshot metadata from scripts/migration_state.json.
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

# Locate project paths
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent.parent
DEFAULT_MIGRATION_STATE = PROJECT_ROOT / "scripts" / "migration_state.json"
DEFAULT_SCHEMA_SQL = MODULE_DIR / "schema.sql"
DEFAULT_SQLITE_PATH = MODULE_DIR / "ducklake_catalog.db"


class CatalogConnection:
    """Wrapper supporting SQLite and PostgreSQL transparently."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.environ.get("DUCKLAKE_DB_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")
        self.is_sqlite = self.db_url.startswith("sqlite:///") or not ("://" in self.db_url)
        self._conn = None

    def connect(self):
        if self.is_sqlite:
            clean_path = self.db_url.replace("sqlite:///", "") if "sqlite:///" in self.db_url else self.db_url
            if clean_path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(clean_path)), exist_ok=True)
            self._conn = sqlite3.connect(clean_path, timeout=30.0)
            self._conn.row_factory = sqlite3.Row
            # Enable foreign keys, WAL mode, and busy timeout for lock-free concurrent reads
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")
            self._conn.execute("PRAGMA busy_timeout = 30000;")
        else:
            try:
                import psycopg2
                import psycopg2.extras
                self._conn = psycopg2.connect(self.db_url, cursor_factory=psycopg2.extras.DictCursor)
            except ImportError:
                raise RuntimeError("psycopg2 is required for PostgreSQL connections: pip install psycopg2-binary")
        return self

    def execute_script(self, sql_script: str):
        if self.is_sqlite:
            self._conn.executescript(sql_script)
        else:
            with self._conn.cursor() as cur:
                cur.execute(sql_script)
            self._conn.commit()

    def execute(self, query: str, params: tuple = ()):
        cur = self._conn.cursor()
        # Adapt parameter placeholder: SQLite uses ?, Postgres uses %s
        if not self.is_sqlite:
            query = query.replace("?", "%s")
        cur.execute(query, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def initialize_catalog(
    db_url: Optional[str] = None,
    migration_state_path: Optional[str] = None,
    schema_sql_path: Optional[str] = None,
    author: str = "SC BI Platform Architecture",
    notes: str = "Initial DuckLake Catalog v1 seed from Snowflake-migrated Parquet"
) -> Dict[str, Any]:
    """Idempotently applies schema and seeds initial snapshot metadata."""
    schema_file = Path(schema_sql_path) if schema_sql_path else DEFAULT_SCHEMA_SQL
    state_file = Path(migration_state_path) if migration_state_path else DEFAULT_MIGRATION_STATE

    if not schema_file.exists():
        raise FileNotFoundError(f"Schema DDL not found at {schema_file}")
    if not state_file.exists():
        raise FileNotFoundError(f"Migration state JSON not found at {state_file}")

    with open(schema_file, "r", encoding="utf-8") as f:
        ddl_script = f.read()

    with open(state_file, "r", encoding="utf-8") as f:
        migration_state = json.load(f)

    tables_data = migration_state.get("tables", {})
    if not tables_data:
        raise ValueError("No tables discovered in migration state.")

    now_iso = datetime.now(timezone.utc).isoformat()
    version_id = 1

    with CatalogConnection(db_url) as conn:
        # 1. Apply DDL
        conn.execute_script(ddl_script)

        # 2. Insert or update initial snapshot v1
        conn.execute(
            """
            INSERT INTO ducklake_snapshots (version_id, committed_at, author, status, notes)
            VALUES (?, ?, ?, 'COMMITTED', ?)
            ON CONFLICT (version_id) DO UPDATE SET
                committed_at = excluded.committed_at,
                author = excluded.author,
                notes = excluded.notes;
            """,
            (version_id, now_iso, author, notes)
        )

        total_rows = 0
        total_bytes = 0
        tables_registered = 0

        # 3. Seed tables & manifests
        for table_key, info in tables_data.items():
            schema_name = info.get("schema", "SCBI_CDP_MART").lower()
            table_name = table_key.lower()
            table_id = f"{schema_name}.{table_name}"
            gcs_prefix = info.get("gcs_path", "")
            rows = int(info.get("rows_unloaded", 0))
            bytes_size = int(info.get("output_bytes", 0))

            total_rows += rows
            total_bytes += bytes_size
            tables_registered += 1

            # Upsert table metadata
            conn.execute(
                """
                INSERT INTO ducklake_tables (
                    table_id, schema_name, table_name, gcs_prefix,
                    active_version, row_count, output_bytes, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (table_id) DO UPDATE SET
                    schema_name = excluded.schema_name,
                    table_name = excluded.table_name,
                    gcs_prefix = excluded.gcs_prefix,
                    active_version = excluded.active_version,
                    row_count = excluded.row_count,
                    output_bytes = excluded.output_bytes,
                    updated_at = excluded.updated_at;
                """,
                (table_id, schema_name, table_name, gcs_prefix, version_id, rows, bytes_size, now_iso)
            )

            # Insert manifest entry for snapshot v1
            manifest_id = f"{table_id}:v{version_id}"
            file_pattern = f"{gcs_prefix.rstrip('/')}/*.parquet"
            conn.execute(
                """
                INSERT INTO ducklake_manifests (
                    manifest_id, table_id, version_id, file_uri, row_count, byte_size, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (manifest_id) DO UPDATE SET
                    file_uri = excluded.file_uri,
                    row_count = excluded.row_count,
                    byte_size = excluded.byte_size;
                """,
                (manifest_id, table_id, version_id, file_pattern, rows, bytes_size, now_iso)
            )

        # 4. Insert commit audit log
        commit_id = f"commit-v{version_id}-init"
        conn.execute(
            """
            INSERT INTO ducklake_commits (
                commit_id, version_id, operation, tables_affected, total_rows, total_bytes, committed_at
            )
            VALUES (?, ?, 'INITIAL_CATALOG_SEED', ?, ?, ?, ?)
            ON CONFLICT (commit_id) DO UPDATE SET
                tables_affected = excluded.tables_affected,
                total_rows = excluded.total_rows,
                total_bytes = excluded.total_bytes,
                committed_at = excluded.committed_at;
            """,
            (commit_id, version_id, tables_registered, total_rows, total_bytes, now_iso)
        )

        conn.commit()

    return {
        "status": "SUCCESS",
        "version_id": version_id,
        "tables_registered": tables_registered,
        "total_rows": total_rows,
        "total_bytes": total_bytes,
        "committed_at": now_iso
    }


def verify_catalog(db_url: Optional[str] = None) -> Dict[str, Any]:
    """Verifies catalog health, active snapshot, and table counts."""
    with CatalogConnection(db_url) as conn:
        cur = conn.execute("SELECT count(*) as count FROM ducklake_tables;")
        row = cur.fetchone()
        table_count = row["count"] if hasattr(row, "keys") else row[0]

        cur = conn.execute("SELECT count(*) as count, sum(row_count) as total_rows, sum(byte_size) as total_bytes FROM ducklake_manifests;")
        row = cur.fetchone()
        manifest_count = row["count"] if hasattr(row, "keys") else row[0]
        total_rows = row["total_rows"] if hasattr(row, "keys") else row[1]
        total_bytes = row["total_bytes"] if hasattr(row, "keys") else row[2]

        cur = conn.execute("SELECT version_id, committed_at, status, notes FROM ducklake_snapshots ORDER BY version_id DESC LIMIT 1;")
        snapshot_row = cur.fetchone()

        active_version = None
        if snapshot_row:
            active_version = {
                "version_id": snapshot_row["version_id"] if hasattr(snapshot_row, "keys") else snapshot_row[0],
                "committed_at": snapshot_row["committed_at"] if hasattr(snapshot_row, "keys") else snapshot_row[1],
                "status": snapshot_row["status"] if hasattr(snapshot_row, "keys") else snapshot_row[2],
                "notes": snapshot_row["notes"] if hasattr(snapshot_row, "keys") else snapshot_row[3],
            }

    return {
        "status": "HEALTHY",
        "tables_registered": int(table_count or 0),
        "manifests_registered": int(manifest_count or 0),
        "total_rows": int(total_rows or 0),
        "total_bytes": int(total_bytes or 0),
        "active_snapshot": (
            {
                "version_id": int(active_version["version_id"]),
                "committed_at": str(active_version["committed_at"]),
                "status": str(active_version["status"]),
                "notes": str(active_version["notes"]),
            }
            if active_version
            else None
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="DuckLake Catalog Initializer")
    parser.add_argument("--db-url", help="Database connection URL (PostgreSQL or SQLite)")
    parser.add_argument("--migration-state", help="Path to migration_state.json")
    parser.add_argument("--verify", action="store_true", help="Run verification without modifying")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    try:
        if args.verify:
            result = verify_catalog(args.db_url)
        else:
            result = initialize_catalog(args.db_url, args.migration_state)
            verify_res = verify_catalog(args.db_url)
            result["verification"] = verify_res

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"[OK] Catalog {result['status']}: {result.get('tables_registered', 0)} tables registered in Snapshot v{result.get('version_id', 1)}")
            print(f"Total Rows: {result.get('total_rows', 0):,} | Total Bytes: {result.get('total_bytes', 0):,}")
    except Exception as e:
        print(f"[ERROR] Failed to initialize catalog: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
