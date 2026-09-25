---
name: de-idea-prd
description: Interviews the user from a raw idea, OR from an already-known replication/migration target (an existing system, object, or codebase to replicate or migrate, optionally under a context pack), into a problem-first PRD. Uses round-based grilling and live domain-modeling to reach a shared understanding rather than a fixed question script. Use this at the very start of a new product/capability, or of a migration/parity project, whenever the user describes an idea, a pain point, a system to replace, or says things like "I want to build a tool that...", "we need to migrate X off Y", or "help me plan a product". Do not use for a single bug fix or small ticket — that's de-plan-ticket. Outer-loop skill: writes docs/prd.md that everything downstream depends on.
---

# Idea → PRD

This is step one of the outer loop. The output is `docs/prd.md`: intent and constraints, never engineering
decisions (stack, schema, framework choices belong to `de-architecture`).

## Method: round-based grilling, not a fixed script

Don't ask the topic checklist below in a fixed top-to-bottom order. Instead, work it as a **design tree**: every
decision branches into the decisions that hang off it. The topic checklist (problem, dependencies, scale,
sensitivity, consumption, correctness, non-goals, success metric — or the replication-target topics further
down) is the question *bank* the frontier draws from, not a script to read verbatim.

Each round:

1. Compute the **frontier** — every question whose prerequisites are already settled, i.e. everything you can
   ask *now* without guessing at an answer you haven't heard yet.
2. Ask the whole frontier in one round, numbered, each with your recommended answer:

   ```
   ❓ **Q1** - **<question title>**: <question body>

   ➡️ <your recommended answer>

   ---

   ❓ **Q2** - **<question title>**: <question body>

   ➡️ <your recommended answer>
   ```
3. Wait for the user's answers. Recompute the frontier — settled answers unblock questions that depended on
   them — and ask the next round. A question whose answer depends on another question still open this round
   belongs to a *later* round.
4. **Finding facts is your job, never the user's.** When a frontier question needs a fact from the environment
   (an existing file, a codebase), go find it yourself — dispatch a sub-agent, or grep/read the codebase
   directly — rather than asking the user for something you could look up. Don't block the round on it: only
   the questions that depend on that fact wait; ask the rest of the frontier now.

The interview is done when the frontier is empty — every branch of the design tree visited, nothing left
silently assumed. Don't draft `docs/prd.md` until the user has confirmed a shared understanding.

## Round 1, question 1, always

Before any other question, round 1 always opens with:

**"Does an existing context pack apply to this work, or is this generic?"**

List the packs currently in `~/.agents/skills/_context-packs/ (or ~/.claude/skills/_context-packs/)` (read that directory's README for the current
list) as options. Store the answer as `Context Pack: <pack-name>` (or `Context Pack: none`) in `docs/prd.md`'s
frontmatter — every downstream skill reads this field once and, if a pack is named, splices in that pack's
section for its own stage.

**If a pack is named**, read `~/.agents/skills/_context-packs/<pack-name>.md` (or `~/.claude/skills/_context-packs/<pack-name>.md`)'s `## de-idea-prd` section now and
use its topics/questions for the rest of this interview instead of the generic ones below — the pack section is
authoritative for this stage when active. If the pack names a required CLI or tool and it isn't available,
that's a reported gap: tell the user and ask how to proceed, don't silently fall back to the generic path.

**If no pack applies (`none`)**, continue with the modes below.

## Two modes — pick one before interviewing (no-pack path)

**Greenfield product** — the target isn't decided yet; you're discovering what to build and for whom. Use the
market-shaped questions in the next section.

**Replication-target mode** — the user already knows what they want to accomplish: an existing system, object,
report, process, or codebase they want a portion of replicated or migrated. There's often no buyer to interview
and no market/consumption model to invent — the risk is silent drift or missing parity against something users
already trust, not market fit.

If genuinely unsure which mode applies, ask one question: *"Is there an existing system, object, or codebase
this replaces, extends, or replicates?"* — yes means replication-target mode.

## Why software PRDs need more than "who's the user, what's the job"

