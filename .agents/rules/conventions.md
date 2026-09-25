# Project Conventions & Validation Standards

## Validation commands

- **Test command**: `cd thin-web-app && pytest`
- **Lint command**: `ruff check .` (or `flake8`)
- **Type-check command**: `mypy thin-web-app/`
- **Component test**: `cd thin-web-app && pytest tests/`

## Code Structure & Conventions

- **Thin Web App**: Python / FastAPI / Vanilla JS in `thin-web-app/`
- **Cube.js Layer**: Semantic layer models in `cube/`
- **Docs & Architecture**:
  - PRD: `thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md` or `docs/prd.md`
  - Execution Plan: `docs/EXECUTION_PLAN.md` or `docs/roadmap.md`
  - Tickets: `docs/tickets/`
  - Plans: `docs/plans/`
  - ADRs: `docs/adr/`
  - Kanban Dashboard: `docs/dashboard/`

## Commit & PR Format
- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- Always link the ticket ID (e.g. `feat(portal): US-1.1 role resolution from identity`)
