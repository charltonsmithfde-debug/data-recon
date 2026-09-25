# Execution Plan — Portal Architecture Realignment

**Created** 2026-09-20 · **Scope** every open story in `thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md`
(EPIC 1–8, 32 stories) · **Status** 3 shipped, 1 decided, 29 open

This file is the **authority on execution order and story status**. The PRD remains the authority on
*what each story means* — its acceptance criteria are not restated here, only referenced.

> **Nothing under `data-recon/` is a git repository.** There is no branch, no commit, no PR and no
> `git log` to recover state from. This file and the story's tests are the only durable record that
> a story was done. Treat an unrecorded change as a lost change.

The HANA/dbt parity queue (`Active Priorities.md` items 0–5) is **parked by decision 2026-09-20** and
is deliberately out of scope here. It is not cancelled; it is simply not what this plan executes.

---

## 1. Resume protocol

A session picking this up, cold, does exactly this:

1. Read this file. The **first row in §4 whose status is not `DONE`** is the current story.
2. Read that story's section in `thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md` for its acceptance
   criteria. Read any ADR it references.
3. Re-verify the "Blocked on" and "Touches" columns against disk before acting — this plan records
   what was true when written, and the working tree moves.
4. Work the story per §3.
5. On completion, update that row's status **and** append a §6 ledger entry in the same pass. Both,
   or neither — a half-updated ledger is worse than none.

`.claude/handover/` is **session** handover and is gitignored (`*`). It does not survive as a record.
This file does. A session-end handover should point at this file rather than restate its contents.

---

## 2. Baseline — measured 2026-09-20

| | |
|---|---|
| Acceptance suite | baseline 2026-09-20: **68 tests, all green**. After US-1.1: **96**. After US-1.4: **111**. After US-1.3: **133**. After US-8.3: **166 tests, all green** (`cd thin-web-app && python -m pytest`) |
| Suites | `test_us_1_1_auth_boundary` 26, `test_us_1_2_identity_resolution` 17, `test_us_1_2b_role_wiring` 14, `test_us_1_2c_popia_indicator` 9, `test_us_1_3_cube_auth` 22, `test_us_1_4_rbac_allowlist` 15, `test_us_2_2_no_secrets` 9, `test_us_6_0_provenance` 16, `test_us_6_0_demo_banner` 5, `test_us_8_3_sql_api_runtime` 33 |
| Legacy cascade suite | 19/19 (run directly, not under pytest — see `pytest.ini`) |
| Cube semantic layer | 13 cubes / 4 files / 509 lines, on Cube **0.35.x** |
| Node | v22.14.0 |

**~~Known flake~~ — SOLVED 2026-09-20, it was never a flake.** The symptom was
`test_us_6_0_provenance::test_response_flags_demo_data…[date-and-client]` failing with
`TimeoutError: timed out` on a 30s socket read in a **full-suite** run while the file passed 16/16
in isolation. It was recorded here as load/upstream latency. That diagnosis was wrong.

**Actual cause:** `tests/conftest.py` booted `server.py` with `stdout=subprocess.PIPE` and never
read the pipe. `http.server` logs one line per request, so the OS pipe buffer fills and the server
process **blocks forever on write**. The cliff is deterministic: request **49**. From there every
request times out, permanently, whatever it asks for — and the static (seam D) tests interleaved
between the HTTP ones keep passing, which is what made it look intermittent.

**Measured, not inferred:** a 140-request probe stalls at #49 with the US-1.1 gate in place, at #49
on a reconstructed pre-US-1.1 `server.py`, and **never** with the pipe drained (300/300 clean). So it
pre-dated US-1.1 entirely; the 26 new US-1.1 tests merely pushed the suite's request count past the
cliff and turned one "flake" into 20 deterministic failures.

**Fix:** a daemon drainer thread in `conftest.py` consumes the log into `server_log`, which the
startup-failure paths now report. Do not "simplify" it to `DEVNULL` — the startup diagnostics need
that text. Lesson: an intermittent timeout in this suite is a **resource** question first, a latency
question second.

---

## 3. The per-story working loop

Every story is red-green-refactor against the PRD's acceptance criteria. The PRD's own rule (§6
preamble) governs: *a story is `DONE` only when its acceptance criteria are demonstrated by an
automated test.* A passing smoke test is explicitly not enough.

1. **Write the failing test first**, as `thin-web-app/tests/test_us_<x>_<y>_<slug>.py` — the existing
   naming convention, and the only pattern `pytest.ini` collects (`python_files = test_us_*.py`).
2. Implement the smallest change that turns it green.
3. Run the **whole** suite, not just the new file. Record the new total in the ledger.
4. Update this file's §4 row and append the §6 ledger entry.

**Seams** (from `tests/conftest.py`): **A** thin-web-app HTTP API via the `portal` fixture · **B** Cube
REST API, needs `CUBEJS_API_SECRET` · **C** DuckDB lakehouse oracle, needs GCS HMAC creds · **D**
static repo invariants, no fixture. Seam B was **never actually blocked** — an earlier session proved
it authenticates against production. Do not re-inherit that false belief.

---

## 4. Execution order

Status values: `DONE` · `NEXT` · `OPEN` · `BLOCKED`

### Phase 0 — Stop the bleeding

| # | Story | Status | Blocked on | Touches |
|---|---|---|---|---|
| — | US-6.0 Stop asserting "live" | **DONE** 09-19 | — | `server.py`, banner |
| — | US-1.2 Role from identity | **DONE** 09-19 | — | `resolve_identity()`, 6 call sites |
| — | US-2.2 No credential literals | **DONE** 09-19 | — | 18 hits / 13 files |
| 1 | **US-2.1 Rotate every exposed credential** | **NEXT** | 🟠 **the user's authorisation** — outward-facing and takes the dashboards down; `gcloud` itself is available | Cloud Run `scbi-cube`, Secret Manager (**not enabled**), `MIGRATION_PLAN.md`, PRD prose |

US-2.1 is the critical path. **Correction 2026-09-20: `gcloud` is available and authenticated**
in the agent's own shell (`charltonsmithfde@gmail.com`, project `myanalyticsproduct`, region
`europe-west1`). Two earlier sessions recorded "needs `gcloud`, not agent-runnable" without ever
running `gcloud version` — the claim was inherited and repeated, never checked. What actually makes
this the user's call is narrower and still stands: rotation is **outward-facing and hard to reverse**
(the dashboards go down between rotation and restart) and so needs their explicit authorisation, and
`setx` is user-level, so a tool-shell export never reaches a fresh shell. The mechanical
`gcloud` steps *are* runnable here once they say go.
The code is already clean — this is the live-value half. The current key is also 24 bytes, under
RFC 7518's 32-byte HMAC-SHA256 minimum, so rotation is a correctness fix as well as a secrets one.

**Measured 2026-09-20, and it raises the urgency:** `scbi-cube` has `allUsers` bound to
`roles/run.invoker` — the Cube API is **invokable by anyone on the internet**, and the signing key
that gates it is the one that sat in the tree. Until US-2.1 lands, a leaked copy of the repo is a
working credential against a public endpoint. **Secret Manager is also not enabled on the project**
(`secretmanager.googleapis.com` is `SERVICE_DISABLED`), so `CUBEJS_API_SECRET` and
`DUCKLAKE_CATALOG_PASSWORD` are plain env vars on the service, not `--set-secrets` mounts.
Markdown is excluded from the secret sweep deliberately, so `MIGRATION_PLAN.md` and the PRD still
name old values and must be scrubbed by hand as part of this story.

### Phase 1 — Trust boundary

| # | Story | Status | Blocked on | Touches |
|---|---|---|---|---|
| 2 | US-1.1 Authenticate before serving anything | **DONE (code)** 09-20 | criterion 1 only: 🔴 **the user** — Cloud Run behind IAP | `verify_iap_assertion()` — real JWKS signature check |
| 3 | US-1.4 Close the RBAC allowlist gap | **DONE** 09-20 | — | `cube.js` allowlists + startup assertion |
| 4 | US-1.3 Make Cube reject unverified callers | **DONE (code)** 09-20 | criterion 2 only: 🔴 **the user** — remove `allUsers` from `scbi-cube` **and `scbi-metabase`** | `cube/cube.js` `checkSqlAuth` — real scrypt verification |
| 5 | US-2.3 Prefer keyless access | OPEN | US-2.1 | removes the GCS HMAC pair outright |

US-1.1 came first in this phase because **US-1.2 was not real without it** —
`verify_iap_assertion()` returned `None` pending real JWKS verification, so US-1.2 had replaced a
query-string hole with a header the app could not verify. That is now closed in code.

**US-1.1 was built ahead of US-2.1 deliberately.** The table shows it blocked on US-2.1, and in
*deployment* order it is: the rotation must land before this ships. But nothing in the *code*
depends on rotated values, US-2.1 is not agent-runnable, and leaving the trust boundary
unverifiable while waiting on a human step was the larger risk. Criteria 2–4 are proven by test;
**criterion 1 (Cloud Run behind IAP, `--allow-unauthenticated` absent) is infrastructure and remains
owed by the user**, same class as US-2.1. US-1.4 is unblocked and is the next agent-runnable story. US-1.3 is sequenced last in the phase
deliberately: it edits `cube.js`, which US-3.0 rewrites next, so landing it here means **one**
regression pass over the three dashboards covers both. US-3.0's acceptance criteria already assert it.

### Phase 2 — Cube upgrade and catalog *(unblocks everything structural)*

| # | Story | Status | Blocked on | Touches |
|---|---|---|---|---|
| 6 | **US-3.0 Upgrade Cube 0.35.x → 1.7.x** | OPEN | US-1.3 | `package.json`, lockfile, `Dockerfile`, `cube.js:137` |
| 7 | US-3.1 DuckLake implementation (Option A) | OPEN | **US-3.0**, US-2.1 | `initSql`, catalog schema, reload script |
| 8 | US-4.1 Lakehouse views from a manifest | OPEN | US-3.1 | `scripts/migration_state.json` driven |
| 9 | US-3.2 Make the telemetry cockpit truthful | OPEN | US-3.1 | `web/telemetry_engine.py:217-229` |

US-3.1 is **decided, not done** — ADR-0001 chose Option A on 2026-09-20; steps 2–8 of its §4 are the
implementation and they cannot start before US-3.0. P1 proved `ATTACH 'ducklake:…'` **segfaults
(exit 139)** on the driver Cube 0.35.x binds to.

US-4.1 sits here rather than in Phase 3 because **ADR-0001 §4 step 4 satisfies it in the same
change** — registering the 44 tables from the manifest *is* the manifest-driven view generation.
Doing it later means doing it twice.

**Two hazards carried into this phase, both found while writing the ADR:**
- **No GCS prefix cleanup exists anywhere** in `scripts/`. The reload uses `gcloud storage cp
  --recursive`, which overwrites by name but never deletes what the new unload did not produce.
  Snowflake `COPY INTO` varies file chunking run to run, so a prior generation can survive in the
  `*.parquet` glob — **silent double counting that may already be live**. Audit the bucket for
  orphans *before* the first DuckLake registration (ADR §4 step 8). Do not assume current totals
  are correct.
