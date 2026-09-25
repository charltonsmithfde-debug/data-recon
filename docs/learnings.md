# Engineering Learnings & Outer-Loop Retrospective

## 2026-09-25 — V2-1.1-ducklake-catalog-init
**Component:** `version-two/ducklake/` (DuckLake Metadata Catalog)
**What happened:** System Python (`/usr/bin/python3`) in the isolated sandbox environment does not have `pytest` or a `python` binary alias pre-installed; only `python3` and standard library `unittest` are guaranteed available out of the box. Additionally, Antigravity `PostToolUse` lifecycle hooks parse `stdout` strictly as `protojson` (expecting `{}`), so any diagnostic text printed to `stdout` causes hook unmarshaling errors.
**What to do differently:**
1. Always write test suites inheriting from `unittest.TestCase` so they run identically under both `python3 -m unittest` and `pytest`.
2. In lifecycle hook scripts (`scripts/sync_kanban.py`), send human-readable status logs to `sys.stderr` and output `{}` to `sys.stdout`.

## 2026-09-25 — V2-1.3-local-dev-harness
**Component:** `version-two/infra/` (Local Dev Harness & GCS ADC Validator)
**What happened:** Local development requires both a PostgreSQL instance for the DuckLake catalog and Cube.js SQL API (which speaks the PostgreSQL wire protocol on port `5432`). Binding the local DuckLake PostgreSQL container to `127.0.0.1:5433:5432` prevents port collisions with Cube SQL API (`5432`) and host PostgreSQL services.
**What to do differently:**
1. Keep `DUCKLAKE_DB_URL` standardized on port `5433` for local dev in `.env.example` and verify port separation in automated contract tests (`test_v2_1_3_local_dev_harness.py`).

## 2026-09-25 — V2-2.1-cube-semantic-engine
**Component:** `version-two/cube/` (Cube.js 1.7.x Core Engine & Embedded DuckLake Driver)
**What happened:** In local/CI environments without live Cloud SQL connectivity or pre-cached C++ native bindings, Node.js v26's built-in `node:sqlite` (`DatabaseSync`) enables `EmbeddedDuckLakeDriver` to deterministically resolve `lake.<schema>.<table>` queries against the DuckLake catalog (`ducklake_tables`, `ducklake_manifests`, `ducklake_snapshots`) while using `@duckdb/node-api` in-process in production containers.
**What to do differently:**
1. Store temporary fallback SQLite catalog files in `os.tmpdir()` rather than `version-two/ducklake/` so CLI dry-runs (`node version-two/cube/cube.js --verify-query ...`) never leave untracked files in the repository tree.

