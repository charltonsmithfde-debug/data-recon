---
name: de-implement
description: Executes a de-plan-ticket plan step by step for an integration, component, feature, or interface, validating as it goes rather than writing everything then testing once at the end. Use right after de-plan-ticket, or when the user says "implement it" / "build this" with a plan already in hand. Inner-loop skill. Writes this ticket's implementation status to the Scope Management dashboard before handing off.
---

# Implement

Executes the plan in `docs/tickets/<id>-<slug>.md` literally. If reality diverges from the plan (an API returns
something the plan didn't account for, a dependency doesn't exist as assumed), stop and say so rather than
silently improvising — a small deviation compounds by validation time.

## Steps

1. **Work the plan's steps in order.** After each step that produces runnable code (a function, a component,
   a task definition), run it against a small/sample input before moving to the next step — don't write the
   whole integration or component and test once at the end. Catching a contract mismatch after step 2 is cheap;
   catching it after step 8 means re-deriving which step introduced it.

2. **Follow existing conventions**, don't introduce new patterns for something the codebase already has a
   pattern for (retry decorator, logging setup, config loading). Check `.agents/rules/conventions.md` (or `.claude/references/conventions.md`) and
   sibling files of the same ticket type.

3. **Handle the failure modes the plan named explicitly** — don't leave a bare `except: pass` where the plan
   said "handle rate limit with backoff." If a failure mode turns out to be harder to handle than planned,
   flag it rather than dropping it silently.

4. **Write the tests the plan specified** as you go, not as an afterthought — for a `component` ticket in
   particular, the correctness/contract tests are part of the deliverable, not optional extra credit.

5. **Keep the diff scoped to the ticket.** If you notice an unrelated issue, note it (for `docs/learnings.md`
   later via `de-close-loop`, or a follow-up ticket) instead of fixing it inline and inflating the diff.

## Context pack

If `docs/prd.md` names a context pack, read `~/.agents/skills/_context-packs/<pack>.md` (or `~/.claude/skills/_context-packs/<pack>.md`)'s `## de-implement`
section for this stage's source-specific steps (e.g. moving a domain-specific ticket state machine into a
"build" state before writing code, or running a fast deterministic check after each edit) before proceeding. If
the pack names a required CLI and it isn't on `PATH`, report that gap to the user explicitly rather than
silently skipping the pack's steps.

## Update the dashboard

Before handing off, write this ticket's status to the Scope Management dashboard (via `ArtifactData` if available, or update `docs/roadmap.md` and the ticket file in `docs/tickets/<id>-<slug>.md` directly): set `status` to `implementing`, `why` to a short note (what step
is done / in progress), and `updated_at`.

## Output

Working code plus its tests, matching the plan. Report back: what was implemented, anything that diverged from
the plan and why, and anything flagged as out of scope. Hand off to `de-validate` next — do not consider a
ticket done just because code was written.
