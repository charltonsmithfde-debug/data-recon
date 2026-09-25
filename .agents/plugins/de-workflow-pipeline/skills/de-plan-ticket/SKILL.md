---
name: de-plan-ticket
description: Turns a primed ticket into a one-pass-ready implementation plan for an integration, component, feature, or interface - concrete steps, the contract in and out, and the validation checks that will prove it's done. Use right after de-prime-pipeline, or whenever the user asks to plan a ticket before writing code. Inner-loop skill: writes the plan the agent then executes literally in de-implement. Writes this ticket's planning status to the Scope Management dashboard before handing off.
---

# Plan a ticket

Produces a plan specific enough that `de-implement` executes it without re-deciding anything. Planning here is
cheap; a wrong implementation is not.

## Prerequisite

Run `de-prime-pipeline` first if this session hasn't already primed on the ticket. If planning surfaces a need
to look at a file the priming pass didn't cover, go back to the project's structural lookup (an existing code
index, or the component's declared dependencies) to find it rather than grepping blind — the read list should
always trace back to a real dependency edge.

## Plan contents, by ticket type

**integration**
- Auth method and where credentials come from (env var name, secrets manager key — never hardcode).
- Access method: full refresh vs incremental (what's the cursor/watermark field?), pagination strategy,
  rate-limit handling (backoff policy), and idempotency (what happens on a re-run of the same window?).
- Exact normalized shape: field names, types, and how source fields map to them.
- Failure modes to handle explicitly: source returns a partial/malformed response, source is down, the response
  shape changed.

**component**
- Input dependencies and the shape/assumptions being relied on.
- Logic in plain terms before code — the "what" before the "how."
- Incremental strategy if applicable (what's the incremental key, how are late-arriving updates handled?).
- Tests to add: correctness on keys/invariants, contract checks against upstream, at least one business-rule
  assertion specific to this component (e.g. "total is never negative").

**feature**
- Task/step list and the dependency edges between them.
- Retry policy per step and what "the feature failed" alerts on vs. what's expected transient noise.
- Backfill/reprocessing behavior: can this be safely re-run for a past window without side effects (duplicate
  writes, double-charged API calls)?

**interface**
- Request/response contract, including error responses.
- Auth/rate-limit approach (match existing sibling interfaces unless the ticket says otherwise).
- Access plan against the datastore/service and expected latency at current scale.

**platform**
- Scope tightly to the acceptance criteria in the ticket; don't let a platform ticket balloon into
  re-architecture — if it needs to, stop and flag it rather than improvising.

## Every plan also states

- **Validation plan**: which of the checks in `de-validate` apply and any ticket-specific one to add (e.g. a
  specific sanity check for this source).
- **Rollback**: how to undo this if it ships broken (revert migration, feature-flag off, re-run backfill).
- **Out of scope**: what this ticket deliberately does not do, so `de-implement` doesn't scope-creep.

## Context pack

If `docs/prd.md` names a context pack, read `~/.agents/skills/_context-packs/<pack>.md` (or `~/.claude/skills/_context-packs/<pack>.md`)'s `## de-plan-ticket`
section for this stage's source-specific steps (e.g. a domain-specific contract format the plan must satisfy
before implementation may start) before proceeding. If the pack names a required CLI and it isn't on `PATH`,
report that gap to the user explicitly rather than silently skipping the pack's steps.

## Update the dashboard

Before handing off, write this ticket's status to the Scope Management dashboard (via `ArtifactData` if available, or update `docs/roadmap.md` and the ticket file in `docs/tickets/<id>-<slug>.md` directly): set `status` to `planning`, `why` to a short note, and
`updated_at`.

## Output

Plan posted in chat, and saved to `docs/tickets/<id>-<slug>.md` under a `## Plan` section (append, don't
overwrite the ticket's goal/acceptance criteria/User Stories/Seam). For a pack-backed ticket, the pack's own
accepted contract artefact (if any) is the authoritative plan artefact — the prose section summarizes it, it
doesn't replace it. Confirm with the user before `de-implement` starts, especially if you had to make a
judgment call the ticket didn't specify.
