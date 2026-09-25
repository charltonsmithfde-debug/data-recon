---
name: de-slice-roadmap
description: Slices docs/architecture.md into a build roadmap of integration, component, feature, and interface tickets, each sized for one inner-loop pass, with a dependency graph, milestone grouping, User Stories, and seam identification per ticket. Publishes a live Scope Management dashboard (an Artifact with the db capability) seeded with every sliced ticket, and records its URL in docs/roadmap.md. Use after de-architecture, when docs/architecture.md exists but there's no roadmap/backlog yet, or when the user asks "what do we build first" or wants the work broken into tickets. Outer-loop skill: writes docs/roadmap.md and docs/tickets/*.md that de-prime-pipeline and de-plan-ticket consume per ticket, and every inner-loop skill updates ticket status.
---

# Slice architecture → roadmap → tickets → live dashboard

Turns `docs/architecture.md` into buildable, dependency-ordered tickets, each enriched with user stories and a
seam, and publishes a live dashboard so ticket status is visible in real time instead of only in a static file
nobody reliably re-reads mid-run. Each ticket must be completable in one inner-loop pass (prime → plan →
implement → validate → review → ship) by one session with fresh context.

## Read first

`docs/prd.md` and `docs/architecture.md`. If either is missing, stop and point to the earlier skill. If
`architecture.md` has a Component Inventory section, that inventory is the source of component-ticket nodes —
this skill orders them, it does not invent them (if there's no inventory and the architecture decomposes into
components, stop and point back to `de-architecture` rather than guessing component names here). Check
`docs/prd.md`'s `Context Pack:` field — no `de-slice-roadmap` section currently exists in any pack, but note it
in `docs/roadmap.md`'s frontmatter regardless, since every downstream inner-loop skill needs it.

## Ticket types

Classify every ticket as one of:
- **integration** — one external dependency, end to end: auth, data exchange, pagination/incremental logic
  where relevant, landing/normalizing the result, and a basic health/freshness check.
- **component** — one internal building block (a service, module, or transformation unit): input contract,
  logic, tests (correctness, edge cases, business-rule assertions), and documentation.
- **feature** — one user-facing capability that wires existing integrations/components together: scheduling,
  dependency wiring, retry and alerting policy where orchestration is involved.
- **interface** — one piece of how the system is consumed: a UI screen, an API route, a CLI command, or a
  webhook, with its own auth and rate limiting if applicable.
- **platform** — cross-cutting work that doesn't fit the above: environment setup, CI, the metering/billing
  hook, the observability dashboard itself.

Tag each ticket with its type — `de-prime-pipeline` and `de-validate` both use it to know what "done" checks
apply.

## Slicing rules

- One integration, one component, one feature, or one interface per ticket — not "build ingestion" as a single
  ticket.
- A ticket is one-pass-ready if: its inputs already exist (or are stubbed), its acceptance criteria are
  concrete and testable, and it doesn't require a decision `de-architecture` didn't already make. If a ticket
  still has an open architectural question, surface it now rather than letting an inner-loop session improvise.
