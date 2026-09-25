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

## 2026-09-25 — V2-2.2-cube-security-context
**Component:** `version-two/cube/security.js` (RBAC & Dynamic POPIA Masking Security Context)
**What happened:** `thin-web-app/role_assignments.json` is validated by `scripts/access/manage_access.py check` (ADR-0003) using V1 role identifiers (`ROLE_EXECUTIVE_ALL`, `ROLE_FINANCE_MEMBER`, `ROLE_INVESTMENTS`, `ROLE_ANNUITY`, `ROLE_DIGITAL_OPERATIONS`), while V2 PRD §5.2 introduces `ROLE_INVESTMENT_ANALYST`, `ROLE_ANNUITY_ANALYST`, `ROLE_MEMBER_OPERATIONS`, and `ROLE_AUDIT_COMPLIANCE`. Supporting both sets in `ROLE_PERMISSIONS` inside `security.js` preserves backward compatibility with `manage_access.py` while enforcing V2 domain cube boundaries and capping `canViewPii` strictly by `ROLE_PERMISSIONS[role].canViewPii`.
**What to do differently:**
1. Always compute `canViewPii` as `Boolean(ROLE_PERMISSIONS[role].canViewPii && claims.canViewPii)` so a non-PII role can never self-escalate PII visibility even if a forged or misconfigured claim asserts `canViewPii: true`.

## 2026-09-25 — V2-2.3-semantic-domain-cubes
**Component:** `version-two/cube/model/` (Semantic Domain Cube Models & Join Graphs)
**What happened:** Domain analysts (`ROLE_ANNUITY_ANALYST`, `ROLE_INVESTMENT_ANALYST`) need to join fact cubes (`AnnuityQuotation`, `InvestmentAnalysis`) with `DimMember`, `DimScheme`, and `DimDate` to slice metrics by demographic age brackets and scheme types without bypassing POPIA redaction. Including `DimMember`/`dim_member`, `DimScheme`/`dim_scheme`, and `DimDate`/`dim_date` in `SHARED_DIMENSIONS` while wrapping `id_number`, `member_id`, and `memberNk` in `compilePiiDimensionSql` allows cross-domain demographic slicing while guaranteeing PII fields remain salted SHA-256 hashes for non-PII roles.
**What to do differently:**
1. Enforce POPIA redaction at the dimension definition level (`compilePiiDimensionSql`) as well as in `queryRewrite` so shared dimension joins remain safe across all analytical roles.

## 2026-09-25 — V2-3.1-dual-delivery-infra
**Component:** `version-two/infra/` & `version-two/cube/cube.js` (Dual Delivery Topologies: Cloud Run REST + GCE VM SQL API)
**What happened:** Under the Single Artifact Principle (ADR-0004), a single container image (`scbi-cube:2.0`) serves both Cloud Run REST API (port `4000`) and GCE VM SQL API (port `5432`). Adding `startCubeSqlServer` and `executeSqlApiQuery` directly into `version-two/cube/cube.js` alongside `startCubeHttpServer` allows the identical runtime to boot in REST-only, SQL-only (`--serve-sql`), or dual-delivery (`--serve` with `CUBEJS_PG_SQL_PORT=5432`) mode while enforcing `checkSqlAuth` scrypt verification and blocking direct catalog/storage bypass queries.
**What to do differently:**
1. Always route SQL API queries (`executeSqlApiQuery`) through `modelIndex.loadDomainCubes()` and `securityHooks.queryRewrite` so SQL API consumers (Metabase, Power BI DirectQuery) are subject to the exact same RBAC and POPIA redaction rules as REST API consumers.
