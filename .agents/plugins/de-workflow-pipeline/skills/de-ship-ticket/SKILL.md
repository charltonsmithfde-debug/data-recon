---
name: de-ship-ticket
description: Presents a mandatory human checkpoint with the ready-to-ship summary, then - only on explicit confirmation - commits a validated, reviewed change as one atomic conventionally-tagged commit and opens a real pull request describing what shipped, how it was validated, and any breaking-change or migration notes. Use after de-review-changes has no blocking findings, or when the user says "commit this" / "open a PR". Inner-loop skill, last step before de-close-loop.
---

# Ship a ticket: human checkpoint, then commit + PR

The last inner-loop step. Nothing here commits or pushes without an explicit human go-ahead first — this is
the mandatory human-in-the-loop checkpoint before every ticket ships, not a formality to click through.

## Prerequisites

`de-validate` returned PASS and `de-review-changes` has no unresolved blocking findings. If either hasn't run
this session, run them first rather than skipping straight to shipping.

## Mandatory human checkpoint — before touching git

Before running any commit/push command, present the ready-to-ship summary and stop for explicit confirmation.
Do not proceed on an assumption that silence or a general "continue with the plan" from earlier in the session
counts as shipping approval — this checkpoint needs its own explicit answer.

Present:
- **What shipped**: the ticket's goal, in one sentence, and what the diff actually does.
- **Validation evidence**: `de-validate`'s verdict and the checks that produced it (test names, counts,
  dry-run evidence) — quote it, don't paraphrase away the specifics.
- **Review findings**: `de-review-changes`'s findings list, and how each was resolved (fixed, or explicitly
  deferred with prior user sign-off).
- **Manual verification script**, if `.agents/rules/conventions.md` (or `.claude/references/conventions.md`) names one for this ticket type — name
  it and ask whether the user wants to run it themselves before shipping, or has already.

Then use `AskUserQuestion` (not a plain question the user might scroll past, and not proceeding by default) to
get an explicit yes/no: ship now, hold for changes, or hold for the user to run their own manual check first.
Only a "ship" answer moves to Commit below.

## Commit

- One atomic commit for the ticket (squash working commits if there were several exploratory ones).
- Conventional, tagged message (`feat(integration): add Stripe incremental extraction`,
  `fix(component): correct MRR calc for mid-month cancellations`) — follow
  `.agents/rules/conventions.md` (or `.claude/references/conventions.md`) if it specifies a different format.
- Commit body notes anything a future `git blame` reader needs: why an approach was chosen if non-obvious,
  and any known follow-up left out of scope.

## Pull request

Push the branch and open a PR with a real body, not a placeholder:

- **What & why** — the ticket's goal in a sentence, link to `docs/tickets/<id>-<slug>.md`.
- **How it was validated** — the checks `de-validate` ran and their results (counts, test names, dry-run
  evidence) — reviewers should be able to trust the PASS without re-deriving it. If `docs/prd.md`'s
  `Context Pack:` field names a pack and its `~/.agents/skills/_context-packs/<pack-name>.md` (or `~/.claude/skills/_context-packs/<pack-name>.md`) has a
  `## de-ship-ticket` section, follow it for any pack-specific verdict/artefact to quote here.
- **Breaking changes / migration notes** — explicit callout if `de-validate` or `de-review-changes` flagged a
  contract change or cost increase. Don't bury this in the diff.
- **Rollback plan** — one line, from the plan in the ticket.

## Update the dashboard

Write this ticket's result to the Scope Management dashboard (via `ArtifactData` if available, or update `docs/roadmap.md` and the ticket file in `docs/tickets/<id>-<slug>.md` directly): set `status` to `shipped`, `pr_url` to the opened PR's URL, `why` to a short "shipped,
PR #N" note, and `updated_at`. This is what lets `project.percent_done` and the dashboard view reflect reality
without a separate reporting pass.

## Output

Commit hash and PR URL/number, reported to the user. If a required-reviewers list exists in
`.agents/rules/conventions.md` (or `.claude/references/conventions.md`), request them. After merge, the next step is `de-close-loop` — say so.
