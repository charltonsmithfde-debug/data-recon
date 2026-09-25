---
name: de-review-changes
description: Pre-commit technical review of a change, scoped to the risks generic code review misses - idempotency, backfill/reprocessing safety, PII/PHI handling, cost blast radius, and breaking contract changes for downstream consumers. Use after de-validate returns PASS, or whenever the user asks to review a diff before committing. Inner-loop skill. Reads project conventions (.agents/rules/conventions.md or .claude/references/conventions.md) if present. Writes this ticket's review status to the Scope Management dashboard before handing off.
---

# Review changes

A second pass with fresh eyes before it becomes a commit, focused specifically on what generic review misses.

## What to check, beyond normal code quality

- **Idempotency & re-run safety** — if this integration, component, or feature step runs twice for the same
  input (retry, backfill, manual re-run), does it duplicate data, double-charge an API's rate limit, or produce
  a different result the second time? Any of those is a real finding, not a nitpick.
- **Backfill/reprocessing blast radius** — if someone reprocesses this for the last 90 days, what does that
  cost (API calls, compute) and does anything downstream assume "today's data only" in a way that breaks?
- **PII/PHI/sensitive-data handling** — does this change introduce, move, or expose a sensitive field without
  the masking/encryption/access-control the PRD's compliance section called for? Check even when the ticket
  wasn't explicitly about compliance — sensitive fields travel through systems quietly.
- **Breaking changes to downstream consumers** — does a contract change here (renamed/removed/retyped field)
  break something outside this repo (a customer's query, another team's dashboard)? If `de-validate` already
  flagged this, confirm it's called out in the PR description, not silently absorbed.
- **Secrets and credentials** — nothing hardcoded, correct secrets-manager/env-var usage, and least-privilege
  scoping on any new credential this change introduces.
- **Cost** — does this change materially increase compute, API call volume, or storage (e.g. a full-refresh
  where an incremental would do)? Flag it even if it's a defensible trade-off — the human should decide with
  eyes open.
- **Alignment with the plan** — does the diff match `docs/tickets/<id>-<slug>.md`'s plan and stay within its
  stated scope? Flag unplanned scope creep even if the extra work is good.

## Process

1. Read `.agents/rules/conventions.md` (or `.claude/references/conventions.md`) if present for house style.
2. Read the diff plus the ticket's plan.
3. List findings by severity: **blocking** (must fix before commit), **should-fix** (fix now if cheap, else
   note for a follow-up), **note** (worth knowing, not worth blocking on).
4. If a `code-reviewer` subagent exists in `.agents/agents/` or `.claude/agents/`, hand the deep pass to it; otherwise do the review
   inline as above.

## Context pack

If `docs/prd.md` names a context pack, read `~/.agents/skills/_context-packs/<pack>.md` (or `~/.claude/skills/_context-packs/<pack>.md`)'s `## de-review-changes`
section for this stage's source-specific steps (e.g. re-running a domain-specific regression/failure library
before human sign-off, or a specific gate-close command) before proceeding. If the pack names a required CLI
and it isn't on `PATH`, report that gap to the user explicitly rather than silently skipping the pack's steps.

## Update the dashboard

Before handing off, write this ticket's status to the Scope Management dashboard (via `ArtifactData` if available, or update `docs/roadmap.md` and the ticket file in `docs/tickets/<id>-<slug>.md` directly): set `status` to `ready_to_ship` (no blocking findings) or back to
`implementing` (blocking findings, returning to `de-implement`), `why` to a short note, and `updated_at`.

## Output

A findings list by severity, posted in chat. Hand to `de-ship-ticket` if there are no blocking findings. If
there are, fix them (back to `de-implement`) or explicitly get the user's sign-off to defer a should-fix item —
don't silently drop findings.