*(Greenfield mode only — skip this and the interview below if you're in replication-target mode.)*

A generic PRD asks "who is the user, what's the job to be done." A build-ready PRD needs that *plus* questions
that determine the entire shape of the system before a line of architecture is drawn:
- What external systems, services, or data sources does this depend on, who owns them, and can you actually get
  access during dev?
- What's the expected scale (users, requests/day, data volume)? This alone decides whether you're building a
  simple CRUD app or something that needs real capacity planning — get it wrong and the architecture step is
  wasted.
- Is there sensitive data in scope (PII, credentials, financial, health)? This decides compliance posture (SOC2,
  HIPAA, GDPR) before a single schema is designed.
- Who consumes the output — end users in a UI, another system via API/webhook, or a downstream process? This
  decides whether you're building a product or an integration.
- What's "correct"? Systems fail silently — stale data, duplicate writes, drifted contracts — in ways that
  don't throw exceptions. Nail down what monitoring/alerting means for this product before implementation starts.

## Question bank (greenfield mode)

Draw the frontier from these topics, adapting based on answers already given:
- **Problem**: What breaks or is painful today without this product? For whom, specifically?
- **Users & buyer**: Who uses it day to day and who pays for it? Often different people.
- **External dependencies**: What systems, services, or data does this rely on (APIs, databases, files, event
  streams, third-party providers)? Who owns access? Any dependencies not available yet?
- **Scale**: Rough scale today and at 12 months (users, requests, data volume). Does staleness/latency break the
  value prop?
- **Sensitivity & compliance**: PII/PHI/PCI in scope? Data residency requirements? Existing compliance
  obligations (SOC2, HIPAA) that constrain vendor/infra choice?
- **Output & consumption**: UI, API, export, webhook, integration into another system — be specific, this drives
  the interface-layer decision later.
- **Correctness & freshness bar**: What does "it's working correctly" mean for this product? What's an
  acceptable staleness/latency window? What should trigger an alert?
- **Non-goals**: What are you explicitly not building in v1? Scope-creeps faster than most software — nail this
  down.
- **Success metric**: One or two numbers that tell you this shipped and worked.

Draft `docs/prd.md` with these sections: Context Pack (frontmatter), Problem, Users, External Dependencies &
Access, Scale/Performance Requirements, Sensitivity & Compliance, Consumption Model, Correctness Definition,
Non-Goals, Success Metrics, Open Questions.

## Question bank (replication-target mode, no pack)

For "migrate this off X," "replicate capability Y," or any change against an existing system: the risk is
*what exactly* is being replaced, *what proves it was replaced correctly*, and *what's explicitly out of scope
this wave*. Skipping this is how a migration ships something that looks right and drifts wrong for months.

Draw the frontier from:
- **Source object(s) / system**: what exactly is being replicated? Discover the real touchpoint set by exploring
  the existing codebase directly (grep/read it, or your own project's code-search tooling if configured) rather
  than asking the user to enumerate touchpoints by hand. (A context pack may name a more specific discovery tool
  for its domain — that only applies when the pack is selected.)
- **Current consumers**: what depends on this today? Anyone consuming the source object directly, outside the
  known consumer?
- **Why now**: what's driving the change (a decommission date, performance, a new capability the legacy system
  can't support)? A hard deadline changes how much parity risk is acceptable to carry.
- **Parity / correctness bar**: what must reconcile to the source, on what measure, and within what tolerance?
  Name the measure and tolerance here, not improvised at build time.
- **Known quirks**: does the implementer already know of gotchas in the source (a hidden filter, a conversion
  step, an edge case)? Capture them now — this is exactly what `docs/learnings.md`/tribal-knowledge docs exist
  to prevent re-discovering the hard way.
- **Cutover & rollback**: run the new path in parallel with the old for a period, or replace outright? What
  happens if reconciliation fails after cutover?
- **Non-goals**: which parts of the source are explicitly *not* being carried over this wave? Migrations
  scope-creep by "just include this other thing too" — name what's excluded.
- **Success metric**: concretely — a variance threshold, a sign-off condition. Not "it's migrated."

Draft `docs/prd.md` with: Context Pack (frontmatter), Source Object(s) & Owner, Touchpoint Inventory (summarized
by kind, call out anything that couldn't be resolved by name), Current Consumers, Motivation/Deadline, Parity &
Reconciliation Requirement, Known Quirks / Tribal Knowledge, Cutover & Rollback Plan, Non-Goals, Success
Metrics, Open Questions. (No Users/Buyer, Compliance, or Consumption Model sections — those are already answered
by the fact that this lands in an existing system.)

## Live domain modeling — run this during the interview, not after

As terms get resolved during the interview, don't wait until the PRD is drafted to write them down:

- **Update `CONTEXT.md` inline**, the moment a term is resolved — not batched. If no `CONTEXT.md` exists yet,
  create it when the first term is resolved. It is a glossary only — no implementation details, no scratch pad.
- **Challenge fuzzy or conflicting terms immediately.** If the user uses a term that conflicts with `CONTEXT.md`,
  or is vague/overloaded ("account" — Customer or User?), stop and ask which precise meaning they mean before
  moving on.
- **Stress-test relationships with concrete scenarios** when a domain relationship comes up — invent an edge
  case and force precision about the boundary.
- **Cross-reference against real code** when the user states how something works and a codebase already exists
  — read the actual code, not just the user's or your own prose — surface any contradiction rather than trusting
  it.
- **Offer an ADR only when all three hold**: hard to reverse, surprising without context, and the result of a
  real trade-off. If any is missing, skip it — most PRD-stage decisions won't clear this bar; `de-architecture`
  is where most real ADRs get written.

## Draft, then confirm

1. **Capture what's already been said.** If the idea, target, or constraints are already in the conversation,
   extract them into the relevant round's answers — don't re-ask what's already answered.
2. Run the grilling rounds above until the frontier is empty.
3. Draft `docs/prd.md` per the section list for the active mode/pack.
4. **Confirm with the user** before moving on. Flag anything you inferred vs. anything the user stated directly.

## Output

`docs/prd.md` (with the `Context Pack:` frontmatter field always present), `CONTEXT.md` kept current live, and
a short summary in chat. Do not propose a tech stack, schema, or architecture here — that's next. If the user
wants to keep going, say the next step is `de-architecture`.
