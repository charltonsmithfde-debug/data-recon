# DE Workflow Pipeline Plugin

A production-grade **Antigravity Plugin** packaging the end-to-end autonomous Software Delivery Lifecycle (SDLC) outer & inner loop workflow, complete with lifecycle hooks, safety gates, and automatic Kanban board synchronization.

---

## What's Included

### 1. Skills (`skills/`)
- **Outer Loop**:
  - `de-idea-prd`: Interactive Socratic interview transforming raw ideas into structured PRDs with non-goals and acceptance criteria.
  - `de-architecture`: Turns PRD into architectural blueprints and Architecture Decision Records (ADRs).
  - `de-slice-roadmap`: Slices architecture into atomic tickets, establishes dependencies, and registers tickets on the Kanban board.
  - `de-run-full-workflow`: Orchestrates outer loop to inner loop execution.
- **Inner Loop (Per-Ticket)**:
  - `de-prime-pipeline`: Codebase reconnaissance and context priming prior to planning.
  - `de-plan-ticket`: Formulates atomic single-pass implementation plan.
  - `de-implement`: Step-by-step code implementation with incremental verification.
  - `de-validate`: Multi-dimension validation (lint, types, unit tests, contracts, dry-run).
  - `de-review-changes`: Pre-commit architectural and code quality review.
  - `de-ship-ticket`: Mandatory human checkpoint before committing and opening PR.
  - `de-close-loop`: Updates learnings and marks ticket shipped on the Kanban board.
- **Context Packs**:
  - `_context-packs/`: Reusable domain- and system-specific mechanics.

### 2. Lifecycle Hooks (`hooks.json`)
- `kanban-auto-sync` (`PostToolUse`): Automatically re-syncs the Kanban board whenever tickets, plans, or execution plans are updated.
- `ship-gate-safety` (`PreToolUse`): Intercepts `git push` and `gh pr create` with `force_ask` to enforce human approval before shipping.
- `workflow-stop-check` (`Stop`): Prevents the agent from stopping prematurely if tickets remain in mid-flight validation.

### 3. Rules (`rules/`)
- `de-workflow-gate.md`: Rigorous pipeline enforcement ensuring each stage transitions through the required sequence.

---

## Installation

### Option A: Install in Current Project Workspace (Recommended)
Run inside your project root:
```bash
python path/to/de-workflow-pipeline/install.py --workspace
```
Or simply copy the `de-workflow-pipeline` directory into `.agents/plugins/de-workflow-pipeline`.

### Option B: Install Globally for All Projects
```bash
python path/to/de-workflow-pipeline/install.py --global
```
Installs into `~/.agents/plugins/de-workflow-pipeline`.

---

## Verifying Discovery
Antigravity automatically discovers plugins in `.agents/plugins/` or `~/.agents/plugins/`. You can also explicitly declare it in `.agents/plugins.json`:
```json
{
  "entries": [
    {
      "path": ".agents/plugins/de-workflow-pipeline"
    }
  ]
}
```
