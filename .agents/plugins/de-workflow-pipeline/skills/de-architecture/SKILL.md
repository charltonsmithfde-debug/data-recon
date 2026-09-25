---
name: de-architecture
description: A working session that turns a PRD into a concrete software architecture - external integrations, storage, core components, workflow orchestration, interfaces, auth/billing, and observability - with trade-offs and risks made explicit, live domain-modeling against CONTEXT.md as decisions are made, and each real decision recorded as an ADR. Use after de-idea-prd, whenever docs/prd.md exists but docs/architecture.md doesn't, or when the user asks to design/plan the stack, pick a datastore, or figure out "how" to build the product. Outer-loop skill: writes docs/architecture.md and docs/adr/*.md that de-slice-roadmap and every de-plan-ticket session depend on.
---

# Architecture

Turns `docs/prd.md` into `docs/architecture.md`: how it gets built, not just what. This is a working session,
not a monologue — surface trade-offs and get the user to decide, don't silently pick for them on anything
consequential.

## Read first

`docs/prd.md`. If it doesn't exist, stop and say so — point to `de-idea-prd`. Check its `Context Pack:` field —
if a pack is named, read `~/.agents/skills/_context-packs/<pack-name>.md` (or `~/.claude/skills/_context-packs/<pack-name>.md`)'s `## de-architecture` section now;
it may replace or sharpen the generic Existing Component Audit below for this pack's domain. If the user already
stated a stack ("we're on Postgres + Node + React"), skip straight to component design for the remaining gaps
instead of re-litigating the stack.

If most components are already decided by an existing project (an established datastore, framework,
multi-tenancy model, auth/billing already live), don't re-run the full checklist — confirm those are unchanged
in one line each and spend the session on whatever component the PRD actually requires a new decision on.

## Live domain modeling — run this throughout the session, not just at PRD time

As architecture decisions get made, keep sharpening the domain model rather than treating `CONTEXT.md` as
something PRD-stage already finished:

- **Challenge terms against `CONTEXT.md`** as they come up in this session — if a decision uses a term that
  conflicts with the glossary, or is vague/overloaded, stop and pin down the precise meaning before deciding.
- **Cross-reference decisions against real code** rather than assuming prose (the PRD's or the user's) is
  accurate — if a decision assumes something exists or behaves a certain way, read the actual codebase to
  verify it before finalizing the component decision.
- **Update `CONTEXT.md` inline** the moment a term is settled during this session, not batched at the end.
- The existing ADR gate (below, under Output) is shared with this discipline — no separate gate to apply.

## Components to work through

For each, name the options, the trade-off that actually matters for *this* PRD (not a generic pros/cons list),
and get a decision:

1. **External integrations** — for each external dependency in the PRD: pull (scheduled API/DB access) vs push
   (webhooks, events) vs manual/file-based. Real-time vs batch, driven by the freshness requirement already
   captured. Note rate limits, auth methods, and pagination/retry quirks per integration — these are where
   integrations actually break.
2. **Storage** — primary datastore(s), schema shape, and where raw/unprocessed data lands if there's an
   ingestion step. Decide the retention policy now; it's expensive to bolt on later.
