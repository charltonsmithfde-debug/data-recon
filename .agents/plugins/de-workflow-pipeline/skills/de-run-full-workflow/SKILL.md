---
name: de-run-full-workflow
description: Chains the whole software delivery workflow end-to-end from a single idea or feature description - PRD, architecture, roadmap, then the inner loop (prime, plan, implement, validate, review, ship) for each ticket, closing the loop after every merge - reporting progress via the Scope Management dashboard and distinguishing real code failures from environmental blocks so it never loops indefinitely on either. Use when the user wants to go from an idea straight to a shipped/buildable product, or says "build this end to end" / "run the whole workflow". For a single already-scoped ticket, use the inner-loop skills directly instead of this orchestrator.
---

# Run the full workflow: idea → ship

The orchestrator. Chains the outer-loop planning skills once, then runs the inner loop per ticket, closing the
loop after each merge. Confirm scope with the user before running unattended — this can produce a lot of
tickets and a lot of PRs.

## Sequence

1. **Outer loop, once:**
   - `de-idea-prd` — if `docs/prd.md` doesn't already exist or the user has a new idea. This is where the
     context pack (if any) gets selected — every subsequent step in this run reads `docs/prd.md`'s
     `Context Pack:` field rather than re-asking.
   - `de-architecture` — if `docs/architecture.md` doesn't already exist.
   - `de-slice-roadmap` — if there's no roadmap/tickets yet. This is also where the Scope Management dashboard
     gets published — `docs/roadmap.md`'s `Dashboard:` frontmatter has its URL. Share that URL with the user
     now; it's the live view for the rest of this run.

   Pause after each and get explicit confirmation before moving to the next — these are the expensive-to-
   reverse decisions. Don't chain through them silently even in "full workflow" mode.

2. **Ask the user how much of the roadmap to build now**: everything, just the first milestone, or just the
   first ticket. Roadmaps can be long; don't assume "all of it" without asking.

3. **Inner loop, per ticket, in dependency order from `docs/roadmap.md`:**
   ```
   de-prime-pipeline → de-plan-ticket → de-implement → de-validate
        → de-review-changes → de-ship-ticket → de-close-loop
   ```
   Each of these steps writes its own status update to the dashboard as it runs (see each skill's "Update the
   dashboard" step) — this orchestrator doesn't need to write dashboard state itself, only read it back for
   progress reporting.

   **Retry logic — FAIL and BLOCKED_ENV are handled differently, on purpose:**
   - `de-validate` returning **FAIL** (a real code defect): loop back to `de-implement` for that ticket. Track a
     per-ticket FAIL count. Only after **two genuine FAILs in a row on the same ticket** does this stop and ask
     a human — a single FAIL is normal inner-loop iteration, not a signal something is systemically wrong.
   - `de-validate` returning **BLOCKED_ENV** (couldn't run a check — environment/connectivity, not a code
     defect): **do not retry.** Escalate to the human immediately, once, with what's blocked and why. Retrying
     an environmental block burns time and context without new information, and repeated BLOCKED_ENV must never
     be miscounted as repeated FAIL — they are different problems requiring different responses (a human fixing
     the environment vs. a human reviewing the code).
   - Don't let a FAILing or BLOCKED_ENV ticket block downstream tickets from even starting if they're
     independent (no dependency edge on the stuck one) — but don't mark the stuck ticket shipped either, and
     reflect its real status (`blocked_code` after two FAILs, `blocked_env` on a block) on the dashboard.
   - If `de-review-changes` finds a blocking issue, resolve it before `de-ship-ticket`.
   - Report progress after each ticket ships: what shipped, what's next, running total against the milestone —
     point at the dashboard URL alongside the prose summary rather than trying to restate full ticket state in
     chat.

4. **Between tickets**, re-check `docs/learnings.md` — `de-close-loop` may have just added something (or
   edited a skill) that changes how the next ticket should be primed or planned. This is the outer loop
   actually doing its job within a single orchestrated run.

5. **Stop conditions**: the requested scope (one ticket / one milestone / everything) is shipped, a ticket
   fails validation twice in a row (genuine FAIL, not BLOCKED_ENV) and needs human judgment, or any ticket
   returns BLOCKED_ENV — surface it and pause rather than looping indefinitely on either.

## Output

A running log of what shipped (PR links), what was learned, and what remains on the roadmap, plus the dashboard
URL as the live source of truth for full ticket state. At the end, summarize: milestone status (cross-check
against the dashboard's `project.percent_done` rather than just counting in chat), any open questions or ADR
changes accumulated along the way, and the next recommended ticket if the run stopped short of the full
roadmap.
