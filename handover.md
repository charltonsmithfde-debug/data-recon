# Session Handover — Version 2.0 (`data-recon`)

| | |
|---|---|
| **Last Updated** | 2026-09-25 |
| **Branch / HEAD** | `main` (`b625787` + `V2-3.3`) |
| **Workflow Framework** | `de-*` Software Delivery Lifecycle ([`.agents/rules/de-workflow-gate.md`](./.agents/rules/de-workflow-gate.md)) |
| **Overall Progress** | **9 / 11 Tickets Shipped (81.8%)** — Milestones 1, 2 & 3 Complete |
| **Next Ticket** | **`V2-4.1`** ([`docs/tickets/V2-4.1-parity-recon-suite.md`](./docs/tickets/V2-4.1-parity-recon-suite.md)) |

---

## 1. Executive Summary & Current State

We are executing the **Version 2.0 Architecture** (Unified ACID Lakehouse & Semantic Metric Layer with DuckLake + Cube.js 1.7.x) defined in [`docs/prd.md`](./docs/prd.md) and [`docs/architecture.md`](./docs/architecture.md).

### Completed in Previous Sessions
1. **Outer Loop (100% Complete)**:
   - **Gate 1 (PRD)**: Approved in [`docs/prd.md`](./docs/prd.md).
   - **Gate 2 (Architecture & ADR)**: Authored [`docs/architecture.md`](./docs/architecture.md) and [`docs/adr/0004-dual-delivery-topologies.md`](./docs/adr/0004-dual-delivery-topologies.md).
   - **Gate 3 (Roadmap & Slicing)**: Sliced 11 atomic tickets across 4 milestones in [`docs/roadmap.md`](./docs/roadmap.md) and `docs/tickets/V2-*.md`. Archived legacy V1 plan to [`docs/EXECUTION_PLAN_V1_LEGACY.md`](./docs/EXECUTION_PLAN_V1_LEGACY.md) and wired [`scripts/sync_kanban.py`](./scripts/sync_kanban.py) to sync [`docs/dashboard/kanban-data.json`](./docs/dashboard/kanban-data.json).
2. **Milestone 1 — ACID Lakehouse Catalog & Storage Foundation (100% Complete)**:
   - **`V2-1.1` (`4f6f9cb`)**: DuckLake PostgreSQL metadata catalog DDL ([`version-two/ducklake/schema.sql`](./version-two/ducklake/schema.sql)) and idempotent bootstrapper ([`version-two/ducklake/init_catalog.py`](./version-two/ducklake/init_catalog.py)) registering all 44 migrated mart tables (`647,792,599` rows) in Snapshot `v1`.
   - **`V2-1.2` (`8f5cd10`)**: Atomic staging & snapshot commit pipeline ([`version-two/ducklake/reload_pipeline.py`](./version-two/ducklake/reload_pipeline.py)) with pre-commit row-count/URI guards, time-travel snapshot queries, and single-transaction rollback.
   - **`V2-1.3` (`daa5368`)**: Local PostgreSQL 16 catalog compose stack on port `5433` ([`version-two/infra/docker-compose.dev.yml`](./version-two/infra/docker-compose.dev.yml)), zero-secret template ([`version-two/infra/.env.example`](./version-two/infra/.env.example)), and GCS ADC validator ([`version-two/infra/adc_harness.py`](./version-two/infra/adc_harness.py)).