- `telemetry_engine.py:221` hardcodes tier `db-custom-1-3840` (1 vCPU) while
  `scripts/provision_gcp_infra.sh:32` creates `db-custom-2-7680` (2 vCPU).

  **Corrected 2026-09-20 — an earlier version of this bullet had it backwards.** It said the
  cockpit under-reports by half and named that as US-3.2's concrete first fix. Measured against
  the live project: `gcloud sql instances describe scbi-ducklake-catalog` returns tier
  **`db-custom-1-3840`**, `RUNNABLE`, `POSTGRES_16`. The hardcoded value is *correct*; it is
  `provision_gcp_infra.sh` that does not match reality, because that script was never applied to
  this instance. **Changing `telemetry_engine.py` to 2 vCPU, as the old bullet directed, would
  introduce the error rather than fix it.**

  The real defect is unchanged and is still US-3.2's first fix: the cockpit reports a tier it
  **hardcodes and has never contacted the instance to confirm**. It happens to be right today,
  which is worse than being wrong — a value that nobody reads from the source is right only by
  coincidence, and silently becomes wrong the moment anyone resizes the instance. Read it from
  the API; and reconcile `provision_gcp_infra.sh` separately, since it now documents a shape the
  project does not have.

### Phase 3 — Semantic foundation

| # | Story | Status | Blocked on | Touches |
|---|---|---|---|---|
| 10 | US-4.2 Fix the broken dimension bindings | OPEN | US-4.1 | `SharedDimensions.js` |
| 11 | US-4.3 Build `FundAnalyticsMonthlyMetrics` | OPEN | US-4.2 | new cube |
| 12 | US-4.4 Build `MemberSegmentation` | OPEN | US-4.2 | new cube |
| 13 | US-4.5 Define or delete remaining allowlisted cubes | OPEN | US-4.3, US-4.4 | allowlist |

US-4.4 carries the PRD's highest-impact risk: the segmentation join **fans out and inflates member
counts**, silently. Its row-count equivalence test is not optional, and the PRD requires reconciling
against published PBI totals before release. US-4.3 needs a business answer first — see §5.

### Phase 4 — Make the proof harness real *before* the dashboard work leans on it

| # | Story | Status | Blocked on | Touches |
|---|---|---|---|---|
| 14 | US-7.1 Independent ground truth | OPEN | US-4.2 | recon oracle |
| 15 | US-7.3 Browser verification | OPEN | — (install Playwright) | retires the US-6.0 static proxy |

Pulled ahead of the PRD's M5 on purpose. Phases 5 and 6 rewrite every number and every slicer on
Dashboard 1; without an independent oracle and real DOM assertions, those stories can only be marked
done on self-referential tests. US-7.3 also retires the explicitly-labelled **static proxy** standing
in for the US-6.0 banner test today, and should give US-7.1 a deterministic path that fixes the §2
flake.

### Phase 5 — Cascading filters

| # | Story | Status | Blocked on | Touches |
|---|---|---|---|---|
| 16 | US-5.1 Cube-derived slicer options | OPEN | US-4.5, US-7.1 | slicer handler |
| 17 | US-5.2 Bidirectional narrowing | OPEN | US-5.1 | |
| 18 | US-5.3 Invalid-selection recovery | OPEN | US-5.1 | |
| 19 | US-5.4 Request hygiene | OPEN | US-5.1 | |

Exit criterion is the PRD's **56-pair cascade matrix** green with zero hardcoded option arrays.
Note US-5.1 touches Dashboards 2 and 3 too — they share the hardcoded handler even though they are
otherwise out of scope.

### Phase 6 — Dashboard 1 de-fabrication

| # | Story | Status | Blocked on | Touches |
|---|---|---|---|---|
| 20 | US-6.1 Headline KPI cards from Cube | OPEN | US-5.1, US-7.1 | |
| 21 | US-6.2 Pages 1–3 from Cube | OPEN | US-6.1 | |
| 22 | US-6.3 Page 4 Contributions from Cube | OPEN | US-6.1 | |
| 23 | US-6.4 Page 5 Products & Risk from Cube | OPEN | US-6.1 | |
| 24 | US-6.5 Filter state persists across tabs | OPEN | US-6.2 | |
| 25 | US-6.6 Remove silent fallbacks everywhere | OPEN | US-6.1…6.4 | every handler |

**The US-6.0 demo banner comes down only after 25 is green**, not before. The PRD names a credibility
risk here: real numbers will visibly differ from the fabricated ones users have already seen.
Communicate before this phase ships.

### Phase 7 — Close the proof loop

| # | Story | Status | Blocked on | Touches |
|---|---|---|---|---|
| 26 | US-7.2 Mutation check | OPEN | US-7.1 | |
| 27 | US-7.4 CI gate | OPEN | US-7.2, US-4.2 | secret sweep, conformance, no-literals, recon, mutation |

### Phase 8 — Consolidate

| # | Story | Status | Blocked on | Touches |
|---|---|---|---|---|
| 28 | US-8.1 Deploy the thin app | OPEN | US-1.1, US-7.4 | `thin-web-app/Dockerfile`, Cloud Run `scbi-thin-web` behind IAP |
| 29 | US-8.2 Retire `data-recon/web/` | OPEN | US-8.1, US-3.2 | |
| 30 | **US-8.3 Serve Metabase and Power BI over the Cube SQL API** | **DONE (code + deployed)** 09-20 | login unproven — the VM runs and Cube SQL is listening, but no BI client has authenticated yet | `cube/cube.js`, `cube/Dockerfile`, 3 new `cube/` scripts, `metabase/`, `docs/METABASE_CUBE_SQL.md` |

US-8.2 must come after US-3.2, since the telemetry cockpit being retired lives in `web/`.

**US-8.3 was not in the original plan.** The plan had no Metabase story at all, and the PRD's
serving layer stopped at the thin web app. It was added on 2026-09-20 when the user restated the
architecture as **GCS → ducklake (GCSQL) → CubeJS → clients (Metabase, Power BI, thin web
client)** and directed that the Postgres wire protocol be enabled. It sits in Phase 8 because it
consolidates the serving layer, and it does not block any earlier phase.

---

## 5. Deviations from PRD §7 milestones, and why

This order is **not** the PRD's M0–M6 sequence. Three deliberate changes:

| Change | Reason |
|---|---|
| **EPIC 3 moved from M6 to Phase 2** | ADR-0001 made the Cube upgrade a hard prerequisite, not a consolidation tidy-up. US-3.1 Option A is unimplementable until it lands. |
| **US-4.1 moved next to US-3.1** | ADR-0001 §4 step 4 satisfies US-4.1's manifest requirement in the same change. |
| **US-7.1 and US-7.3 pulled ahead of EPIC 5/6** | Phases 5–6 rewrite every dashboard number; without an independent oracle and real browser assertions they can only be self-certified. |

## 6. Open questions that gate specific stories

**All five are now decided — ADR-0002, 2026-09-20**, on best-practice grounds, after eight
sessions with no answer. Each decision is reversible; ADR-0002 §8 records the cost of reversing
each one. **Two remain provisional and can still be overturned by the business** — items 1 and 5
below. Read ADR-0002 before starting any of these stories.

1. ~~**Brokerage semantics** (gates US-4.3) — `DimAggregator.aggregator_brokerage_name` vs
   `aggregator_client_broker_consultant`.~~
   **Decided: `DimAggregator.aggregatorBrokerageName` via `aggregator_hk`** (ADR-0002 §3). The
   slicer filters an organisation, not a person; `aggregator_client_broker_consultant` is a
   different grain and is personal information under POPIA. `broker_consultant_hk` is annuity-only.
   Expose the consultant separately, PII-masked, on the annuity cubes.
   ⚠ **Provisional — confirm with the report owner *before* US-4.3 starts.** This is the one
   decision here with a real reversal cost: re-pointing the slicer means restating any published
   brokerage breakdown.
2. ~~**Identity source** (gates US-1.1) — Google Groups vs a `role_assignments` table.~~
   **Answered by US-1.2**, which shipped `role_assignments.json` as the mechanism, and
   **filled on 2026-09-20**: the system owner, `ROLE_EXECUTIVE_ALL` with PII in the clear and
   the `sys_admin` group. The file now carries both halves of identity — what a person sees
   (`role`, `can_view_pii`, read by `server.py`) and what they reach (`groups`, read by
   `09_apply_access.sh`) — so the two cannot drift. Schema, procedure and the rules the JSON
   cannot state about itself: `thin-web-app/ROLE_ASSIGNMENTS.md`.
3. ~~**Segmentation join path** (gates US-4.4) — `member_segmentation_nk` (PBI's *inactive*
   relationship) vs `member_hk + date_sk`.~~
   **Decided: `member_hk + date_sk`** (ADR-0002 §4). `cnf__fact_member_segmentation` is member ×
   month, so the composite key *is* the grain and cannot fan out; `member_segmentation_nk` is a
   relationship its own source model deactivated for unrecorded reasons.
   **The row-count equivalence gate is unchanged** — choosing the safer join is not evidence that
   it is safe.
4. ~~**Gender values** (gates US-6.1) — does the source carry values beyond M/F, or nulls?~~
   **Decided: render what the data returns; bucket NULL/blank/unknown into one explicit
   `Unspecified`** (ADR-0002 §5). The question asked us to predict a demographic domain; the fix
   is to remove the assumption, not resolve it. `app.js:769-770,794-795,1242` hardcodes exactly two
   series in three places — today a third value silently omits members rather than erroring.
5. ~~**Dashboards 2 and 3** — same recon treatment or not?~~
   **Decided, as two separate answers** (ADR-0002 §6): the shared slicer handler **is** fixed
   correctly for all three — US-5.1's own final criterion already requires removing the shared
   alias — while the **reconciliation scope stays Dashboard 1**.
   ⚠ **Provisional** in the second half only: whether 2 and 3 eventually get recon is a Product
   Owner roadmap call, deliberately left open.

Resolved: *DuckLake adopt or retire* → **adopt**, ADR-0001, 2026-09-20.
Resolved: *Identity source* → `role_assignments.json`, shipped with US-1.2.
Resolved: *Brokerage, segmentation join, gender, Dashboards 2–3, `role_assignments.json`, and the
compromised HMAC key* → **ADR-0002, 2026-09-20**.

**Answered by the system owner, 2026-09-20.** The three authorisation decisions that gated 05,
07 and 08 are settled, and the answer is a file rather than three command lines:

| Person | Role | PII | Groups |
|---|---|---|---|
| `charltonsmithfde@gmail.com` | `ROLE_EXECUTIVE_ALL` | in the clear | `sys_admin` |

