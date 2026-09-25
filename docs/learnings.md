# Engineering Learnings & Outer-Loop Retrospective

## 2026-09-25 — V2-1.1-ducklake-catalog-init
**Component:** `version-two/ducklake/` (DuckLake Metadata Catalog)
**What happened:** System Python (`/usr/bin/python3`) in the isolated sandbox environment does not have `pytest` or a `python` binary alias pre-installed; only `python3` and standard library `unittest` are guaranteed available out of the box. Additionally, Antigravity `PostToolUse` lifecycle hooks parse `stdout` strictly as `protojson` (expecting `{}`), so any diagnostic text printed to `stdout` causes hook unmarshaling errors.
**What to do differently:**
1. Always write test suites inheriting from `unittest.TestCase` so they run identically under both `python3 -m unittest` and `pytest`.
2. In lifecycle hook scripts (`scripts/sync_kanban.py`), send human-readable status logs to `sys.stderr` and output `{}` to `sys.stdout`.