3. **Milestone 2 — Unified Semantic Engine & Governance (100% Complete)**:
   - **`V2-2.1` (`2109686`)**: Cube.js 1.7.x core engine with `@duckdb/node-api` embedded driver, `httpfs` + `ducklake` startup SQL (`ATTACH 'ducklake:postgres:...' AS lake`), and port 4000 readiness server ([`version-two/cube/package.json`](./version-two/cube/package.json), [`version-two/cube/cube.js`](./version-two/cube/cube.js)).
   - **`V2-2.2` (`e8e5dc0`)**: Server-enforced RBAC & dynamic POPIA masking security context ([`version-two/cube/security.js`](./version-two/cube/security.js)) with HS256 JWT verification, HTTP 403 cube boundary checks, salted SHA-256 PII dimension redaction (`id_number`, `member_id`, `client_name`), and constant-time `scrypt` SQL API credential verification.
   - **`V2-2.3` (`2fa4169`)**: Validated Cube 1.7.x semantic domain models and join graphs ([`version-two/cube/model/AnnuityQuotation.js`](./version-two/cube/model/AnnuityQuotation.js), [`version-two/cube/model/InvestmentAnalysis.js`](./version-two/cube/model/InvestmentAnalysis.js), [`version-two/cube/model/MemberAnalysis.js`](./version-two/cube/model/MemberAnalysis.js), [`version-two/cube/model/SharedDimensions.js`](./version-two/cube/model/SharedDimensions.js), [`version-two/cube/model/index.js`](./version-two/cube/model/index.js)).
4. **Milestone 3 — Dual Delivery Infrastructure & Consumer Integration (100% Complete)**:
   - **`V2-3.1` (`776ee77`)**: Production multi-stage `Dockerfile` (`node:22-bookworm-slim`), Cloud Run REST manifest (`version-two/infra/cloudrun-rest.yaml`), GCE VM SQL API systemd unit (`version-two/infra/gce-sql-systemd.service`), and dual-delivery REST (`4000`) + SQL API (`5432`) server in `version-two/cube/cube.js`.
   - **`V2-3.2` (`b625787`)**: Decoupled Thin Web Portal API Gateway (`version-two/portal/auth.py`, `version-two/portal/server.py`) with `X-Goog-Authenticated-User-Email` IAP verification, `role_assignments.json` RBAC lookup, HS256 JWT minting, and live Cube REST `/cubejs-api/v1/load` queries replacing synthetic endpoints.
   - **`V2-3.3`**: Downstream BI DirectQuery & Metabase rewiring (`version-two/metabase/setup.py`, `docs/METABASE_CUBE_SQL.md`) enforcing `scbi-cube-sql:5432` connectivity, storage-bypass guards, and IAP TCP tunneling (`gcloud compute start-iap-tunnel scbi-cube-sql 5432`).

---

## 2. Immediate Next Steps (Milestone 4)

Begin **Milestone 4: Parity, ACID Concurrency & Verification Harness**:

| Order | Ticket ID | Spec | Status | Blocked On |
|---|---|---|---|---|
| **1 (Next)** | **`V2-4.1`** | [`docs/tickets/V2-4.1-parity-recon-suite.md`](./docs/tickets/V2-4.1-parity-recon-suite.md) | `TODO` | — (Unblocked) |
| **2** | **`V2-4.2`** | [`docs/tickets/V2-4.2-concurrency-acid-suite.md`](./docs/tickets/V2-4.2-concurrency-acid-suite.md) | `TODO` | — (Unblocked) |

---

## 3. Mandatory `de-*` Inner-Loop Protocol

Per [`.agents/rules/de-workflow-gate.md`](./.agents/rules/de-workflow-gate.md), **every ticket** must strictly traverse the inner loop in order:

```text
[Prime] -> [Plan] -> [Implement] -> [Validate] -> [Review] -> [Human Gate Ship] -> [Close Loop]
```

1. **Prime (`de-prime-pipeline`)**: Read the ticket in `docs/tickets/<id>.md`, orient in relevant code, and set status to `PRIMING` in `docs/roadmap.md` and the ticket file.
2. **Plan (`de-plan-ticket`)**: Create `docs/plans/<id>-plan.md` and set status to `PLANNING`.
3. **Implement (`de-implement`)**: Set status to `IMPLEMENTING` and build the deliverables + automated tests.
4. **Validate (`de-validate`)**: Set status to `VALIDATING`, run syntax checks, unit/contract tests, and a representative dry-run.
5. **Review (`de-review-changes`)**: Verify idempotency, POPIA/RBAC security invariants, zero hardcoded secrets, and set status to `READY_TO_SHIP`.
6. **Ship (`de-ship-ticket`) — MANDATORY HUMAN GATE**:
   - **NEVER commit automatically.** Present the validation summary and ask the user via `ask_question` before running `git commit`.