- Group into milestones that each produce something demoable end-to-end (e.g. "one integration flowing through
  to one screen") rather than "all integrations, then all components, then all features" — the latter means
  nothing works until the very end.

### Ordering component tickets: derive from real structure, don't guess

For a codebase with a named component/transformation layer, don't order `component` tickets by reading the
architecture prose — build the actual dependency graph and topologically sort it:

1. **Existing nodes and edges** — pull the project's real dependency structure for every component already in
   the codebase (via the project's own dependency/build tooling, or by reading imports/references directly).
   This gives you the true edges for anything the new work touches or extends — don't re-derive these by hand,
   the codebase is authoritative and the architecture doc can be stale or wrong about what already exists.
2. **New nodes and edges** — add one node per row in architecture.md's Component Inventory, with edges from its
   declared `inputs` (which may point at existing nodes or at other new-inventory rows). A row's `decision`
   (new/extend/decompose) doesn't change how it's graphed — reuse rows without a row don't exist as nodes at
   all — but does decide the ticket's framing: `extend`/`decompose` rows are edits to something real, so scope
   the ticket to the delta, not a rewrite.
3. **Union the two graphs** and topologically sort. The resulting order is bottom-up by construction: sources
   → shared/foundational → composed/derived, with a new component never scheduled before something it reads
   from.
4. **Edited components pull in their existing children automatically** — if a Component Inventory row edits a
   component that already has downstream consumers in the codebase, those consumers are already nodes in the
   existing graph and come out the other side of the sort as impact-analysis tickets, even though
   architecture.md never mentioned them by name. Don't drop these; tag them clearly as "downstream of an edited
   component" so `de-prime-pipeline` knows the ticket is impact analysis, not new build.
5. A `feature` ticket depends on every `integration`/`component` ticket it wires together; an `interface`
   ticket depends on the components it queries. Fold these into the same sort rather than ordering them
   separately.

If the topological sort finds a cycle, stop — that's a real architecture defect (two components declared as
inputs to each other), not something to resolve by picking an arbitrary order.

## Per-ticket enrichment: User Stories + seam

Beyond type/acceptance-criteria/inputs/open-questions, every `docs/tickets/<id>-<slug>.md` also gets:

- **User Stories** — a long, numbered list, each in the form `As a <actor>, I want <feature>, so that
  <benefit>`. Cover all aspects of the ticket's slice, not just the happy path — e.g. for an integration
  ticket, include stories for the operator noticing a failed sync, not just the end consumer seeing fresh data.
  This should be extensive; a ticket with only one or two user stories probably hasn't had its scope examined
  closely enough.
- **Seam** — identify where this ticket will be tested/validated. Prefer an existing seam (a test harness, a
  validation entry point, a contract boundary already in the codebase) over inventing a new one; use the
  highest seam possible. If a new seam is genuinely needed, propose it at the highest point you can and name it
  explicitly — the fewer seams across the codebase, the better; one seam per ticket is the ideal.

Append these under `## User Stories` and `## Seam` in each ticket file, alongside the existing goal/acceptance
criteria/inputs/open-questions sections.

## Output: roadmap, tickets, and the live dashboard

1. `docs/roadmap.md` — milestones, and within each, the ticket list with type tags in the order the topological
   sort produced (text arrows for the actual edges: `integration-stripe → component-mrr → feature-daily-refresh
   → interface-mrr-api`), with impact-analysis tickets (edited component's existing downstream consumers)
   marked as such. Frontmatter includes `Context Pack:` (carried from `docs/prd.md`) and `Dashboard:` (the
   Artifact URL from the step below).
2. `docs/tickets/<id>-<slug>.md` per ticket: type, one-line goal, concrete acceptance criteria, inputs it
   depends on, open questions carried over from architecture, User Stories, and Seam.
3. **Publish the Scope Management dashboard** — mandatory, not optional, before handing off. See below.

## Publish the Scope Management dashboard

Publish **one Artifact or dashboard per roadmap/initiative**.

- **In Antigravity:** Generate a Scope Management Dashboard markdown artifact (or maintain the ticket board/table directly in `docs/roadmap.md` / `docs/dashboard.md`).
- **If running in an environment with the `ArtifactData` tool / DB capability (`capabilities: {db: {}}`):** The page renders a live ticket board/table that reads directly from the DB capability.

### Scope Management / Ticket Data schema

Whether written via `ArtifactData` or maintained directly in `docs/roadmap.md` and `docs/tickets/*.md`, use the following structure:ArtifactData` before first use):

- **`tickets`** collection — one document per ticket, doc id = the ticket id (e.g. `t001`), fields:
  - `id`, `slug`, `title`, `type` (integration/component/feature/interface/platform)
  - `milestone` (the milestone name from `docs/roadmap.md`)
  - `status` — one of `todo | priming | planning | implementing | validating | reviewing | ready_to_ship |
    blocked_env | blocked_code | shipped`
  - `why` — the current-stage reason, one line (e.g. "implementing step 3 of 5" or "blocked: verification
    command exited 2")
  - `what` — the ticket's goal, one line, from the ticket file
  - `blocked_by` — array of ticket ids this one depends on that aren't yet `shipped`
  - `updated_at` — ISO timestamp of the last status write
  - `pr_url` — set once `de-ship-ticket` opens a PR
  - `ticket_file_path` — `docs/tickets/<id>-<slug>.md`
  - `checklist` — array of `{name, passed}` from `de-validate`'s applicable checks for this ticket
- **`project`** collection — a single document, doc id `main`, fields:
  - `prd_link`, `architecture_link` (paths to `docs/prd.md`/`docs/architecture.md`)
  - `milestones` — array of milestone names in order
  - `percent_done` — derived: `shipped` ticket count / total ticket count, recomputed on every write
  - `context_pack` — the active pack name or `none`

Seed both collections/tables now, right after slicing: one entry per sliced ticket with `status: "todo"`, and the project summary doc (via `ArtifactData` if available, or initialized in `docs/roadmap.md` and `docs/tickets/*.md`).

Record the published Artifact's URL in `docs/roadmap.md`'s frontmatter as `Dashboard:` once published. Tell the
user the dashboard link directly — this is the primary live view of scope going forward, not a nice-to-have.

Every inner-loop skill (`de-prime-pipeline` through `de-close-loop`) writes its own status/why/what/checklist
update to this same dashboard before handing off to the next skill — see each skill's own "Update the dashboard"
step. `de-slice-roadmap` only creates and seeds it once per roadmap.

Confirm the milestone order with the user. Then either hand off to `de-run-full-workflow` to build the whole
roadmap, or point at the first ticket with `de-prime-pipeline` to start the inner loop by hand.
