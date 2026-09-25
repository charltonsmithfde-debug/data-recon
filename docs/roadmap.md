# Roadmap — Version 2.0: Unified ACID Lakehouse & Semantic Metric Layer

| | |
|---|---|
| **Document ID** | ROADMAP-V2-DUCKLAKE-CUBE |
| **Status** | Active |
| **Context Pack** | none |
| **PRD Reference** | [`docs/prd.md`](./prd.md) |
| **Architecture Reference** | [`docs/architecture.md`](./architecture.md) |
| **Dashboard** | [`docs/dashboard/index.html`](./dashboard/index.html) |

---

## Topological Build Order & Dependency Graph

```
Milestone 1:
V2-1.1 (ducklake-catalog-init) ──┬──► V2-1.2 (atomic-reload-pipeline)
                                 └──► V2-1.3 (local-dev-harness)

Milestone 2:
V2-1.1 + V2-1.3 ──► V2-2.1 (cube-semantic-engine) ──► V2-2.2 (cube-security-context) ──► V2-2.3 (semantic-domain-cubes)

Milestone 3:
V2-2.3 ──► V2-3.1 (dual-delivery-infra) ──┬──► V2-3.2 (portal-api-gateway)
                                          └──► V2-3.3 (downstream-bi-rewire)

Milestone 4:
V2-2.3 + V2-3.1 ──► V2-4.1 (parity-recon-suite)
V2-1.2 + V2-2.1 ──► V2-4.2 (concurrency-acid-suite)
```

---

## Sliced Backlog by Milestone

### Milestone 1 — ACID Lakehouse Catalog & Storage Foundation
| # | Story / Ticket | Status | Blocked On | Touches |
|---|---|---|---|---|
| 1 | V2-1.1 Initialize DuckLake PostgreSQL Metadata Catalog | **DONE** | — | `version-two/ducklake/init_catalog.py`, `version-two/ducklake/schema.sql` |
| 2 | V2-1.2 Atomic Staging & Snapshot Commit Pipeline | **DONE** | — | `version-two/ducklake/reload_pipeline.py`, Snowflake/GCS stage |
| 3 | V2-1.3 Local Development Environment & GCS ADC Harness | **DONE** | — | `version-two/infra/docker-compose.dev.yml`, `version-two/infra/.env.example` |

### Milestone 2 — Unified Semantic Engine & Governance (Cube.js 1.7.x)
| # | Story / Ticket | Status | Blocked On | Touches |
|---|---|---|---|---|
| 4 | V2-2.1 Cube.js 1.7.x Core Engine with Embedded DuckDB & DuckLake Extension | **DONE** | — | `version-two/cube/package.json`, `version-two/cube/cube.js` |
| 5 | V2-2.2 Server-Enforced RBAC & Dynamic POPIA Masking Security Context | **DONE** | — | `version-two/cube/security.js`, `thin-web-app/role_assignments.json` |
| 6 | V2-2.3 Semantic Domain Cube Models & Multi-Table Join Graphs | **DONE** | — | `version-two/cube/model/*.js` |

### Milestone 3 — Dual Delivery Infrastructure & Consumer Integration
| # | Story / Ticket | Status | Blocked On | Touches |
|---|---|---|---|---|
| 7 | V2-3.1 Dual Delivery Deployment Topologies (Cloud Run REST + GCE VM SQL API) | **TODO** | — | `version-two/infra/Dockerfile`, `version-two/infra/cloudrun-rest.yaml`, `version-two/infra/gce-sql-systemd.service` |
| 8 | V2-3.2 Thin Web Portal Decoupled API Gateway | **TODO** | V2-3.1 | `version-two/portal/server.py`, `version-two/portal/auth.py` |
| 9 | V2-3.3 Downstream BI DirectQuery & Metabase Rewiring | **TODO** | V2-3.1 | `version-two/metabase/setup.py`, `docs/METABASE_CUBE_SQL.md` |

### Milestone 4 — Parity, ACID Concurrency & Verification Harness
| # | Story / Ticket | Status | Blocked On | Touches |
|---|---|---|---|---|
| 10 | V2-4.1 Automated Metric Parity Reconciliation Suite | **TODO** | V2-3.1 | `version-two/tests/test_metric_parity.py` |
| 11 | V2-4.2 Concurrency & Zero-Torn-Reads Verification Harness | **TODO** | — | `version-two/tests/test_concurrency_acid.py` |