7. **Close Loop (`de-close-loop`)**: Mark ticket `DONE` in `docs/roadmap.md`, `docs/tickets/<id>.md`, and `docs/plans/<id>-plan.md`, unblock downstream tickets, append any new insights to [`docs/learnings.md`](./docs/learnings.md), and commit conventionally.

---

## 4. Environment & Sandbox Quirks (Read First to Save Time)

1. **Python Binary & Test Runner**:
   - The environment provides `/usr/bin/python3` (there is no `python` alias and no global `pytest` package).
   - Always write Python test suites using standard library `unittest.TestCase` so they run zero-dependency via:
     ```bash
     python3 -m unittest discover -s version-two/tests -p "test_*.py" -v
     ```
2. **Git Commits in Sandbox**:
   - The `.git/` directory is mounted read-only inside the default command sandbox (`fatal: Unable to create '.../.git/index.lock': Read-only file system`).
   - When committing after human gate approval, call `run_command` with `BypassSandbox: false` first, then retry the exact command with `BypassSandbox: true` (keeping `toolAction` and `toolSummary` identical).
3. **Kanban Sync Hook (`.agents/hooks.json`)**:
   - [`scripts/sync_kanban.py`](./scripts/sync_kanban.py) runs automatically after every file edit via `PostToolUse`.
   - Antigravity hooks parse `stdout` as `protojson` (expecting `{}`). Keep human-readable logs on `sys.stderr` and `{}` on `sys.stdout` if editing `scripts/sync_kanban.py`.
4. **Port Allocation Contract**:
   - `5433`: Local DuckLake PostgreSQL 16 catalog (`docker-compose.dev.yml`)
   - `5432`: Cube.js SQL API (Postgres wire protocol for Power BI / Excel / DBeaver / Metabase)
   - `4000`: Cube.js REST API (Thin Web Portal & AI Agents)
   - `8000`: Thin Web Portal HTTP Server

---

## 5. Key Repository Reference Map

- **Core Governance Docs**:
  - PRD: [`docs/prd.md`](./docs/prd.md)
  - Architecture Blueprint: [`docs/architecture.md`](./docs/architecture.md)
  - ADR-0004 (Dual Delivery Topologies): [`docs/adr/0004-dual-delivery-topologies.md`](./docs/adr/0004-dual-delivery-topologies.md)
  - Roadmap & Backlog: [`docs/roadmap.md`](./docs/roadmap.md)
  - Kanban Data: [`docs/dashboard/kanban-data.json`](./docs/dashboard/kanban-data.json)
  - Learnings Log: [`docs/learnings.md`](./docs/learnings.md)
- **Version 2.0 Implementation (`version-two/`)**:
  - DuckLake Catalog & Reload Pipeline: [`version-two/ducklake/`](./version-two/ducklake/)
  - Local Dev & Cloud Infra: [`version-two/infra/`](./version-two/infra/)
  - Automated Test Suite: [`version-two/tests/`](./version-two/tests/)
- **Version 1.0 Reference Assets (for RBAC & Metric Parity in Milestones 2–4)**:
  - RBAC Role Assignments (`EXECUTIVE`, `FINANCE_PII`, `DISTRIBUTION`, `RESTRICTED`): [`thin-web-app/role_assignments.json`](./thin-web-app/role_assignments.json)
  - V1 Thin Web Portal & Query Registry: [`thin-web-app/server.py`](./thin-web-app/server.py)

---

## 6. Quick Verification Command for New Session

Run this first in the new session to confirm the workspace is clean and all 12 Milestone 1 tests pass:

```bash
git status -s && python3 -m unittest discover -s version-two/tests -p "test_*.py" -v
```
