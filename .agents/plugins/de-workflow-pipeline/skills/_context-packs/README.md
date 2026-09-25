# Context packs

A context pack is source/domain-specific know-how that a `de-*` skill splices in
*only when selected* — so the core outer/inner loop stays generic and usable for
any engineering task, while migration- or platform-specific mechanics (a
particular discovery tool, a particular contract/gate system, a particular
source system's quirks) live in one place instead of being hardcoded into
every skill that might touch them.

## How a pack gets selected

`de-idea-prd` asks, as the first question of its first grilling round: *"Does
an existing context pack apply to this work, or is this generic?"* The answer
is written into `docs/prd.md`'s frontmatter as `Context Pack: <pack-name>` (or
`Context Pack: none`). Every downstream skill (`de-architecture`,
`de-slice-roadmap`, `de-prime-pipeline`, `de-plan-ticket`, `de-implement`,
`de-validate`, `de-review-changes`, `de-close-loop`) reads that field once at
the start of its own run and, if a pack is named, reads
`~/.agents/skills/_context-packs/<pack-name>.md` (or `~/.claude/skills/_context-packs/<pack-name>.md`) for this stage's
source-specific steps before proceeding with its generic process.

If no pack is named, every skill runs its fully generic process — no
project-specific tool or vendor assumption should ever surface in the
no-pack path.

## How a pack is authored

A pack is one markdown file, named `<pack-name>.md`, with one `##` section per
`de-*` skill it modifies. A skill only reads the section with its own name —
packs don't need every skill's section if there's nothing to add for that
stage. Format per section:

```markdown
## de-idea-prd

<what changes about this skill's process when this pack is active — extra
interview questions, a different discovery mechanism, etc.>

## de-architecture

...
```

A pack should:
- **Point at tools, not embed prose that duplicates them.** If the target
  project has its own `GEMINI.md`/`AGENTS.md`/`CLAUDE.md`/style guide/tribal-knowledge file, the pack
  says "read `<file>`" rather than copying its content in — packs go stale
  the moment the target project's own docs change.
- **Degrade to a reported gap, not a silent skip, when its tooling is
  missing.** If a pack names a CLI and that CLI isn't on `PATH`, the skill
  using the pack says so explicitly and asks the user how to proceed — it
  does not quietly fall back to the generic path as if the pack were never
  selected.
- **Never cause a skill to run something destructive or externally-visible
  without saying so first**, even if the underlying generic skill would
  normally treat the equivalent generic command as safe (e.g. a "build" or
  "compile" command is not guaranteed read-only in every project — a pack
  that knows a specific project has a live side-effecting hook should say
  so).

## Packs in this directory

None currently. Add a pack here when a recurring, source- or
platform-specific engineering-task shape comes up — a pack is worth creating
once the same source-specific mechanics would otherwise get copy-pasted into
a second initiative.
