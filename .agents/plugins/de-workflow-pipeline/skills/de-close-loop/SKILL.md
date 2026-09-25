---
name: de-close-loop
description: After a ticket's PR merges, updates docs/learnings.md, ADRs, roadmap status, and the Scope Management dashboard, and - if the same kind of problem showed up twice - edits the relevant SKILL.md itself so the next inner-loop session doesn't rediscover it. Use right after a PR merges, when the user says "that's merged, what's next", or periodically to catch up learnings from several merged tickets at once. Outer-loop skill: this is what makes ticket 40 easier than ticket 4.
---

# Close the loop

This is the skill that makes the outer loop real. Without it, every inner-loop session starts from zero no
matter how many tickets have shipped. State must land in files, not stay in this session's context.

## Steps

1. **Mark the ticket done** in `docs/roadmap.md` and note the PR link on `docs/tickets/<id>-<slug>.md`.

2. **Extract learnings**, not a changelog. Ask: did anything in this ticket surprise the implementer — an
   undocumented API quirk, a flaky test that needed a specific fix, a contract assumption that turned out
   wrong, a review finding that wasn't obvious going in? If yes:

   **If `docs/prd.md` names a context pack**, check `~/.agents/skills/_context-packs/<pack>.md` (or `~/.claude/skills/_context-packs/<pack>.md`)'s
   `## de-close-loop` section — a pack may prefer recording the surprise as an executable regression case in
   its own domain-specific system over a plain `docs/learnings.md` entry when the surprise is the kind of thing
   a deterministic or judgment check could have caught (not a one-off). That still doesn't replace step 3
   below — a pack-recorded lesson is also worth checking for a repeated pattern.

   Otherwise (or in addition, for the narrative a future session needs even after a pack-specific case exists),
   append a short entry to `docs/learnings.md`:
   ```
   ## <date> — <ticket id/slug>
   **Component:** <integration/component/feature/interface name>
   **What happened:** <the surprise, in one or two sentences>
   **What to do differently:** <the actionable fix — what should the next session do>
   ```
   If nothing surprising happened, don't pad the file — an empty entry is noise a future session has to read
   past.

3. **Check for a repeated pattern.** Read the last several `docs/learnings.md` entries. If the same kind of
   issue has shown up more than once (e.g. two different integrations both got pagination wrong the same way,
   or two reviews both caught the same missing idempotency check), that's a signal the *skill*, not just the
   docs, should change:
   - Edit the relevant `SKILL.md` (e.g. add a specific check to `de-plan-ticket` or `de-validate`) so the
     class of mistake is caught before it happens next time, not just recorded after.
   - Note the edit in `docs/learnings.md` so it's visible why the skill changed.

4. **Update ADRs if this ticket invalidated one.** If implementation revealed that an architectural decision
   in `docs/adr/` doesn't hold (e.g. the chosen incremental strategy doesn't actually handle late data), don't
   silently work around it in code — update the ADR's Consequences section or open a new ADR that supersedes
   it, and flag to the user that this may affect other planned tickets.

5. **Update the dashboard.** Write this ticket's final status to the Scope Management dashboard (via `ArtifactData` if available, or update `docs/roadmap.md` and the ticket file in `docs/tickets/<id>-<slug>.md` directly): confirm `status` is `shipped`, clear
   `blocked_by` on any ticket that was waiting on this one, and update `updated_at`. This is also a good moment
   to re-check `project.percent_done` reflects reality.

6. **Report what's next.** Based on `docs/roadmap.md`'s dependency graph (and the dashboard's `blocked_by`
   fields), name the next unblocked ticket.

## Output

Updated `docs/roadmap.md`, `docs/learnings.md`, the dashboard, and possibly a `SKILL.md` or ADR. A one-line
status to the user: what shipped, what was learned, what's next.
