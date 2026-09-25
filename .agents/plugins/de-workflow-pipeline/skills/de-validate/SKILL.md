---
name: de-validate
description: Runs the full validation suite for a ticket - unit tests, lint/type-check, contract checks, data/behavior-quality assertions, and a dry run against representative input - and returns one PASS/FAIL/BLOCKED_ENV verdict. Use right after de-implement, before de-review-changes, or whenever the user asks to check/test/validate an integration, component, feature, or interface. Inner-loop skill. Writes this ticket's verdict/checklist to the Scope Management dashboard before handing off.
---

# Validate

Returns one verdict: **PASS**, **FAIL**, or **BLOCKED_ENV**, with evidence. "Tests pass" is necessary but not
sufficient — this skill checks the things that let a real defect through even when unit tests are green.

## Three verdicts, not two

- **PASS** — every applicable check ran and passed.
- **FAIL** — a check ran and found a real defect in the code/component/integration. This is what loops back to
  `de-implement`.
- **BLOCKED_ENV** — a check *could not run* because of environment/connectivity (a service unreachable, a
  credential expired, a required CLI missing, a sandbox restriction) — not because the code is wrong. **Never**
  collapse this into FAIL; it is not evidence of a defect and treating it as one sends `de-implement` chasing a
  bug that doesn't exist. Always surface a BLOCKED_ENV to the human explicitly and immediately — it never
  silently counts toward any retry counter (`de-run-full-workflow` treats it differently from FAIL for exactly
  this reason).

If some checks PASS and one is BLOCKED_ENV, report both: which checks passed with evidence, and which one is
blocked and why. Don't let a clean partial result read as an unqualified PASS.

## Read first

Check `docs/prd.md`'s `Context Pack:` field. If a pack is named and
`~/.agents/skills/_context-packs/<pack-name>.md` (or `~/.claude/skills/_context-packs/<pack-name>.md`) has a `## de-validate` section, that section's checks
*supersede*, not supplement, the generic checks below for the ticket types it covers — read it now and follow
it instead where it applies.

## Standard checks (every ticket type)

Fill these in once, per project, in `.agents/rules/conventions.md` (or `.claude/references/conventions.md`) (lint/type-check/test commands) — this
skill reads them from there rather than shipping placeholders:

```
<lint command from project conventions (.agents/rules/conventions.md or .claude/references/conventions.md)>            # e.g. ruff check ., eslint .
<type-check command from project conventions (.agents/rules/conventions.md or .claude/references/conventions.md)>      # e.g. mypy ., tsc --noEmit
<unit test command from project conventions (.agents/rules/conventions.md or .claude/references/conventions.md)>       # e.g. pytest, npm test
```

If `.agents/rules/conventions.md` (or `.claude/references/conventions.md`) doesn't name these commands yet, don't guess silently — ask the user
once for the project's real lint/type-check/test commands, then write them into
`.agents/rules/conventions.md` (or `.claude/references/conventions.md`) so future runs don't re-ask. If a command can't be run at all because a
required tool isn't installed or reachable, that's BLOCKED_ENV for that check, not FAIL.

All must pass for PASS. If any fails with real output, verdict is FAIL — report the failure, don't attempt to
fix it here (that's back to `de-implement`).

## Type-specific checks

**integration**
- Run it against a real or recorded sample response, not just mocked-happy-path data.
- Verify idempotency: run the same access window twice, confirm no duplicate records land (or that upserts
  correctly overwrite).
- Verify pagination actually terminates and doesn't drop the last/first page.
- Confirm rate-limit handling triggers correctly (simulate a 429 if the source supports it, or review the
  backoff logic directly).

**component**
```
<component test command from project conventions (.agents/rules/conventions.md or .claude/references/conventions.md)>   # e.g. project's own test/build-select command
```
- All contract/correctness tests pass (uniqueness, not-null, referential integrity, accepted-values, or your
  stack's equivalents).
- The business-rule assertion from the plan passes against real or representative data, not just fixtures.
- Output sanity: result count/shape is in a plausible range given the input — a component that silently drops
  90% of records should fail this even if every named test passes.
- If incremental: run it twice back to back and confirm no duplication, and confirm a late-arriving update is
  handled per the plan.

**Live-dependency caveat**: if running these commands could touch a live external system (a hook, a metered
API call), confirm with the user before running them rather than assuming a "test"/"build" command is safely
read-only — some projects wire side effects into commands that look inert. A context pack may name a specific
known hook for its target project (check its `## de-validate` section); absent that, ask rather than assume.

**feature**
- Dry-run/backfill the feature for a small historical window in a non-prod environment. Confirm it completes
  and confirms idempotency (re-running the same window doesn't duplicate downstream effects).
- Confirm a single step's induced failure doesn't cascade in ways the plan didn't intend (isolated retry vs.
  full restart, as designed).

**interface**
```
<interface test command from project conventions (.agents/rules/conventions.md or .claude/references/conventions.md)>   # e.g. pytest tests/api, newman run collection.json
```
- Contract matches the plan: response shape, status codes, error format.
- Auth and rate limiting behave as sibling interfaces do.
- Performance is sane at current scale (no unnecessary full scan introduced where an index/partition should be
  used).

## Contract-drift / breaking-change check (integration and component tickets)

Diff the new contract against the previous one. If a field was removed, renamed, or had its type narrowed
(e.g. nullable → non-null in a way that could break existing consumers, or a widening that changes semantics),
flag it explicitly as a **breaking change** even if all tests still pass — tests often don't cover downstream
consumers that aren't in this repo.

## Update the dashboard

Before handing off, write this ticket's result to the Scope Management dashboard (via `ArtifactData` if available, or update `docs/roadmap.md` and the ticket file in `docs/tickets/<id>-<slug>.md` directly): set `status` to `validating` while checks run, then on
completion to `reviewing` (PASS), `implementing` (FAIL — back to `de-implement`), or `blocked_env`
(BLOCKED_ENV), update `why` with a one-line reason, `checklist` with each check's `{name, passed}`, and
`updated_at`.

## Output

One of:
- **PASS** — all applicable checks above passed (or a context pack's composite check exited its PASS code).
  List what was run.
- **FAIL** — list exactly which check failed and the evidence (the actual error, counts, diff, or command
  output). Do not soften a FAIL into "mostly passes."
- **BLOCKED_ENV** — list exactly which check couldn't run and why (missing tool, unreachable service, expired
  credential). Say explicitly this is not evidence of a defect, and ask the user how to proceed rather than
  guessing.

Hand a PASS to `de-review-changes` next. On FAIL, hand back to `de-implement`. On BLOCKED_ENV, stop and escalate
to the user — do not retry automatically.