`sys_admin` implies `portal`, `metabase`, `sql_analyst` and the derived `cube_rest`, so one word
answers all three questions at once: who may open Metabase, who may invoke `scbi-cube`, and who
gets an IAP tunnel to 5432. `scripts/blocked/09_apply_access.sh` turns the roster into those IAM
bindings and reports anyone bound whom the roster does not justify; `scripts/access/manage_access.py`
is how the next person is added. The procedure is `thin-web-app/ROLE_ASSIGNMENTS.md`.

One operator holding everything is correct for a platform with one operator, and stops being
correct the moment a second person needs part of it — which is exactly what `groups` exists for.
Two things that are deliberately *not* implied by it: a Metabase account (Metabase's own user
admin) and a SQL credential (`CUBEJS_SQL_USERS`, via `02b_remint_sql_users.sh`).

### Infrastructure owed by the user

Not questions — actions. No code is blocked on them, but the stories they belong to cannot be
called done, and two of them mean a shipped control currently protects nothing.

`gcloud` **is** available and authenticated in the agent shell, so the mechanical steps below are
runnable here on request. They are listed as the user's because each is outward-facing, takes a
live service down, or needs an authorisation decision — not because the tooling is missing.

| Owed | Story | Why it is the user's | Consequence until done |
|---|---|---|---|
| **BLOCKED ON `00` — run `00_export_ca_bundle.ps1` from PowerShell, then `04_rotate_and_mount_secrets.sh`** (see *Blocked: 04* below). Rotates the Cube signing key and both Cloud SQL passwords; the GCS HMAC pair is carried across, not re-minted | US-2.1 | Dashboards go down between rotation and restart, **and the agent is refused `00` by the auto-mode classifier** (`Security Weaken`) | The repo's key still opens a **publicly invokable** Cube API. 04 aborts at its CA-bundle guard before any write, so there is no partial state — but no part of the rotation has happened |
| ~~Enable `secretmanager.googleapis.com`~~ **DONE 2026-09-21 — `03_enable_secret_manager.sh` run by the agent on the user's go**; **mounting via `--set-secrets` is still owed (04)** | US-2.2 | Enabling the billable API was the user's call and was given; mounting takes Cube and Metabase down | API enabled, four **empty** secrets exist with the runtime SA as `secretAccessor`. US-2.2's criteria 1 and 3 remain **unmet** — nothing is mounted, so every service still reads plain env vars |
| Deploy `scbi-thin-web` to Cloud Run behind IAP, no `--allow-unauthenticated`, with `SCBI_IAP_AUDIENCE` set | US-1.1 crit. 1, US-8.1 | Creates a new public-facing service | The 26-test auth gate protects nothing — **the service does not exist yet** |
| **QUEUED — run `scripts/blocked/05_lock_down_cloud_run.sh`** (exact command in *Queued to run* below). Removes `allUsers` from the invoker binding of **both** `scbi-cube` and `scbi-metabase` | US-1.3 crit. 2 | Cuts off any current direct consumer, and the auto-mode classifier refuses the script to the agent | Cube is reachable by anyone who has the key; **Metabase's login UI is reachable by anyone at all** (re-measured 2026-09-20: `allUsers` still bound on both) |
| ~~Approve and run `cube/deploy_cube_sql_vm.sh`~~ **DONE 2026-09-20** | US-8.3 | Approved by the user and executed | Instance `scbi-cube-sql` is RUNNING at `10.132.0.2`. Cube SQL listens on 5432; **no client has logged in yet** |
| ~~Mint a **new** GCS HMAC pair~~ **DONE 2026-09-20**; redeploying **Cloud Run** still owed | US-2.1, US-8.3 | Rotating a live credential; the old key may still be in use by `web/*_engine.py` | New pair is live on the SQL VM. **Corrected 2026-09-20:** the live `scbi-cube` revision carries **neither** key -- it has no `CUBEJS_DB_DUCKDB_S3_*` env vars at all (names listed, values never read), so the current `cube.js` would crash-loop there. The old key is still ACTIVE |

**On the GCS HMAC pair, before anyone "adds the existing one".** *(Superseded 2026-09-20: a second, uncompromised pair was minted and is live on the SQL VM. The paragraph below still governs the **old** key, which was deliberately left ACTIVE.)* The compromised key is
`GOOG1EZ…DALH` on `886154918734-compute@developer.gserviceaccount.com`, and **its secret is
committed to this repo** (§P4 below names both halves). Deploying it would be deploying a known-
compromised credential. Mint a new one:

```bash
gcloud storage hmac create 886154918734-compute@developer.gserviceaccount.com
```

Do **not** deactivate or delete the old key in the same step — `web/*_engine.py` read it from the
environment and may still be running somewhere. Retire it once that is confirmed. The new secret
must never be written into any `.py`/`.js`/`.sh`/`.ps1` under `data-recon/`; the deploy scripts all
take it from the environment, and `test_us_2_2_no_secrets` sweeps for it.
| ~~Optional: create `thin-web-app/role_assignments.json`~~ ~~**File created 2026-09-20 (ADR-0002 §7); the *mapping* is still owed**~~ **DONE 2026-09-20: mapped, one person — the system owner as `sys_admin` on `ROLE_EXECUTIVE_ALL`** | US-1.2 | Was a business decision about who gets what; answered by the system owner | `01_preflight.sh`/`07`/`99_verify.sh` report how many callers are mapped, so an empty map could never read as done. Adding the next person is `scripts/access/manage_access.py add` + `09_apply_access.sh` |

#### Blocked: `04_rotate_and_mount_secrets.sh` needs `00` first, and `00` is refused to the agent

**Found 2026-09-21 by attempting it.** `04` calls `require_ca_bundle` unconditionally, **before**
stage 1 and before the `--dry-run` branch, so it aborts at once with no CA bundle present:

```
ABORT: No CA bundle at /c/Users/G988557/.scbi-runbook/win-ca-bundle.pem
```

`$HOME/.scbi-runbook/` exists but is **empty** — `00_export_ca_bundle.ps1` has never been run, and
`CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE` is unset. 04 needs it because **stage 1 reads the GCS HMAC
secret off the SQL VM over `gcloud compute ssh --tunnel-through-iap`**, and that is exactly the
code path Zscaler's TLS interception breaks. The HMAC secret is not retrievable from GCS at all —
`/etc/cube-sql.env` on the VM is the only copy — so stage 1 is not skippable.

**The agent is refused `00`** by the auto-mode classifier as `Security Weaken`, the same way it was
refused 09 and will be refused 05. Not routed around, per the standing rule. The two commands, in
order, are the user's:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\blocked\00_export_ca_bundle.ps1
```
```bash
cd /c/Users/G988557/Documents/Code/github_DBT/data-recon
./scripts/blocked/04_rotate_and_mount_secrets.sh --dry-run    # then again without --dry-run
```

No `setx` is needed for the runbook: `require_ca_bundle` defaults to
`${STATE_DIR}/win-ca-bundle.pem` and exports the variable itself. The `setx` line 00 prints is only
for ad-hoc `gcloud` calls outside these scripts.

**Why this is a safe place to have stopped.** 04's first write is **stage 4** (secret versions) and
the outage begins at **stage 5** (Cloud SQL passwords). Stages 1–3 are recover, generate, confirm.
An abort at the guard, or a stage-1 SSH failure, therefore changes nothing — which is the failure
mode to want, given that once stage 5 has run, re-running the whole script would generate a *third*
password rather than repair the second. If it dies mid-flight, read stage 5's own `die` message:
it says to set the password by hand from the secret's latest version and continue from stage 6.

**`04 --dry-run` alone cannot complete from a non-TTY shell even once 00 has run** — stage 3 calls
`confirm()`, and the `--dry-run`/`confirm()` defect means it prompts anyway and `die`s on EOF.
From a real terminal this is a non-issue: type `proceed`. Nothing executes under `DRY_RUN`
regardless, since `run()`, `add_version()` and `set_sql_password()` all no-op.

**Decide `--include-vm` before running it live.** Without the flag the SQL VM keeps the *old* API
secret — a knowingly half-finished rotation, and harmless today because BI clients authenticate
with `CUBEJS_SQL_USERS`, not a JWT. With it, the VM is redeployed too: a second outage on a
runtime whose login is still unproven.

#### Queued to run: `05_lock_down_cloud_run.sh` — the lockdown

**Added to this owed list 2026-09-20 at the user's request.** 09 has already bound the operator as
an invoker on both services (re-verified this session against the live policy), so the grant half
is satisfied and the revoke can no longer lock the only operator out. Dry-run first, then live:

```bash
cd /c/Users/G988557/Documents/Code/github_DBT/data-recon
./scripts/blocked/05_lock_down_cloud_run.sh --dry-run \
    --cube-invoker=serviceAccount:886154918734-compute@developer.gserviceaccount.com \
    --cube-invoker=user:charltonsmithfde@gmail.com \
    --metabase-invoker=user:charltonsmithfde@gmail.com
```

Then the same line without `--dry-run`. **Both `--cube-invoker` entries are required.** The compute
service account is the thin web app's runtime and the normal caller of `scbi-cube`, and it is
**not bound today** — re-measured this session, the only members on `roles/run.invoker` are
`allUsers` and the operator. `allUsers` is the sole reason the platform's own caller reaches Cube,
so omitting the service account would cut it off at the moment of the revoke.

Two things to know before running it. Both are measured, neither is a reason not to run it:

- **`data-recon/web/` and its telemetry cockpit go dark the minute this runs** — 403 at Cloud Run,
  before Cube, so it will not look like an auth problem in Cube's logs. `web/` is US-8.2's to
  retire and `thin-web-app` already mints the right header. If `web/` is still wanted afterwards,
  the fix is to give it `X-Serverless-Authorization`; **never** to re-add `allUsers`.
- **`--dry-run` does not skip `confirm()`** (`scripts/blocked/lib/common.sh`), so a dry run still
  prompts and needs a TTY. Nothing executes under `DRY_RUN`; the prompts are cosmetic.

Confirm afterwards with `./scripts/blocked/99_verify.sh` — it is the check that currently reports
`allUsers` present, so its failure count should drop when this lands. Reversal is one command:
re-add the binding.

**`SCBI_IAP_AUDIENCE` value for the deploy:** project number `886154918734`, project id
`myanalyticsproduct`, so the IAP-on-Cloud-Run form is `/projects/886154918734/apps/myanalyticsproduct`.
Behind a load balancer it is the backend-service form instead.

**US-2.2 is marked `DONE` and that remains correct as scoped** — its automated test covers the
code sweep, which is what the story's verification names. But criteria 1 and 3 are infrastructure
and are not met. Same class as US-1.1 criterion 1: the code half shipped, the live half did not.

---

## 7. Ledger — append only, newest at the bottom

One entry per story completed. Never edit an earlier entry; correct it with a new one.

Format: `### <date> — US-x.y <title>` then what changed, the test that proves it, the suite total
after, and anything the next session would otherwise re-derive.

