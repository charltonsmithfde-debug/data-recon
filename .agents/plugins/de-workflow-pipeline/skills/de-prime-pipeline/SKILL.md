---
name: de-prime-pipeline
description: Orients the agent in the relevant part of a codebase - the specific integration, component, feature, or interface and its neighbors - before planning or implementing a ticket. Use at the start of any inner-loop pass on a ticket from docs/tickets/, or whenever the user says "start working on <ticket>" or picks up a scoped task. Inner-loop skill: loads only the context that ticket needs, not the whole repo. Consults an existing code index (if one exists) before any grep, glob, or ad-hoc file read. Writes this ticket's priming status to the Scope Management dashboard before handing off.
---

# Prime: orient on the relevant slice of the codebase

Loads exactly the context a ticket needs — no more. A full-repo read wastes the context budget this session
has for planning and implementing.

## Structure first — cheaper than blind search

Never start orienting with a speculative Read across the whole codebase. If the project has an existing code
index, dependency graph, or lineage export (e.g. a build tool's dependency graph, a language server, or any
other structural tool already wired into this project), consult it first and read only the specific files it
points you to — a structural lookup is cheaper and more accurate than grepping blind. If no such tool exists,
grep/glob for the ticket's named component and its direct neighbors instead of reading broadly.

Which structure to consult depends on the ticket type:

- **integration / feature / interface / platform** → find the file(s) matching this ticket's named component,
  walk one hop of dependencies in each direction (what it imports/calls, what imports/calls it), and note those
  file paths. That's your read list — don't grep beyond it unless something is clearly missing.
- **component** → find the component's definition, its declared inputs (what it depends on) and whatever
  references it downstream. That's your read list for step 3 below.

## Steps

1. **Read the ticket.** `docs/tickets/<id>-<slug>.md` for goal, acceptance criteria, ticket type
   (integration/component/feature/interface/platform), and dependencies.

2. **Read `docs/architecture.md` for the relevant component only** — the external-integrations section for an
   integration ticket, the core-components section for a component ticket, etc. Skip the rest.

3. **Trace the contract**, using the read list from the structural lookup above rather than searching for it.
   Depending on ticket type:
   - *integration*: what does the external system actually return (sample a real or documented payload if
     possible)? What's the normalized shape it must produce on this side?
   - *component*: what upstream components does it depend on, what are their current contracts and any
     documented assumptions (nullability, shape, freshness)? Read the components one hop upstream, not the
     whole graph.
   - *feature*: what pieces already exist that this feature needs to wire together — read their entry points
     and current configuration/dependencies, not their internals.
   - *interface*: what does it call into, and what's the existing auth/rate-limit pattern used by sibling
     interfaces (match it, don't invent a new one)?

4. **Check `docs/learnings.md`** (if it exists) for anything tagged with this source, component, or feature —
   past gotchas (a quirky edge case, a flaky test, a contract-drift incident) `de-close-loop` recorded. This is
   the whole point of the outer loop: don't rediscover a known problem.

5. **Check `.agents/rules/conventions.md` (or `.claude/references/conventions.md`)** for naming, folder structure, and testing conventions if
   present.

6. **Summarize back to the user** in a few lines: what you now understand the ticket to require, what
   upstream/downstream it touches, and any risk or ambiguity spotted before planning starts. Surface
   ambiguity now — it's cheap here and expensive after implementation.

## Context pack

If `docs/prd.md` names a context pack, read `~/.agents/skills/_context-packs/<pack>.md` (or `~/.claude/skills/_context-packs/<pack>.md`)'s `## de-prime-pipeline`
section for this stage's source-specific steps before proceeding. If the pack names a required CLI and it isn't
on `PATH`, report that gap to the user explicitly rather than silently skipping the pack's steps.

## Update the dashboard

Before handing off, write this ticket's status to the Scope Management dashboard (via `ArtifactData` if available, or update `docs/roadmap.md` and the ticket file in `docs/tickets/<id>-<slug>.md` directly): set `status` to `priming`, `why` to a short note (e.g. "primed,
touches 3 upstream components"), and `updated_at`.

## Output

A short primed-context summary in chat. No files written (outside a context pack's own state, if opened above).
Hand off to `de-plan-ticket` next.