3. **Core components** — where business logic lives (services, modules, a transformation layer). How
   incremental updates and backfills/reprocessing work, if relevant. How upstream contract changes propagate
   without silently breaking downstream components.

   If the system decomposes into named components (services, modules, or an equivalent transformation layer)
   **and the target already has an existing codebase**, naming the components is not a transcription exercise —
   a source object (an existing endpoint, table, or report) rarely maps 1:1 onto one new component. Do the
   **Existing Component Audit** below *before* drafting the Component Inventory; the inventory is its output,
   not an independent list.

   ### Existing Component Audit (required before the Component Inventory, when a codebase already exists)

   If `docs/prd.md` has a Touchpoint Inventory (from `de-idea-prd`'s replication-target mode), that's the object
   list to audit — not just the top-level object named in the PRD. If a context pack is active (`docs/prd.md`'s
   `Context Pack:` field) and its `~/.agents/skills/_context-packs/<pack-name>.md` (or `~/.claude/skills/_context-packs/<pack-name>.md`) has a `## de-architecture`
   section, that section's domain-specific audit mechanics (e.g. how to walk from a data object to the process
   that populates it, or repo-specific layering rules) take precedence over the generic steps below — read it
   now. Generically, for each object:
   1. **Find what already reads from it.** Search the codebase (grep, or your project's own code-search tooling
      if configured) for existing consumers of the same upstream source. An existing component already reading
      this source means step one of the migration is "reuse," not "build."
   2. **Find what already covers this responsibility.** Check for an existing component that already represents
      part of what the source object computes — a shared abstraction the codebase already has a hard rule
      against duplicating, or an existing component at a compatible level this could extend instead of
      recomputing. Read the target project's own style guide / tribal-knowledge docs for prior decisions about
      this source or a sibling one.
   3. **Decide, per source object, one of:** *reuse as-is* (no new component — the existing one already covers
      it), *extend* (add a field, check, or hook to an existing component), *decompose* (the source object's
      logic splits across a new component, a new join/aggregation step, and an *existing* component it builds on
      rather than duplicates), or *new build* (genuinely nothing exists yet). "New build" should be the
      exception, not the default, once the audit is actually done.
   4. **Place it in the right repo/project**, if the codebase spans more than one. A context pack may name
      specific layering rules here (see its `## de-architecture` section); otherwise use the target project's
      own documented conventions. Decide the repo and whether a wrapper/adapter is required now, not during
      `de-implement`.

   Only then produce the **Component Inventory**: one row per component this decides to *touch* — new,
   extended, or reused-with-a-caveat (a reused component with no changes doesn't need a row) — with
   `name, layer (e.g. ingestion/domain/aggregation/presentation), one-line responsibility, inputs (sources or
   other components it depends on), decision (new/extend/decompose), repo (if multi-repo)`. This is an
   architecture decision, not a scheduling one: responsibility, layer, and *which existing components to build
   on rather than duplicate* are exactly the kind of thing that's expensive to reverse later, so decide them
   here, at a rough-cut level — `de-plan-ticket` will formalize the full contract (interfaces, tests,
   expectations) per component later. `de-slice-roadmap` cannot invent this list or redo this audit; it only
   orders what this inventory (plus the existing project's real structure) already contains. For an extended
   component, list it once here — its existing downstream consumers are picked up automatically, not
   re-declared by hand.
4. **Workflow / orchestration** — scheduler or job-runner, retry and backfill/reprocessing semantics, how
   failure of one step is isolated from others, alerting on missed schedules or SLAs.
5. **Interfaces** — matches the PRD's consumption model: a UI for end users, a query/API layer for other
   systems, webhooks for push. Auth model for each interface.
6. **Multi-tenancy** — if this serves multiple customers/orgs: shared schema with a tenant column, schema per
   tenant, or database per tenant. This decision is expensive to reverse — spend real time here, driven by the
   compliance/isolation requirements from the PRD.
7. **Auth & billing** — how users/customers authenticate, how usage is metered if pricing is usage-based —
   metering has to be designed alongside the core components, not bolted on after.
8. **Observability** — run/job status, data or behavior quality checks (freshness, volume anomalies, contract
   drift), and where alerts go. This is not optional for a production system; decide the minimum viable version
   now.
9. **Environments** — how dev/staging differ from prod, especially what data is available in dev without
   touching real customer data (synthetic/sampled/masked).

## Risk pass

Before finalizing, explicitly list: what's the riskiest unknown (an API you haven't tested, a scale estimate
that's a guess, a compliance requirement not yet confirmed)? What would change the architecture if that
assumption is wrong? Put these in the PRD's Open Questions if they're not resolved.

## Output

- `docs/architecture.md` — component diagram (describe it in text/ASCII), the decision and reasoning for
  each component above, and the risk list. Include the Component Inventory table as its own section if the
  core-components step produced one.
- `docs/adr/NNN-<slug>.md` — one per consequential, hard-to-reverse decision (multi-tenancy model, datastore
  choice, orchestration choice). Format: Context, Decision, Consequences, Alternatives considered.

Confirm with the user before handing off. Next step is `de-slice-roadmap`.