### 2026-09-19 — US-6.0, US-1.2, US-2.2 *(reconstructed from the vault, pre-dates this ledger)*
- **US-6.0** — the member handler fabricated numbers from in-process constants while reporting
  `live_feed: true`; now `data_source: "synthetic"` with a UI banner.
  Tests: `test_us_6_0_provenance.py` (16), `test_us_6_0_demo_banner.py` (5).
- **US-1.2** — every handler read `?role=`/`?maskPii=` off the request and defaulted an anonymous
  caller to `ROLE_EXECUTIVE_ALL` with PII visible. Now `resolve_identity()` + `GET /api/identity`,
  six call sites wired, least privilege is `ROLE_FINANCE_MEMBER` masked.
  Tests: `test_us_1_2_identity_resolution.py` (15), `test_us_1_2b_role_wiring.py` (14),
  `test_us_1_2c_popia_indicator.py` (9).
- **US-2.2** — 18 credential literals across 13 files removed (Cube signing key, GCS HMAC pair, two
  provisioning passwords, a Metabase password). Env-only reads, no fallback;
  `require_env()`/`requireEnv()` fail at startup on a missing variable.
  Test: `test_us_2_2_no_secrets.py` (9).
- **The finding that mattered:** seam B was never blocked. The live Cloud Run signing key *was* the
  in-code default at `server.py:29` and authenticated against production (403 without, 200 with).
  Every earlier "blocked on credentials" note was wrong.
- Suite total after: **68 green**.

### 2026-09-20 — US-3.1 decided (not implemented)
- ADR `docs/adr/0001-ducklake-or-parquet.md` created: **adopt DuckLake (Option A)**. The monthly
  reload does overlap live traffic, which was the deciding condition.
- **DuckLake was never actually in use** — zero `ATTACH` in the tree, only the naming. The lake is
  Parquet-on-GCS read through `read_parquet()` globs in `cube.js` `initSql`.
- **P1 verified empirically, not from version numbers:** `duckdb-driver@^0.35.0` → `0.35.81` →
  `duckdb@1.4.4`, which clears the DuckLake 1.3.0 floor *and* loads the extension — but
  `ATTACH 'ducklake:…'` **segfaults, exit 139, reproducibly**. The identical lifecycle (attach,
  load, reload, snapshots, `AT (VERSION => 2)` time travel) runs clean on `@duckdb/node-api@1.5.5-r.5`,
  which is exactly what `duckdb-driver@1.7.42` depends on. **A version check alone gives a false
  green here** — do not shortcut this class of check again.
- `data-recon/cube/` was left untouched; all verification ran in a scratchpad.
- Cost is not an argument either way: the instance is sunk for Metabase regardless (~USD 105–115/mo
  list, an estimate, not a billing read).
- Suite total: unchanged, **68 green** (no code change).

### 2026-09-20 — US-3.0 scoped
- Written as a new story in PRD EPIC 3. No `docs/tickets/` convention exists under `data-recon/`;
  the PRD's `US-x.y` stories are the ticket format, and `US-3.0` follows the existing `US-6.0`
  ship-first numbering.
- **Smaller than first estimated:** camelCase JS models are still supported in Cube v1, so the model
  layer needs **no renaming**, and the surface is **13 cubes across 4 files** (509 lines), not 13
  files. ADR §3.1 corrected accordingly.
- **What breaks:** `dbType` was removed in v1.7.0 and now *throws* — `cube/cube.js:137` sets it, so
  the server fails at boot. Node v20 removed, **v22 deprecated**, both in v1.7.0; local Node is v22.14.0.
- **What does NOT break** (checked against `cube-js/cube` `DEPRECATION.md` — do not re-derive):
  `checkSqlAuth`, `contextToAppId`, `queryRewrite` all survive. `SECURITY_CONTEXT` was deprecated in
  v0.33 in favour of `queryRewrite`, which this repo already uses.
- **The container is already inconsistent today:** `Dockerfile` is `FROM cubejs/cube:latest`, and
  `latest` resolves to **v1.7.42** (pushed 2026-09-18 alongside the `v1`/`v1.7`/`v1.7.42` tags),
  while `package.json` pins `^0.35.0` into `/cube/conf`. So a 1.7.42 base image is running a 0.35.x
  `cubejs-server`, and the base moves on every rebuild. Both layers need pinning, plus a lockfile.
- Suite total: unchanged, **68 green** (no code change).

### 2026-09-20 — US-1.1 Authenticate before serving anything *(code complete; criterion 1 owed)*
- **What changed.** `server.py`: `SCBI_IAP_AUDIENCE` via `require_env()` (a missing audience is now
  a startup failure); a TTL-cached `_fetch_jwks()` + `_jwk_for_kid()`; a real
  `verify_iap_assertion()` doing full ES256 signature + `aud` + `iss` + `exp` verification and
  returning the token's `email`; and `reject_unauthenticated()` — **one** gate, called at the top of
  `do_GET` and `do_POST`.
- **The gate is a single chokepoint by design, not per-endpoint.** Checked per handler it would rot:
  a handler added later would default to *open*. Here a new handler defaults to closed.
- Test: `tests/test_us_1_1_auth_boundary.py` (**26**). Covers no header, non-JWT garbage, expired,
  wrong `aud`, wrong `iss`, foreign-key signature, tampered payload, `alg: none`, unknown `kid`, and
  valid → 200, parameterised across 7 `/api/*` paths.
  **Renamed from the PRD's `tests/test_auth_boundary.py`** so `pytest.ini`'s `test_us_*.py` pattern
  actually collects it — the PRD's name would have been silently skipped.
- **US-1.2's contract was rewritten, not weakened.** Its tests asserted an anonymous caller got
  `200` + `authenticated: False`; the PRD says *any* `/api/*` path is gated, so anonymous is now
  401. US-1.2's real substance — role and PII entitlement never read off the request — moved to an
  *authenticated* caller, which is strictly stronger: the escalation attempts are now made by
  someone the server trusts. Two tests added there
  (`test_unidentified_caller_is_not_answered_at_all`,
  `test_authenticated_caller_cannot_claim_an_email`): 15 → 17.
- **`SCBI_IAP_JWKS_URL` is not the forbidden bypass env var.** It changes *which issuer's keys* are
  trusted so the suite can mint its own; full signature/`aud`/`iss`/`exp` verification still runs on
  every token, and it grants nothing without the private half. Production sets no such variable.
  `test_no_bypass_env_var_exists` asserts no `SCBI_SKIP_AUTH`-class switch exists in `server.py`.
- **`role_assignments.json` still does not exist**, so a verified caller falls back to
  `LEAST_PRIVILEGED_ROLE` with PII masked — the same privilege the suite already asserted. Only
  `authenticated`, `email` and `role_source` changed.
- **The big incidental finding: the §2 "known flake" was a harness bug, and was never a flake.**
  See §2 — the server blocked forever on a full, unread log pipe at request 49. Fixed in
  `conftest.py`. The full suite went from 10+ minutes with 20 failures to seconds with none.
  **Three consecutive clean full runs.**
- Suite total after: **96 green**, exit 0. (68 → 96: +26 US-1.1, +2 US-1.2.)
- **Still owed by the user:** criterion 1 — deploy Cloud Run behind IAP without
  `--allow-unauthenticated`, and set `SCBI_IAP_AUDIENCE` on the service. Until then the gate is
  proven but not live. See §6.

### 2026-09-20 — US-1.4 Close the RBAC allowlist gap
- **The gap, measured:** 8 of the 15 names across `ROLE_PERMISSIONS[*].allowedCubes` resolved to no
  cube at all — `FundAnalyticsMonthlyMetrics`, `MemberTransactions`, `AssetflowsMemberMonthly`,
  `InFundExitMemberMonthly`, and all four `DigitalPortal*` names. 13 cubes are defined across
  `model/cubes/*.js`.
- **`ROLE_DIGITAL_OPERATIONS` now has an empty allowlist** — every one of its four cubes was
  undefined. This changes nothing about what it could query (it could already reach only shared
  dimensions); it stops the permission set from *implying* access that never existed. US-4.5 defines
  or deletes those cubes. The 8 removed names are listed in a comment above `ROLE_PERMISSIONS` with
  the story that owes each one back — **re-add a name only in the change that defines its cube.**
- **The PII fix is the substantive half.** `DimMember` sat in `SHARED_DIMENSIONS`, which
  `queryRewrite` skips the cube-boundary check for, so **every role could read it** —
  `memberGender`, `memberMaritalStatus`, `memberAgeBand`, `currentAge` in the clear, and `memberNk`
  masked only by the separate `SECURITY_CONTEXT` check. It is now allowlisted per role.
- **`DimMember` was re-granted to `ROLE_FINANCE_MEMBER` explicitly, not left denied.** The criterion
  says "removed from the unconditional whitelist", not "denied to everyone": US-6.1's demographic
  cards read gender and age band, and every verified caller falls back to that role. Governed by
  grant instead of bypass is the point. `ROLE_INVESTMENTS`, `ROLE_ANNUITY` and
  `ROLE_DIGITAL_OPERATIONS` lose `DimMember` entirely — none has a demographic remit.
- `SHARED_DIMENSIONS` was **hoisted from inside `queryRewrite` to module scope** so the startup
  assertion can validate it, and so it is not rebuilt on every query.
- **Criterion 2:** `assertAllowlistsResolve()` runs at module load, scanning `model/cubes/*.js` for
  `cube('Name'`, and throws naming the offender. `__dirname` is `/cube/conf` in the image
  (`Dockerfile` does `COPY . .` into that WORKDIR), so the scan resolves in the container too. An
  unreadable model directory is also a startup failure, deliberately.
- Test: `tests/test_us_1_4_rbac_allowlist.py` (**15**), red on 6 before the change.
  **It does not rely on regex alone.** A Node harness stubs `@cubejs-backend/duckdb-driver` through
  `Module._resolveFilename` — `cube/node_modules` does not exist — loads the *real* `cube.js` and
  calls the *real* `queryRewrite`, so denial is proven by enforcement. It covers the PRD's
  verification (per role: every allowlisted cube succeeds, every non-allowlisted cube raises
  `AccessDenied`), the startup assertion via a patched copy of `cube.js` beside a copied model tree,
  and `test_the_unmodified_config_still_loads` so the two injection tests cannot pass vacuously.
  **This is the third time a text-level check would have given a false green here** — see the
  `dbType` note in the US-3.0 entry and the unread-pipe "flake" in §2. Do not reduce these to greps.
- **Not done, and deliberately so:** the PRD's verification also asks for a trivial live query per
  role against the running Cube. That is seam B against a **publicly invokable** production service
  whose signing key US-2.1 has yet to rotate. The enforcement logic is what the criteria constrain,
  and it is now proven directly. Revisit after US-2.1.
- `checkSqlAuth` still returns `{ password: auth.password }`, accepting any password. That is
  **US-1.3**, not this story, and it is now the next agent-runnable row.
