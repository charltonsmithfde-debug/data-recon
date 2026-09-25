-- ============================================================================
-- DuckLake Metadata Catalog Schema (PostgreSQL 16 & SQLite Compatible)
-- Ticket: V2-1.1 (Initialize DuckLake PostgreSQL Metadata Catalog)
-- ============================================================================

CREATE TABLE IF NOT EXISTS ducklake_snapshots (
    version_id INTEGER PRIMARY KEY,
    committed_at TEXT NOT NULL,
    author TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'COMMITTED',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS ducklake_tables (
    table_id TEXT PRIMARY KEY,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    gcs_prefix TEXT NOT NULL,
    active_version INTEGER NOT NULL REFERENCES ducklake_snapshots(version_id),
    row_count BIGINT NOT NULL DEFAULT 0,
    output_bytes BIGINT NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ducklake_manifests (
    manifest_id TEXT PRIMARY KEY,
    table_id TEXT NOT NULL REFERENCES ducklake_tables(table_id),
    version_id INTEGER NOT NULL REFERENCES ducklake_snapshots(version_id),
    file_uri TEXT NOT NULL,
    row_count BIGINT NOT NULL DEFAULT 0,
    byte_size BIGINT NOT NULL DEFAULT 0,
    checksum TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ducklake_commits (
    commit_id TEXT PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES ducklake_snapshots(version_id),
    operation TEXT NOT NULL,
    tables_affected INTEGER NOT NULL,
    total_rows BIGINT NOT NULL,
    total_bytes BIGINT NOT NULL,
    committed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ducklake_manifests_table_version
    ON ducklake_manifests(table_id, version_id);

CREATE INDEX IF NOT EXISTS idx_ducklake_tables_schema
    ON ducklake_tables(schema_name, table_name);
