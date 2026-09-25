---
trigger: always_on
---

# Software Delivery Lifecycle Rules: The de-* Pipeline

All software engineering, architectural modifications, and ticket implementations in this repository MUST strictly follow the `de-*` workflow from idea to ship.

## 1. Outer Loop (System & Ticket Definition)

1. **Idea to PRD (`de-idea-prd`)**:
   - Do NOT start implementation or architectural design from raw requests without a PRD in `docs/prd.md` (or `thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md`).
   - Identify whether an existing Context Pack applies (e.g., from `~/.agents/skills/_context-packs/`).
   - **Gate 1 (Human Checkpoint)**: Always verify problem statements, non-goals, and scope boundaries with the user before proceeding.

2. **Architecture & ADRs (`de-architecture`)**:
   - Turn the PRD into an architecture blueprint (`docs/architecture.md`).
   - Record consequential technical decisions as Architecture Decision Records (`docs/adr/*.md`).
   - **Gate 2 (Human Checkpoint)**: Discuss trade-offs with the user; do not silently decide database, contract, or auth architecture.

3. **Roadmap & Slicing (`de-slice-roadmap`)**:
   - Slice the architecture into atomic tickets in `docs/tickets/<id>-<slug>.md` and register them in `docs/roadmap.md` or `docs/EXECUTION_PLAN.md`.
   - Update the Kanban board (`docs/dashboard/kanban-data.json`).
   - **Gate 3 (Human Checkpoint)**: Confirm execution batch scope (single ticket, milestone, or full roadmap).

---

## 2. Inner Loop (Per-Ticket Execution)

Every ticket MUST strictly traverse the inner loop in sequence:

```
[Prime] -> [Plan] -> [Implement] -> [Validate] -> [Review] -> [Human Gate Ship] -> [Close Loop]
```

1. **Prime (`de-prime-pipeline`)**:
   - Orient in the relevant codebase subset before planning or touching code.
   - Set ticket status to `priming` on the Kanban board.
2. **Plan (`de-plan-ticket`)**:
   - Write a single-pass implementation plan in `docs/plans/<ticket-id>-plan.md`.
   - Set ticket status to `planning` on the Kanban board.
3. **Implement (`de-implement`)**:
   - Follow the plan step by step with incremental validation.
   - Set ticket status to `implementing` on the Kanban board.
4. **Validate (`de-validate`)**:
   - Run the full validation suite: lint, type-check, unit tests, contract checks, and representative input dry-run.
   - Return one verdict: `PASS`, `FAIL`, or `BLOCKED_ENV`.
   - Set ticket status to `validating` on the Kanban board.
5. **Review (`de-review-changes`)**:
   - Perform pre-commit technical review (idempotency, schema/contract compatibility, blast radius).
   - Set ticket status to `ready_to_ship` if clean, or back to `implementing` if blocking issues exist.
6. **Ship Ticket (`de-ship-ticket`) - MANDATORY HUMAN GATE**:
   - **NEVER automatically commit or open a PR without explicit user confirmation.**
   - Present the summary: what was changed, test evidence, PR title/body, and breaking changes.
   - Only on explicit user approval: commit conventionally and open the PR.
7. **Close Loop (`de-close-loop`)**:
   - Update `docs/learnings.md`, mark ticket `shipped` in `docs/EXECUTION_PLAN.md` / `docs/roadmap.md` and the Kanban dashboard.

---

## 3. Kanban Dashboard & Document Traceability

1. Every ticket, plan, spec, ADR, and PR must remain linked in `docs/dashboard/kanban-data.json` and viewable via [docs/dashboard/index.html](docs/dashboard/index.html).
2. Whenever modifying tickets, roadmap, or execution plan, run `python scripts/sync_kanban.py` to ensure the Kanban board reflects real-time status.
