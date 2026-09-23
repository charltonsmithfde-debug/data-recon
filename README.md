# data-recon

Replication and reconciliation of the `pbi-scbi` Power BI semantic models (SC BI, currently on
Snowflake via DirectQuery) into an open, self-hosted lakehouse stack: **DuckLake / DuckDB on
Google Cloud Storage**, fronted by a **Cube.js** headless semantic layer, and served through
**Metabase** dashboards and a lightweight custom web portal.

## Layout

| Path | What it is |
|---|---|
| `cube/` | Cube.js semantic layer (RBAC, PII masking, pre-aggregations) and its Cloud Run / VM deploy scripts |
| `metabase/` | Metabase deployment scripts |
| `thin-web-app/` | Portal front end being rebuilt per `thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md` — see that PRD and `docs/EXECUTION_PLAN.md` for current status |
| `web/` | Standalone reconciliation engines (member, annuity, investment, telemetry) and a legacy web UI |
| `scripts/` | Migration, provisioning, and transpilation scripts (PBI/DAX → DuckLake SQL), plus `scripts/blocked/` — infra changes that are drafted but deliberately not yet run |
| `docs/` | Architecture guide, execution plan, ADRs, and the user manual |
| `tests/` | RBAC and model tests |

## Key docs

- `docs/PBI_TO_DUCKLAKE_REPLICA_GUIDE.md` — end-to-end architecture and migration blueprint
- `docs/EXECUTION_PLAN.md` — authoritative story status and resume protocol for the portal rebuild
- `docs/USER_MANUAL.md` — how to use the deployed stack
- `docs/adr/` — architecture decision records

## Notes

- `data/` and generated/large artifacts (parquet snapshots, DuckDB files) are git-ignored; they
  are not part of this repo's history.
- `scripts/blocked/` contains credential-rotation scripts that are reviewed but intentionally not
  executed yet — read each script's header before running it.