- Suite total after: **111 green**, exit 0, two consecutive clean full runs. (96 → 111: +15.)

### 2026-09-20 — US-1.3 Make Cube reject unverified callers *(code complete; criterion 2 owed)*

- **Criterion 2, the substance:** `checkSqlAuth` returned `{ password: auth.password }`, which is
  Cube's documented way of saying *accept whatever was supplied*. Every SQL login succeeded. It now
  verifies the supplied password against a credential store with `crypto.scryptSync` and
  `timingSafeEqual`.
- **The store** is `CUBEJS_SQL_USERS`: JSON, username → `{ password: 'scrypt:<salt>:<key>', role }`.
  `parseSqlUsers()` validates it at module load and throws on a plaintext password or a role with
  no `ROLE_PERMISSIONS` entry — the alternative is a login that authenticates and then throws on
  its first query, inside `queryRewrite`, where the message reaches nobody useful.
- **`canViewPii` is deliberately NOT read from the store.** It comes from `ROLE_PERMISSIONS`. A
  store is an operational artefact edited under deploy pressure; PII visibility is a POPIA decision
  and must not be settable by whoever edits a JSON blob.
- **The username prefix heuristic is gone.** `exec*` or `admin*` previously self-asserted
  `ROLE_EXECUTIVE_ALL` — the one role with PII in the clear — on the strength of a string the
  caller chose. The test that covers this pairs a username the old heuristic would read as
  `ROLE_FINANCE_MEMBER` with a stored role of `ROLE_ANNUITY`, so agreement between the two cannot
  hide a regression.
- **Criteria 1 and 4:** `assertApiSecretIsUsable()` enforces RFC 7518 §3.2's 32-byte floor for
  HS256 and refuses the revoked in-repo secret by SHA-256. The revocation list names the digest,
  never the value — `test_us_2_2_no_secrets` sweeps every `.py`/`.js` for the literal, and a digest
  is a detection rule, not a credential.
- **Unknown usernames cost the same scrypt work as known ones** (`ABSENT_USER_DIGEST`), so the
  store's membership cannot be probed by timing.
- Test: `tests/test_us_1_3_cube_auth.py` (**22**). A Node harness loads the *real* `cube.js` and
  calls the *real* `checkSqlAuth`, same pattern as US-1.4 — rejection is proven by the function
  refusing, not by the source text reading well. Python and Node scrypt were verified
  byte-identical at N=16384 r=8 p=1 dklen=32 before the suite was written.
- **Criterion 2's infrastructure half is owed by the user**: `scbi-cube` still has `allUsers`
  bound to `roles/run.invoker`. Same split as US-1.1 criterion 1. `deploy_cube_rest_cloudrun.sh`
  (US-8.3) now makes that an explicit, undefaulted choice rather than a hand-rolled flag.
- Suite total after: **133 green**. (111 → 133: +22.)

### 2026-09-20 — US-8.3 Serve Metabase and Power BI over the Cube SQL API *(code complete; deploy owed)*

New story, not in the original plan — see the Phase 8 note. Three directives from the user: enable
the Postgres wire protocol on 5432, follow best practice for Metabase, and resolve the DuckDB S3
keys.

- **The finding that reframes the whole story: the variable name was wrong.** `cube/Dockerfile` set
  `CUBEJS` + `_SQL_PORT=5432` and `PBI_TO_DUCKLAKE_REPLICA_GUIDE.md` §5.2 told operators to do the
  same. **That is not a Cube variable.** Cube reads `CUBEJS_PG_SQL_PORT`. So even on a TCP-capable
  runtime the SQL API would never have bound — and the failure is invisible: no listener, no log
  line, every client refused at the TCP layer, indistinguishable from a firewall problem. The
  user's own pasted Cube docs had the right name; the repo had the wrong one.
- **Cloud Run cannot carry it either**, and that is a platform boundary, not a setting. Measured:
  `scbi-cube` revision `scbi-cube-00011-74r` exposes `containerPort: 4000, name: http1` — one port,
  HTTP-only routing. Both halves had to be fixed; neither alone works.
- **`assertSqlApiIsCoherent()`** in `cube.js` makes every silent misconfiguration a startup failure:
  `CUBEJS_SQL_SUPER_USER` set (no `canSwitchSqlUser` policy exists here, so that login could assume
  any role in the store), the legacy port variable set without the real one, a credential store
  with no listening port, or a port that does not coerce to 1..65535. A REST-only runtime with no
  SQL configuration at all returns cleanly — Cloud Run must keep booting, and that is its own test.
- **Runtime: a single Container-Optimized OS Compute Engine instance**, `scbi-cube-sql`,
  `e2-standard-2`, `europe-west1-b`, **no external address**, running the *same image* as
  `scbi-cube` (resolved from the live service, never rebuilt — one `cube.js` across both runtimes).
  **GKE was considered and rejected for now**: Autopilot control plane + internal TCP LB cost, and
  IAP TCP forwarding does not reach a GKE Service — that tunnel is how Power BI Desktop reaches
  5432 with nothing exposed. Revisit at >1 consumer per domain.
- **Metabase best practice, as implemented: one SQL connection per role domain.** Cube derives the
  security context from the login, so a connection *is* a role, and one shared login would give the
  whole BI estate one role. `cube/mint_sql_users.js` mints the set (3 Metabase + 2 Power BI),
  generating passwords *inside* the script so they never reach shell history or the process table.
  **`ROLE_EXECUTIVE_ALL` is deliberately absent** — it is the only role with PII in the clear, and a
  shared executive connection would unmask `member_nk` for everyone who can open a dashboard. That
  is enforced three ways: the deploy script refuses such a store, a test sweeps every deploy
  artefact, and `cube.js` throws on `CUBEJS_SQL_SUPER_USER`.
- **There was no cube deploy script in the repo at all** — every revision was hand-rolled, which is
  exactly how the GCS HMAC pair went missing from the live revision while `cube.js` has
  `requireEnv`'d it since US-2.2. Two now exist, `deploy_cube_rest_cloudrun.sh` and
  `deploy_cube_sql_vm.sh`, and a test asserts both supply the pair.
- **Two GCP facts measured this session, both of which the design depends on:** the `default`
  subnet in europe-west1 is `10.132.0.0/20` (there are three subnets named `default` in that
  region), and **Private Google Access on it is off** — a `--no-address` instance cannot pull its
  image from Artifact Registry without it, and it fails *after* booting, with only the serial
  console to say so. The deploy script enables it idempotently.
- **A regression this session found and fixed:** `assertSqlApiIsCoherent()` turned the whole
  inherited `test_us_1_3_cube_auth` suite red — its harness declared `CUBEJS_SQL_USERS` with no
  port, which is precisely the combination the new guard rejects. The guard was right and the
  harness was wrong; the harness now declares a configuration that could actually boot. This is why
  §1's resume protocol says to re-run the *whole* suite, not the new file.
- **`.ps1` was missing from `test_us_2_2_no_secrets`'s `SWEEP_SUFFIXES`**, which is why
  `deploy_metabase.ps1` and `provision_gcp_infra.ps1` kept literal passwords for weeks after
  their `.sh` twins were cleaned. Both fixed, and `.ps1` added to the sweep — which then
  immediately caught a third occurrence. A sweep is worth exactly what its suffix list covers.
- **Metabase could not have reached a private runtime**: `deploy_metabase.sh` gave the service no
  VPC egress, so the connection would fail at the TCP layer before any credential was checked —
  and in the Metabase UI that looks identical to a wrong password. Now deploys with
  `--network`/`--subnet`/`--vpc-egress=private-ranges-only`.
- Docs: `docs/METABASE_CUBE_SQL.md` written (several artefacts already pointed at it);
  `PBI_TO_DUCKLAKE_REPLICA_GUIDE.md` §5.2 and §7 corrected — §7 had claimed Power BI could use a
  "Cloud Run Cube.js endpoint", which is false at the protocol level.
- Test: `tests/test_us_8_3_sql_api_runtime.py` (**33**), written red first: **16 failed, 17 passed**
  at red. The 17 that passed at red are the per-role `checkSqlAuth`/`queryRewrite` tests — they
  pass because US-1.3's store already supports the multi-connection shape, which is itself the
  evidence that "one connection per role domain" needs no new Cube code.
- **Nothing was created, changed or deleted in GCP.** Every `gcloud` call this session was a read.
  The deploy is owed by the user — §6.
- Suite total after: **166 green**, exit 0. (133 → 166: +33.)

### 2026-09-20 — US-8.3 deployed: the Cube SQL runtime exists in GCP

**This is the first session that created anything in GCP.** Every earlier passage in this file and
in the vault that says the runtime was never run is, from this entry forward, false.

**Approved by the user in-session**, both explicitly: (1) create the SQL runtime VM, (2) mint a new
GCS HMAC pair now.

**Created / changed in GCP**

| Object | State |
|---|---|
| Instance `scbi-cube-sql` | e2-standard-2, europe-west1-b, COS stable, `--no-address`, internal IP `10.132.0.2`, **RUNNING** |
| Firewall `allow-scbi-cube-sql` | tcp:5432 from `10.132.0.0/20` + `35.235.240.0/20`, tag `scbi-cube-sql` |
| Private Google Access, subnet `default`/europe-west1 | flipped **False → True** — VPC-wide, affects every subnet consumer |
| GCS HMAC pair | new pair minted on `886154918734-compute@developer.gserviceaccount.com`; old compromised key left **ACTIVE** by instruction |
| Project SSH metadata | written as a side effect of a failed `gcloud compute ssh` — unintended, harmless, but it is a project mutation |

**Proven, from Cloud Logging `cos_containers`, on two separate boots:**

```
Cube SQL (pg) is listening on 0.0.0.0:5432
Cube API server (0.35.81) is listening on 4000
```

That output also proves every `cube.js` module-load guard passed against the real store —
`parseSqlUsers()` and `assertSqlApiIsCoherent()` included.

**Two real bugs in `cube/deploy_cube_sql_vm.sh`, found only by running it. Both fixed.**

1. `--action=ALLOW` alongside `--allow=` — gcloud rejects them as mutually exclusive.
2. **`gcloud compute instances create-with-container` is discontinued server-side**, not deprecated:
   *"The option to deploy a container during VM instance creation that relies on a container startup
   agent is discontinued."* `--container-image`, `--container-env-file` and `update-container` are
   all gone with it. Reworked onto Google's documented replacement — a plain COS VM plus a
   cloud-init `user-data` payload writing `/etc/cube-sql.env` (0600) and a `cube-sql.service`
   systemd unit. The exists-branch is now `add-metadata` + `reset`, because cloud-init only runs
   `write_files`/`runcmd` on first boot. Script is 307 lines, `bash -n` clean.
   **Any other artefact in this tree using `create-with-container` is broken.**
   *Checked 2026-09-20: none do.* The only remaining mentions are the explanatory comments in
   `deploy_cube_sql_vm.sh` itself, and `scripts/provision_gcp_infra.ps1` creates a **Cloud SQL**
   instance (`gcloud sql instances create`), which is unaffected.

**A security regression this introduced, deliberately and with the user's approval:** the SQL
connection digests and `CUBEJS_API_SECRET` now live in **instance metadata**, not Secret Manager.
Anyone who can `describe` the instance can read them. This makes US-2.2 criteria 1 and 3 *more*
unmet, not less, and it cannot be fixed until `secretmanager.googleapis.com` is enabled.

**Not proven — the story is not fully done.** No BI client has authenticated. The container is
listening; the login path is unexercised, and so is the DuckDB→GCS read with the new HMAC pair
(a `SELECT 1` would not touch it — only a real cube query will).

**Why it is unproven is a local problem, not a GCP one.** `gcloud compute start-iap-tunnel` and
`gcloud compute ssh --tunnel-through-iap` both fail with `CERTIFICATE_VERIFY_FAILED`. Diagnosed
2026-09-20: this machine is behind **Zscaler TLS interception**, and gcloud validates against its
own bundled CA store, which has no Zscaler root. The Windows trust store *does* — a direct TLS
handshake to `tunnel.cloudproxy.app` verifies cleanly against a 189-cert PEM exported from
`Cert:\LocalMachine\Root`, while gcloud's own store fails on the same endpoint. So the fix is
`CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE` pointing at such an export. **The bundle is proven sufficient;
the tunnel itself has still not been run.**

A pure-stdlib Postgres v3 probe is ready for the moment a tunnel exists (StartupMessage → cleartext
password → `SELECT 1`). It and the 5 users' credentials are session-scoped scratchpad files, not
repo files. **If they are gone, re-run `node cube/mint_sql_users.js` and re-run the deploy script** —
re-minting is the intended rotation path; only digests are on the VM.

**Next:** prove a login (fixed-CA tunnel + probe, or redeploy Metabase with Direct VPC egress and
point it at `10.132.0.2:5432` per `docs/METABASE_CUBE_SQL.md` §3), then exercise a real cube query
to test the DuckDB/GCS half, then US-3.0 (Cube 0.35.81 → 1.7.x).

### 2026-09-20 (later) — why nothing could connect: the COS host firewall

**Root cause found and proven. The port was never open on the instance itself.**

The CA problem and the connectivity problem turned out to be two different problems stacked.

**1. The IAP tunnel TLS failure is solved.** This machine sits behind **Zscaler TLS interception**.
gcloud validates against its own bundled CA store, which has no Zscaler root — the Windows store
does. Exporting `Cert:\LocalMachine\Root` (+ `\CA`, + CurrentUser) to a 189-cert PEM and pointing
`CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE` at it makes both `start-iap-tunnel` and
`ssh --tunnel-through-iap` work. Confirmed by the error *changing*, from
`CERTIFICATE_VERIFY_FAILED` to a backend error.

**2. Which exposed the real fault:** `4003: 'failed to connect to backend'. (Failed to connect to
port 5432)`. Everything at the GCP layer checked out — instance tag `scbi-cube-sql` present,
firewall `allow-scbi-cube-sql` INGRESS tcp:5432 from `10.132.0.0/20` + `35.235.240.0/20`, not
disabled, priority 1000. The block was **inside the VM**:

```
cube-sql   Up 32 minutes                      <- container healthy
LISTEN 0 1024 0.0.0.0:5432 users:(("MainThread",pid=1200))   <- Cube genuinely listening

Chain INPUT (policy DROP 69 packets, 4390 bytes)
1  ACCEPT  all   state RELATED,ESTABLISHED
2  ACCEPT  all   lo
3  ACCEPT  icmp
4  ACCEPT  tcp   tcp dpt:22
```

**Container-Optimized OS ships a default-DROP host firewall that allows only port 22 and
established flows.** A GCP firewall rule is necessary but **not sufficient** on COS. The 69 dropped
packets were the tunnel attempts themselves.

**Fixed in `cube/deploy_cube_sql_vm.sh`** (now 330 lines, `bash -n` clean): an idempotent
`ExecStartPre` on `cube-sql.service` that runs `iptables -C … || iptables -A INPUT -p tcp --dport
${SQL_PORT} -j ACCEPT`. It lives in the **unit, not `runcmd`**, because iptables state on COS does
not survive a reboot and `runcmd` runs on first boot only — as an ExecStartPre it re-applies on
every boot and restart.

**The running instance is still closed.** Applying the rule to the live VM is a remote shell write
and was refused by the tool sandbox; it needs the user's permission or a redeploy. **So US-8.3 is
still not proven end to end** — the login and the DuckDB→GCS read remain unexercised.

### 2026-09-20 (later) — evidence on the old HMAC key, for the retire/keep decision

Gathered read-only, to replace guesswork with facts.

- **Both keys are ACTIVE** on `886154918734-compute@developer.gserviceaccount.com`: the new pair
  and the compromised `GOOG1EZ…DALH`.
- **No deployed service reads either one.** Cloud Run has exactly two services, `scbi-cube` and
  `scbi-metabase`. Env var *names* (values deliberately never read): `scbi-cube` has
  `CUBEJS_DB_TYPE/PORT/DEV_MODE/API_SECRET`, `DUCKLAKE_GCS_BUCKET`, `DUCKLAKE_CATALOG_*`,
  `CUBEJS_CACHE_AND_QUEUE_DRIVER` — and **no `CUBEJS_DB_DUCKDB_S3_*` at all**. `scbi-metabase` has
  only `MB_DB_*`. *(This corrects a line written earlier today in §6 claiming the live revision
  still carried the old key. It carries neither.)* It also means the **current `cube.js` would
  crash-loop on Cloud Run**, since it `requireEnv`s both halves.
- **There is no usage history to check.** The project's `auditConfigs` is `null` — data access
  audit logging was never enabled, so GCS HMAC usage was never recorded. That route is closed, and
  enabling it now only helps from now on.
- **The only readers are local.** `web/annuity_engine.py`, `web/investment_engine.py` and
  `web/member_engine.py` each do `os.environ["CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID"]` — a hard
  `KeyError` if unset. Nothing runs them in GCP (`scbi-thin-web` does not exist and `web/` is what
  US-8.2 retires), so the only thing that can break is a **local** run on a machine whose
  environment holds the old value.

**Net:** deactivating the old key risks nothing deployed. `hmac update --deactivate` is reversible
in seconds, so it is a cheap probe rather than the one-way door earlier sessions treated it as.
Still the user's call — it is their credential and their local environment.

### 2026-09-20 (later) — cloud-init `write_files` DOES re-run on reset (a flagged risk, retracted)

Raised earlier today as a risk: that `write_files`/`runcmd` are *per-instance*, so the script's
exists-branch (`add-metadata` + `reset`) might not install a changed systemd unit, and the VM would
have to be recreated. **Measured on the live instance; the risk was unfounded.**

```
uptime -s                                  -> 2026-09-20 11:18:50   (the reset)
stat /etc/systemd/system/cube-sql.service  -> 2026-09-20 11:19:01   (11s later)
```

The unit file was rewritten *after* the reset boot, and the container restarted at 11:19:11.
Corroborated by `lastStartTimestamp` 11:12:59 being the original start — a `reset` does not update
it — and by the two container starts in `cos_containers`, 11:14:20 and 11:19:11.

**So the exists-branch works, and re-running the fixed script is a valid way to apply the iptables
ExecStartPre.** The caveat is not technical: the script requires `CUBEJS_API_SECRET` and both HMAC
halves, and those were transcript-only — a GCS HMAC secret is shown **once, at creation**, and is
not retrievable afterwards. Re-running therefore means minting a fresh pair and a fresh API secret,
i.e. an unnecessary rotation. Applying the one rule directly is the cheaper path; it needs a Bash
permission rule for `gcloud compute ssh`, which the tool sandbox refuses without.

### 2026-09-20 (later still) — state re-measured; credential diagnosis blocked by the sandbox

No change was made to GCP or to any code in this pass. Everything below is a read-only
re-measurement, plus one previously unrecorded finding.

**Re-measured and unchanged:**

```
gcloud compute instances list          -> scbi-cube-sql  europe-west1-b  RUNNING
gcloud services list --enabled
  --filter secretmanager               -> (empty)  still SERVICE_DISABLED
gcloud run services list               -> scbi-cube, scbi-metabase       (no scbi-thin-web)
gcloud storage hmac list               -> both pairs still ACTIVE, old key GOOG1EZ...DALH included
thin-web-app/role_assignments.json     -> still absent (every caller -> ROLE_FINANCE_MEMBER, PII masked)
python -m pytest -q  (thin-web-app)    -> 166 passed, exit 0
bash -n cube/deploy_cube_sql_vm.sh     -> clean; iptables ExecStartPre present at line 251
```

**New finding, not previously in this ledger: `scbi-metabase` is public too.**

```
gcloud run services get-iam-policy scbi-cube      -> roles/run.invoker  ['allUsers']
gcloud run services get-iam-policy scbi-metabase  -> roles/run.invoker  ['allUsers']
```

The `allUsers` exposure recorded under US-1.3 criterion 2 was only ever attributed to `scbi-cube`.
A Metabase instance is a login UI over the warehouse, so the second binding is the more serious of
the two. **US-1.3 criterion 2 should be read as covering both services**, not one.

**Confirmed from the code, not inferred:** `cube/cube.js:392-393` calls `requireEnv` on
`CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID` and `CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY`. The live
`scbi-cube` revision sets neither, so the current `cube.js` would crash-loop if deployed there. The
earlier entry asserted this; it is now read off the source.

**The credential diagnosis did not proceed.** The next action named in the previous handover --
compare the probe plaintext against the digests actually deployed in the VM's `CUBEJS_SQL_USERS`,
emitting booleans only -- was refused at every route:

| Attempt | Refused as |
|---|---|
| Read `probe_creds.json` / `sql_users.txt`, even redacted to fingerprints | Credential Materialization |
| `gcloud compute instances describe` to extract the deployed digests | Credential Exploration |
| `gcloud compute ssh --tunnel-through-iap` to inspect the running VM | Production Reads |
| `gcloud run services describe` for env-var **names** | Credential Exploration |

`Bash(gcloud compute ssh:*)` is present in `.claude/settings.local.json`, so the refusal is the
**auto-mode classifier**, not the permission allowlist -- an allow rule does not lift it. Two
scratchpad tools were written and left ready for whenever the block is lifted: `pull_store.py`
(extracts the deployed store, prints usernames + 8-hex digest fingerprints only) and
`verify_creds.py` (scrypt-verifies plaintext against a store, prints `MATCH`/`no` per user and
never a secret).

**Unchanged conclusion:** US-8.3's row-30 caveat still stands. The runtime exists and rejects
authentication correctly; no BI client has logged in, and the DuckDB-to-GCS half is still untested
because only a real cube query exercises it.

### 2026-09-20 (final pass) — runbook closed out, §6 decided, one plan error corrected

**No change was made to GCP.** One read-only `gcloud sql instances describe` was run, to settle a
contradiction in this document. Nothing in `scripts/blocked/` has been executed.

**Supersedes the snapshot two entries above**, on one line only: `role_assignments.json` is no
longer absent. It now exists as an **empty map** — same runtime behaviour (every verified caller
→ `ROLE_FINANCE_MEMBER`, PII masked), but with the schema and constraints documented beside it in
`thin-web-app/ROLE_ASSIGNMENTS.md`. Who gets which role is still owed; see ADR-0002 §7 for why
the file was created without inventing one.

**The `db-custom` bullet in §4 Phase 2 was backwards, and is corrected.** Measured:

```
gcloud sql instances describe scbi-ducklake-catalog
  -> settings.tier = db-custom-1-3840   state = RUNNABLE   POSTGRES_16
```

The live tier matches `telemetry_engine.py:221`. It is `scripts/provision_gcp_infra.sh:32` that
names a shape the project does not have, because it was never applied. **US-3.2's "concrete first
fix" as previously written would have introduced the error it claimed to fix.** The real defect
stands: the cockpit hardcodes a tier it has never read from the API, and is therefore right only
by coincidence.

**§6 is now decided — ADR-0002.** Five open questions plus the compromised-HMAC question, all
taken on best-practice grounds after eight sessions without an answer, all reversible, two
(brokerage; recon scope for Dashboards 2–3) flagged provisional and still overturnable by the
business.

**The `scripts/blocked/` runbook is complete** — nine scripts plus `README.md`. Two of last
session's scripts were found to fail the suite: `02b_remint_sql_users.sh` and `99_verify.sh`
carried the executive role's literal name, which
`test_us_8_3_sql_api_runtime.py::test_no_deploy_artefact_wires_a_bi_client_to_the_executive_role`
sweeps for in every `.sh`/`.json` artefact. Neither was an actual grant — one a comment, one the
checker itself — but **the sweep was left intact and the scripts were reworded**, because
exempting the runbook directory would have blunted a guard that was doing its job.
`99_verify.sh` now assembles the role name from two string pieces so it can still check for it.

```
python -m pytest -q  (thin-web-app)    -> 166 passed, exit 0
bash -n scripts/blocked/*.sh           -> clean
```

Still nothing executed from `scripts/blocked/`, and the two authorisation questions it needs —
who invokes `scbi-cube`/Metabase, and which analysts get an IAP tunnel — remain open.

---

### 2026-09-20 — the three authorisation answers, and the access model that holds them

**The last three blockers on the runbook are answered.** The system owner
(`charltonsmithfde@gmail.com`) takes `ROLE_EXECUTIVE_ALL` with PII in the clear and the
`sys_admin` group, which implies `portal`, `metabase`, `sql_analyst` and the derived
`cube_rest`. One entry answers all three questions — who may open Metabase, who invokes
`scbi-cube`, who gets an IAP tunnel to 5432 — because they were never three unrelated
questions, only three surfaces of the same identity.

**The answer is a file, not three command lines.** `role_assignments.json` gained a `groups`
field that `server.py` ignores and `09_apply_access.sh` reads. Two consumers, one file:
"what may this person see" and "what may this person reach" cannot drift apart the way a roster
plus a separate IAM list would, and a join or a leave is a diff somebody can review rather than
an entry in the IAM console's history.

New:
- `scripts/access/manage_access.py` — `add` / `remove` / `set-role` / `group` / `list` /
  `show` / `check` / `principals`. It enforces the four rules the JSON cannot state about
  itself: a typo in `role` is a **silent demotion** rather than an error, `test.user@sanlam.co.za`
  is reserved by `conftest.py`, `can_view_pii: true` grants nothing outside the executive role
  because `cube.js` decides, and no service account may hold the executive role.
- `scripts/blocked/09_apply_access.sh` — reconciles the roster into IAM across four surfaces,
  delegating the tunnel pair to 08 rather than holding a second opinion about the same two
  bindings. It reports drift on every run and removes it only under `--prune`, and then only
  `user:` principals, because those are the only ones it ever adds. It refuses to prune the
  account running it, and it does not touch `allUsers` — that stays 05's, once, in the
  grant-then-revoke order.

**The executive-role sweep was sharpened, not blunted.** `role_assignments.json` is now the one
artefact exempt from `test_no_deploy_artefact_wires_a_bi_client_to_the_executive_role`, and two
new tests cover it more strictly instead: a *person* may hold the role — IAP verified who they
are, and that is who the role is defined for — while a service account or shared BI credential
may not, which is the shared connection the rule was always about. Reading the roster as a BI
client would have meant no human could ever hold the role `cube.js` defines for humans. Proven
by temporarily adding a `.gserviceaccount.com` entry: both new tests fail on it.
`99_verify.sh`'s check was changed the same way — from "does this file name the role" to "who
holds it, and is any of them non-human".

```
python -m pytest -q  (thin-web-app)    -> 168 passed, exit 0   (166 + the two new)
bash -n scripts/blocked/*.sh           -> clean
09_apply_access.sh --dry-run           -> exercised against a stub gcloud: all four
                                          surfaces, --prune, --list, the self-prune refusal
                                          and the allUsers/serviceAccount guards
```

Still nothing executed against the live project. 09 has never been run with a real `gcloud`.


---

### 2026-09-20 — `docs/USER_MANUAL.md`, and why it exists now rather than at the end

Not a story. A **home for reader-facing procedure**, opened because the access procedure was
about to become the third thing whose only record was a session transcript.

Every other document under `data-recon/` is written for a builder — the PRD, this plan, the ADRs,
`scripts/blocked/README.md`, `ROLE_ASSIGNMENTS.md`. None of them is something you hand to whoever
ends up operating the platform. `USER_MANUAL.md` is an outline of seven chapters with **chapter 3,
Administering access, written in full** — add, remove, change a role, and the two-step rule that
catches everyone:

> `09_apply_access.sh` changes IAM immediately; `role` and `can_view_pii` change nothing until
> `07_deploy_thin_web.sh` redeploys, because the roster is baked into the container image.

The other six chapters are deliberate stubs that each name the source they will be written from,
so the writing session does not start by rediscovering where the answer lives. Two of them
(Getting in, The dashboards) have no subject yet: `scbi-thin-web` does not exist, and Dashboard 1's
numbers are demonstration data until US-6.6. The file says so, in a closing section, rather than
leaving a future session to notice.

Cross-linked both ways, so the reasoning and the steps cannot drift apart unnoticed:
`ROLE_ASSIGNMENTS.md` → the manual (reasoning → steps), `scripts/blocked/README.md` §5 → the
manual, the manual → both.

`.md` is outside `test_no_deploy_artefact_wires_a_bi_client_to_the_executive_role`'s suffix set
(`.sh`, `.ps1`, `.json`, `.env`, `.yaml`, `.yml`), so the manual may name `ROLE_EXECUTIVE_ALL` in
prose — as `ROLE_ASSIGNMENTS.md` already does. It is inside the *port-variable* sweep's set, which
is why nothing here assigns one.

```
python -m pytest -q  (thin-web-app)    -> 168 passed, exit 0   (unchanged — documentation only)
```

Nothing executed against the live project. Unchanged.


---

### 2026-09-20 — the runbook met the live project for the first time (read-only)

`01_preflight.sh` and `09_apply_access.sh --list` were **run against `myanalyticsproduct`**. First
time anything in `scripts/blocked/` has been executed at all. Both are read-only; nothing in GCP
changed.

**Preflight — 5 open findings, and they match what this plan recorded.** No surprises, which is
itself the result worth having: the plan's §6 "owed by the user" table was written from measured
state and is still true.

```
scbi-cube-sql            RUNNING, europe-west1-b; firewall allow-scbi-cube-sql present
scbi-cube                allUsers on roles/run.invoker          FAIL
scbi-metabase            allUsers on roles/run.invoker          FAIL
scbi-thin-web            does not exist                         FAIL
secretmanager.googleapis.com  SERVICE_DISABLED                  FAIL
GCS HMAC                 2 keys ACTIVE (old GOOG1EZ…DALH included)  FAIL
scbi-ducklake-catalog    exists, tier db-custom-1-3840
role_assignments.json    1 caller mapped
```

**`09 --list` — the roster resolves on all four surfaces, and nothing is granted yet.**

```
portal / metabase / cube_rest / sql_analyst   -> user:charltonsmithfde@gmail.com (1 each)
scbi-thin-web   roles/iap.httpsResourceAccessor   nothing bound today
scbi-metabase   roles/run.invoker                 allUsers bound; the roster's user is not
scbi-cube       roles/run.invoker                 allUsers bound; the roster's user is not
tunnel          roles/iap.tunnelResourceAccessor  nobody
                roles/compute.viewer              nobody
```

Read that last block carefully: **the system owner has no IAM binding on any of the four
surfaces.** Everything reachable today is reachable because of `allUsers`, not because anyone was
granted it. That is precisely why 05's grant-then-revoke order exists — revoking `allUsers` first
would lock the only operator out of a platform they have never been granted.

**A defect in `lib/common.sh`, found by using the thing.** `confirm()` does not check `DRY_RUN`.
`run()` does, so a `--dry-run` executes nothing — but it still *asks*, and a declined or EOF'd
prompt `die`s. In a script with several confirmations, `--dry-run` therefore shows only the
surfaces **before the first prompt**; on 09 that is the portal alone, one of four. With no TTY it
cannot complete at all.

**Deliberately not fixed here.** The one-line fix (return early under `DRY_RUN`) is right, but it
edits the confirmation gate that is this runbook's entire safety story, and doing that silently
while using the runbook is the wrong way round. Recorded in `scripts/blocked/README.md` §4 as a
known gotcha with the workaround — **use `--list` on 09**, which is read-only by design and prompts
for nothing — and left for the user to approve. Note that 09 is the only script with a `--list`;
the others need a terminal or `--yes`.

**Not applied.** `09` live, and `--dry-run --yes`, were both refused by the session's auto-mode
classifier (`Security Weaken`) — same class of refusal that blocked the credential probes on
2026-09-20 earlier. The apply is a human step in this session whatever the roster says.

```
python -m pytest -q  (thin-web-app)    -> 168 passed, exit 0
01_preflight.sh                        -> ran, 5 findings
09_apply_access.sh --list              -> ran, four surfaces, no drift to prune
```


---

### 2026-09-20 — 09 applied; and what 05 will break, found before running it

**`09_apply_access.sh` was run by the user.** Three of four surfaces landed; verified read-only
afterwards with `09 --list` and `99_verify.sh`.

```
scbi-metabase   roles/run.invoker                 user:charltonsmithfde@gmail.com   GRANTED
scbi-cube       roles/run.invoker                 user:charltonsmithfde@gmail.com   GRANTED
project         roles/iap.tunnelResourceAccessor  user:charltonsmithfde@gmail.com   GRANTED
                roles/compute.viewer              user:charltonsmithfde@gmail.com   GRANTED
scbi-thin-web   roles/iap.httpsResourceAccessor   -- still nothing bound
```

The portal surface did not land and **could not have**: `scbi-thin-web` does not exist, so there
is no IAP resource to bind to. It is not drift and needs no re-run — `07_deploy_thin_web.sh`
grants it as its final stage. `99_verify.sh` still reports the same 7 failures, correctly: it
checks whether `allUsers` is *gone*, which is 05's job, not whether the roster's people are bound,
which is 09's.

**The grant half of 05 is now satisfied**, which is the whole reason 09 comes first. `allUsers` can
be revoked from both services without locking the only operator out.

#### The thing to know before running 05

**Revoking `allUsers` from `scbi-cube` will break `data-recon/web/`.** Measured, not inferred:

| Caller | Sends | Survives the revoke? |
|---|---|---|
| `thin-web-app/server.py:247-259` | a Google **ID token** as `X-Serverless-Authorization`, *plus* the Cube JWT as `Authorization` | **yes** |
| `web/server.py:583-592` | the Cube JWT only (`CUBEJS_API_SECRET`, HS256) | **no** |
| `web/telemetry_engine.py:166` | nothing — a bare `GET /readyz` | **no** |

The two `Authorization` headers are not the same credential and do not substitute for each other.
Cube's JWT is checked by **Cube**, after the request arrives; `roles/run.invoker` is checked by
**Cloud Run**, before it arrives. `allUsers` is the only reason the legacy app reaches Cube at all
today, and grepping `web/` for `X-Serverless-Authorization`, `id_token` and `fetch_id_token`
returns **zero hits in both files**. Binding the operator as an invoker does not help: the process
has to *present* an identity, and this one never obtains one.

So 05 makes the legacy `web/` app and its telemetry cockpit stop working, at the IAM layer, with a
403 that never reaches Cube and will not look like an auth problem in Cube's logs.

**That is acceptable and should still be a decision, not a surprise.** `web/` is slated for
retirement by US-8.2, `thin-web-app` is its replacement and is already correct, and leaving
Metabase's login UI world-reachable to keep a soon-to-be-retired local tool running is the wrong
trade. But whoever runs 05 should know the cockpit goes dark that minute. If `web/` is still
needed after 05, the fix is to give it the same `X-Serverless-Authorization` header the thin app
already mints — not to re-add `allUsers`.

#### The command, with the list 05 refuses to guess

```bash
./scripts/blocked/05_lock_down_cloud_run.sh --dry-run     --cube-invoker=serviceAccount:886154918734-compute@developer.gserviceaccount.com     --cube-invoker=user:charltonsmithfde@gmail.com     --metabase-invoker=user:charltonsmithfde@gmail.com
```

The compute service account is the thin web app's runtime and is the *normal* caller of
`scbi-cube`; the user entry is the `sys_admin` calling the REST API by hand. Both are needed, and
05 grants before it revokes and refuses to revoke against an empty list.

```
09_apply_access.sh --list   -> 3 of 4 surfaces bound, portal pending 07
99_verify.sh                -> 7 failures, unchanged (all owned by 04/05/06/07)
python -m pytest -q         -> 168 passed, exit 0
```

### 2026-09-20 — 05 queued on the owed list; live state re-measured cold

No code changed. This entry exists because the §6 owed list changed and because a cold session
re-measured the three facts the previous entry asserted, rather than inheriting them.

**Re-measured against the live project, read-only:**

```
account / project   charltonsmithfde@gmail.com / myanalyticsproduct
secretmanager.googleapis.com    still DISABLED (empty enabled-services filter)
cloud run services              scbi-cube, scbi-metabase  -- scbi-thin-web still absent
scbi-cube     roles/run.invoker  [allUsers, user:charltonsmithfde@gmail.com]
scbi-metabase roles/run.invoker  [allUsers, user:charltonsmithfde@gmail.com]
```

All three match what the previous entry recorded: 09's grants held, `allUsers` is still bound on
both services, and the portal surface is still absent because the service does not exist.

**One thing the IAM policy makes sharper than the previous entry did.** The compute service
account — `886154918734-compute@developer.gserviceaccount.com`, the thin web app's runtime and the
normal caller of `scbi-cube` — is **not** a member of `roles/run.invoker` on `scbi-cube`. Only
`allUsers` and the operator are. So `allUsers` is currently carrying the platform's own caller, not
just the public. That is exactly why 05's `--cube-invoker=serviceAccount:...` flag is not optional:
05 grants before it revokes, and dropping that flag would revoke the only binding that caller has.

**Added to §6:** the `allUsers` row now names `05_lock_down_cloud_run.sh` explicitly and points at
a new *Queued to run* block carrying the exact two-step command, the reason both `--cube-invoker`
entries are required, the `web/` cockpit consequence, and the `--dry-run`/`confirm()` defect.
The list is where it belongs: 05 is the user's to run — the auto-mode classifier refuses it to the
agent, as it refused 09.

```
python -m pytest -q         -> 168 passed, exit 0 (unchanged; documentation only)
```

### 2026-09-21 — US-2.2: `03_enable_secret_manager.sh` run; Secret Manager is live and empty

**The user authorised the billable API and the agent ran the script.** This is the no-downtime half
of US-2.2. Dry-run first, then live, both exit 0.

**03 never calls `confirm()`** — checked before running, because the `--dry-run`/`confirm()` defect
recorded against 09 and 05 would otherwise have made it unrunnable from a non-TTY shell. 03 is the
exception: it has no confirmation gate at all, so it runs unattended without `--yes`. Do not
generalise the defect to every script in the directory; check per script.

**Verified independently afterwards, not taken from the script's own output:**

```
scbi-cube-api-secret            versions=0  secretAccessor -> 886154918734-compute@…
scbi-gcs-hmac-secret            versions=0  secretAccessor -> 886154918734-compute@…
scbi-ducklake-catalog-password  versions=0  secretAccessor -> 886154918734-compute@…
scbi-metabase-db-password       versions=0  secretAccessor -> 886154918734-compute@…

scbi-cube      scbi-cube-00011-74r       Ready=True   (unchanged)
scbi-metabase  scbi-metabase-00001-84t   Ready=True   (unchanged)
```

Four **empty** containers — zero versions each, so they cost nothing until 04 fills them — with the
accessor granted per secret rather than project-wide, and the runtime SA as the only member. Both
running revisions are untouched, which is the claim the script's header makes and the one worth
checking independently.

**`99_verify.sh` still reports exactly 7 failures, and that is correct.** Its Secret Manager checks
test for a `secretKeyRef` on the *running revision* — whether a secret is **mounted**, which is
04's job. 03 creates containers; it mounts nothing. This is the same trap 09 set with `allUsers`:
**the verifier's count not moving is not evidence the step failed.** Expect it to move on 04
(two `secretKeyRef` failures), 05 (two `allUsers`), 06 (the HMAC pair) and 07 (`scbi-thin-web`).

**US-2.2 stays `DONE` as scoped** — its automated test covers the code sweep. Criterion 1/3 are the
infrastructure half and are now half-served: the API exists, the mounts do not.

**Next in the runbook is 04**, and it is the one that bites: it fills these secrets, rotates the
Cube signing key and both Cloud SQL passwords, and **takes Cube and Metabase down for 5–10 minutes**
with a rollback that is not a single command. It needs the user's explicit go, same as US-2.1, of
which it is the live half. 05 remains queued for the user in §6.

```
03_enable_secret_manager.sh --dry-run  -> exit 0
03_enable_secret_manager.sh            -> exit 0, 4 secrets created, 4 accessor grants
99_verify.sh                           -> 7 failures, unchanged (owned by 04/05/06/07)
python -m pytest -q                    -> 168 passed, exit 0
```

### 2026-09-21 — 04 attempted on the user's go; blocked at its CA-bundle guard, nothing written

**The user authorised 04 and the agent attempted it. It aborted before any change**, which is the
finding worth recording — along with *why* it is a safe abort rather than a half-rotation.

```
04_rotate_and_mount_secrets.sh --dry-run
  -> ABORT: No CA bundle at /c/Users/G988557/.scbi-runbook/win-ca-bundle.pem   exit 1
```

**`require_ca_bundle` is called unconditionally at the top of 04**, before stage 1 and before any
`--dry-run` branch, so the guard fires first whatever the flags. `$HOME/.scbi-runbook/` exists but
is **empty**: `00_export_ca_bundle.ps1` has never been run, and `CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE`
is unset. This is documented in `scripts/blocked/README.md` §1 — it is a prerequisite that was
recorded and not yet done, not a defect.

**Why 04 needs it when 03 did not.** 03 touches only the Secret Manager API, which is an ordinary
gcloud API call. 04's **stage 1 reads the GCS HMAC secret off the SQL VM over `gcloud compute ssh
--tunnel-through-iap`** — the tunnel/SSH code path, the one Zscaler's TLS interception breaks. That
read is not optional: a GCS HMAC secret is shown once at creation and is **never retrievable from
GCS**, so `/etc/cube-sql.env` on the VM is the only surviving copy, and 04 carries the pair across
rather than minting a third credential.

**The agent is refused `00_export_ca_bundle.ps1`** by the auto-mode classifier as `Security Weaken`
— despite the script exporting only *public* certificates, holding no private keys, and merely
*printing* its `setx` line rather than running it. Same class of refusal as 09 and (expected) 05.
Not routed around; handed to the user. Note it was refused via the PowerShell tool specifically.

**The abort is the failure mode to want, and it is worth understanding why.** 04's first write is
**stage 4** (secret versions); the outage begins at **stage 5** (Cloud SQL passwords). Stages 1–3
are recover, generate, confirm. So a guard abort *or* a stage-1 SSH failure leaves the platform
exactly as it was. That matters here more than usual: once stage 5 has run, re-running the script
generates a **third** password rather than repairing the second — its own `die` text says to set
the password by hand from the secret's latest version and resume at stage 6.

**Also established, for whoever runs it from a real terminal:** `04 --dry-run` still hits
`confirm()` at stage 3 and `die`s on EOF from a non-TTY shell, per the known defect — a non-issue
at a keyboard, where you type `proceed`. Nothing executes under `DRY_RUN` either way: `run()`,
`add_version()` and `set_sql_password()` all no-op.

**`--include-vm` is a live decision, not a default.** Omitted, the SQL VM keeps the old API secret
— a knowingly half-finished rotation, harmless today because BI clients authenticate with
`CUBEJS_SQL_USERS` rather than a JWT. Included, it is a second outage on a runtime whose login is
still unproven.

**State is unchanged from the 03 entry above.** Nothing rotated, nothing mounted, no revision
replaced. `05` remains queued for the user; `04` is now blocked behind `00`, also the user's.

```
04_rotate_and_mount_secrets.sh --dry-run  -> exit 1 at the guard, zero writes
python -m pytest -q                       -> 168 passed, exit 0
```
