# PRD — Architecture Realignment: Sanlam Online Analytics Portal

| | |
|---|---|
| **Status** | Draft for review |
| **Author** | SC BI Engineering |
| **Date** | 2026-09-19 |
| **Supersedes** | Nothing. Complements [`MIGRATION_PLAN.md`](./MIGRATION_PLAN.md), which described the target architecture but was implemented as a façade. |
| **Scope** | `data-recon/thin-web-app`, `data-recon/cube`, `data-recon/web`, GCP project `myanalyticsproduct` |
| **Out of scope** | dbt model changes in `dbt-scbi-cnf` / `dbt-scbi-sal`; Snowflake; Power BI report authoring |

---

## 1. Problem Statement

`MIGRATION_PLAN.md` declared six architecture principles. An audit on 2026-09-19 found that the
codebase satisfies the *shape* of those principles but violates four of them materially. The portal
currently presents fabricated numbers to users behind a UI badge that reads
`scbi-cube Cloud Run Active (Linked)`.

### 1.1 Evidence

| # | Finding | Evidence |
|---|---|---|
| **P1** | **The DuckLake catalog does not exist.** Cloud SQL `scbi-ducklake-catalog` / database `ducklake_catalog` is provisioned and billed, but nothing in the repo runs `ATTACH ... (TYPE ducklake)`. Cube reads Parquet globs via `read_parquet()`. There is no catalog, no snapshot isolation, no ACID, no time travel, no schema evolution. The only live consumer of that instance is Metabase's `metabase_appdb`. | `cube/cube.js` `initSql`; `scripts/provision_gcp_infra.sh:41`; zero `ATTACH` hits repo-wide |
| **P2** | **Dashboard 1 (Member Analysis Summary) is synthetic.** `handle_member_analysis_query()` never calls `query_cube()`. It multiplies hardcoded constants (`base_total = 366784`, `base_total_aua = 122.33e9`) by hand-tuned per-filter scalars (`"pension fund"` → ×0.505, brokerage → ×0.42) and derives all five tabs from the result. It returns `"live_feed": true`. `handle_cube_slicers()` is likewise hardcoded master lists with substring-match cascade rules, and **every** slicer route — member, investment, annuity — is aliased to it. | `thin-web-app/server.py:160-486` |
| **P3** | **RBAC is client-controlled.** There is no user authentication. `currentRole` is a `<select>` in `app.js:10`, sent as `?role=…&maskPii=…`, and `server.py` mints an HS256 JWT asserting whatever arrived. Any caller can self-assert `ROLE_EXECUTIVE_ALL` + `canViewPii` and unmask member identifiers. Cube's `checkSqlAuth` echoes back `auth.password` rather than verifying it, and derives role from a username prefix. | `app.js:10,537`; `server.py:52-62`; `cube/cube.js` `checkSqlAuth` |
| **P4** | **Credentials are committed.** GCS HMAC access key + secret appear as in-repo defaults in four files; `CUBEJS_API_SECRET = "ScbiCubeSecretToken2026!"` is hardcoded in both servers; Cloud SQL passwords are script defaults. `thin-web-app/server.py`'s own docstring claims "ZERO GCS access keys" — true of that file, false of the tree. | `cube/cube.js:70-72`; `web/{member,investment,annuity}_engine.py`; `scripts/provision_gcp_infra.*` |

### 1.2 Contributing root cause

The semantic layer is incomplete, so there was nothing real for Dashboard 1 to query.
`cube/model/cubes/` defines **3 facts and 10 dimensions over 12 of the 44 migrated tables**.
The RBAC map and the migration registry both name 12 cubes; 8 of them
(`FundAnalyticsMonthlyMetrics`, `MemberTransactions`, `AssetflowsMemberMonthly`,
`DigitalPortal*`, `InFundExitMemberMonthly`) are allowlisted but undefined, so four of the five
roles currently resolve to nothing queryable.

Worse, the one member cube that does exist is built on the wrong fact.
`MemberMonthly` wraps `cnf__fact_member_investment_aua`, which carries no age, gender, salary,
contribution or retirement columns. And `DimMember.currentAge` is declared as
`sql: 'current_age'` — **a column that does not exist**; the dbt model emits `member_age`. That
dimension would throw on first use, which is direct evidence Dashboard 1 was never once executed
against Cube.

### 1.3 Why this matters

- **Correctness**: the portal reports a member count and R122bn AUA that are not derived from data.
- **POPIA**: a client-side dropdown is the only control preventing PII unmasking.
- **Credibility**: the existing `CASCADING_FILTERS_TEST_REPORT.md` reports 19/19 passing in 0.89s.
  Those tests assert `total = male + female` and `sum(bins) = total`, which the fabrication layer
  constructs to be true by definition. The suite is tautological and cannot fail.
- **Cost**: a `db-custom-2-7680` Cloud SQL instance serves one Metabase app DB.

---

## 2. Goals & Non-Goals

### 2.1 Goals

- **G1** Every number rendered in the portal is traceable to a Cube query over lakehouse data.
- **G2** All eight slicers on Dashboard 1 cascade bidirectionally from live data, with zero hardcoded option arrays.
- **G3** A user's role is established by an identity provider, never asserted by the browser.
- **G4** No credential of any kind is resolvable from the repository.
- **G5** The DuckLake catalog is either genuinely adopted or explicitly retired — no billed placeholder.
- **G6** The reconciliation suite compares portal output against independently computed ground truth and is capable of failing.

### 2.2 Non-Goals

- Rebuilding Dashboards 2 (Investment) and 3 (Annuity) — they already query Cube. They inherit the security and slicer work only.
- Changing dbt marts or Snowflake. The lakehouse already contains every table required (44/44 `COMPLETED`, 2026-09-17).
- Visual redesign. Look, feel, CSS, loading overlays and the SysAdmin cockpit are preserved verbatim.
- Pre-aggregations / performance tuning beyond the stated SLA.

### 2.3 Success Metrics

| Metric | Baseline | Target |
|---|---|---|
| Dashboard 1 API responses derived from Cube | 0% | 100% |
| Hardcoded slicer option arrays in `server.py` | 12 lists | 0 |
| Cube-defined cubes vs. RBAC-allowlisted cubes | 13 def. / 12 named, 8 missing | parity, 0 missing |
| Secrets resolvable from repo | ≥ 6 | 0 |
| Endpoints accepting a client-asserted role | all | 0 |
| Recon tests that compare against independent ground truth | 0 / 19 | ≥ 15 |
| Mutation test: corrupt a measure → suite fails | fails to detect | detects |
| p95 slicer latency / query latency | n/a (fabricated) | < 800 ms / < 2500 ms |

---

## 3. Target Architecture

```
Snowflake SC_BI_PRODUCT_PPE
    │  scripts/migrate_cube_data_to_parquet.py  (44 tables, batch)
    ▼
GCS gs://scbi-ducklake-myanalyticsproduct/{scbi_cdp_mart,scbi_sdp_mart}/<table>/*.parquet
    │  DuckDB httpfs, credentials from Secret Manager via Workload Identity
    ▼
Cube.js  scbi-cube  (Cloud Run, europe-west1)
    │    ├─ semantic model: 12 cubes, all 44 tables reachable
    │    ├─ RBAC from verified JWT claims
    │    └─ PII masking in SECURITY_CONTEXT
    ▼
thin-web-app  (Cloud Run, IAP-fronted)
    │    └─ pure proxy: no arithmetic, no constants, no fallbacks
    ▼
Browser
```

**Invariant (new, testable):** `thin-web-app/server.py` contains no numeric literal that reaches a
response body, and no `except` clause that substitutes data for an error. Enforced by CI (US-7.4).

---

## 4. Canonical Data Model for Dashboard 1

This section is the contract the Cube model must implement. Derived from the Power BI
`FundAnalyticsMonthlyMetrics` semantic model (`pbi-scbi/semantic_models/use-case/FundAnalyticsMonthlyMetrics`),
which is the authoritative lineage for this dashboard.

### 4.1 Grain and facts

| Cube | Source table | Grain | Supplies |
|---|---|---|---|
| `FundAnalyticsMonthlyMetrics` | `cnf__agg_consolidated_member_measures_monthly` | member × month × product × org keys | AUA, contributions, risk premium, risk benefit cover, **all 8 filter keys** |
| `MemberSegmentation` | `cnf__fact_member_segmentation` | member × month | `age`, `retirement_age`, `term_to_retirement`, `years_past_early_retirement`, `monthly_salary`, `pensionable_service_years`, and their `*_band_description` columns |

`cnf__agg_consolidated_member_measures_monthly` is the correct spine: it is the only member-domain
fact carrying `date_sk`, `client_hk`, `fund_hk`, `employer_hk`, `paypoint_hk`, `member_hk`,
`revision_association_hk`, `aggregator_hk`, `risk_product_hk`, `investment_product_hk`,
`member_segmentation_hk/nk` **and** the measures. `MemberMonthly`
(`cnf__fact_member_investment_aua`) is retained for AUA-only queries but must not back Dashboard 1.

### 4.2 Join graph (mirrors the PBI relationships)

```
DIM_DATE ─────── date_sk ──────┐
DimClient ────── client_hk ────┤
DimFund ──────── fund_hk ──────┤
DimEmployer ──── employer_hk ──┤
DimPaypoint ──── paypoint_hk ──┼── FundAnalyticsMonthlyMetrics
DimMember ────── member_hk ────┤
DimRevisionAssociation ─ revision_association_hk ─┤
DimAggregator ── aggregator_hk ┤
DimRiskProduct ─ risk_product_hk ┘
                               │
   MemberSegmentation ── member_segmentation_nk ──┘   (PBI marks inactive; see US-4.3)
```

### 4.3 The eight slicers — corrected bindings

`MIGRATION_PLAN.md` and the earlier test plan bind Brokerage to `DimBrokerConsultant`. **That is wrong
for this dashboard.** `broker_consultant_hk` appears only on the annuity facts. The member-domain
join path to a brokerage is `aggregator_hk → cnf__dim_aggregator.aggregator_brokerage_name`.

| Slicer | Cube member | Source column | Notes |
|---|---|---|---|
| Date | `DimDate.formattedDate` | `dim_date.date_nk` | `UPPER(STRFTIME(date_nk,'%d-%b-%Y'))`; options = snapshots present in the fact |
| Fund | `DimFund.fundName` | `cnf__dim_fund.fund_name` | |
| Business Unit | `DimFund.fundClassification` | `cnf__dim_fund.fund_classification` | SUS / SCS |
| Client | `DimClient.clientName` | `cnf__dim_client.client_name` | |
| Employer | `DimEmployer.employerName` | `cnf__dim_employer.employer_name` | |
| **Brokerage** | `DimAggregator.aggregatorBrokerageName` | `cnf__dim_aggregator.aggregator_brokerage_name` | **corrected** — via `aggregator_hk`, not `DimBrokerConsultant` |
| Association | `DimRevisionAssociation.revisionAssociationName` | `cnf__dim_revision_association.revision_association_name` | filter on name, display name; `_nk` is a code |
| Paypoint | `DimPaypoint.paypointClassification` | `cnf__dim_paypoint.paypoint_classification` | |

### 4.4 Known defects in the existing model

| Defect | Location | Fix |
|---|---|---|
| `DimMember.currentAge` → `sql: 'current_age'` | `SharedDimensions.js` | column is `member_age` |
| `MemberMonthly` lacks demographic columns | `MemberAnalysis.js` | demographics come via `DimMember` join; salary/contribution via `MemberSegmentation` |
| 8 RBAC-allowlisted cubes undefined | `cube.js` `ROLE_PERMISSIONS` | define them, or narrow the allowlists to what exists |
| 32 of 44 migrated tables have no view | `cube.js` `initSql` | generate views from a manifest (US-4.1) |

---

## 5. Cascading Filter Specification

### 5.1 Behavioural contract

1. **Data-driven**: every option in every slicer is the distinct result of a Cube query against the
   fact, never a literal.
2. **Bidirectional**: changing any slicer restricts the option set of all seven others to
   combinations that return ≥ 1 fact row.
3. **Selection-preserving**: a slicer's own options are computed *excluding* its own selection from
   the filter set, so the current value never vanishes from its own dropdown.
4. **Self-healing**: if a selection becomes invalid under a new filter combination, it resets to
   `All` and the UI surfaces which slicer was reset.
5. **Stateless server**: the full filter state travels on every request. No session state.
6. **Persistent across tabs**: switching sub-tab re-queries with the unchanged filter state.

### 5.2 Resolution algorithm

For active filter state `S` and target slicer `k`:

```
options(k) = SELECT DISTINCT <member(k)>
             FROM FundAnalyticsMonthlyMetrics
             WHERE  all filters in S except S[k]
             ORDER BY 1
```

Implemented as one Cube request per slicer (8 dimensions, `limit` applied), issued in parallel,
prefixed with `["All"]` by the client, not the server.

### 5.3 Cascade dependency matrix

Every slicer constrains every other — the DAG is complete. The table records only the *semantically
expected* narrowing used as test oracles:

| Changing → | Date | Fund | BU | Client | Employer | Brokerage | Association | Paypoint |
|---|---|---|---|---|---|---|---|---|
| **Date** | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Fund** | ✓ | — | ⇒ determines | ✓ | ✓ | ✓ | ✓ | ✓ |
| **BU** | ✓ | ✓ strong | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Client** | ✓ | ✓ | ✓ | — | ✓ strong | ✓ | ✓ | ✓ |
| **Employer** | ✓ | ✓ | ✓ | ✓ strong | — | ✓ | ✓ | ✓ strong |
| **Brokerage** | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ |
| **Association** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| **Paypoint** | ✓ | ✓ | ✓ | ✓ | ✓ strong | ✓ | ✓ | — |

`⇒ determines`: selecting a Fund fixes Business Unit to that fund's classification.

---

## 6. Epics & User Stories

Roles: **Analyst** (portal end user), **Data Engineer**, **Platform Engineer**, **Security Officer**,
**Product Owner**.

Every story is `DONE` only when its acceptance criteria are demonstrated by an automated test that
*fails against the current `main`*.

---

### EPIC 1 — Trust Boundary: Authentication & Role Enforcement  *(addresses P3)*

#### US-1.1 — Authenticate users before the portal serves anything

**Status** — **DONE (code)** 2026-09-20. Criteria 2–4 proven by `tests/test_us_1_1_auth_boundary.py` (26). Criterion 1 is infrastructure and remains owed: `scbi-thin-web` does not exist on Cloud Run yet. See EXECUTION_PLAN.md §6.
> **As a** Security Officer, **I want** every portal request tied to a verified identity, **so that**
> access to member data is attributable and revocable.

**Acceptance criteria**
- Cloud Run service `scbi-thin-web` sits behind Identity-Aware Proxy; `--allow-unauthenticated` is absent.
- An unauthenticated request to any `/api/*` path returns `401`, not data.
- The signed IAP JWT (`x-goog-iap-jwt-assertion`) is verified server-side against Google's public keys: signature, `aud`, `iss`, `exp`.
- Verification failure returns `401`. There is no bypass env var.

**Verification** — `tests/test_auth_boundary.py`: unauthenticated, expired-token, wrong-`aud`, and tampered-payload requests all return `401`.

#### US-1.2 — Derive role from identity, never from the request
> **As a** Security Officer, **I want** the user's role resolved server-side from their verified
> identity, **so that** a user cannot escalate by editing a URL.

**Acceptance criteria**
- A role-mapping source of truth exists (Google Group membership or a `role_assignments` table) keyed by verified email.
- `server.py` ignores `role` and `maskPii` request parameters entirely; passing them changes nothing.
- The Cube JWT is minted from the resolved role only.
- `GET /api/member_analysis/query?role=ROLE_EXECUTIVE_ALL&maskPii=false` as a `ROLE_FINANCE_MEMBER` user returns masked data.
- The role dropdown in `app.js` becomes a read-only display of the resolved role. Users with more than one entitlement get a selector restricted to roles they actually hold, re-validated server-side.

**Verification** — `tests/test_rbac_enforcement.py`: parameterised over all 5 roles × 3 dashboards; every attempted escalation is rejected. Test asserts `member_nk` is masked for all non-executive roles.

#### US-1.3 — Make Cube reject unverified callers

**Status** — **DONE (code)** 2026-09-20. Criteria 1, 2 and 4 proven by `tests/test_us_1_3_cube_auth.py` (22), which loads the real `cube.js` and calls the real `checkSqlAuth`. Criterion 3's infrastructure half is owed: `scbi-cube` still has `allUsers` bound to `roles/run.invoker`.
> **As a** Platform Engineer, **I want** `scbi-cube` to trust only signed tokens, **so that** the
> semantic layer is not an open endpoint.

**Acceptance criteria**
- `CUBEJS_API_SECRET` is loaded from Secret Manager; no default in code.
- `checkSqlAuth` verifies the supplied password against a credential store. The current
  `return { password: auth.password }` — which accepts any password — is removed.
- Cloud Run `scbi-cube` is `--no-allow-unauthenticated`; the thin app calls it with a service-account ID token.
- A request bearing a JWT signed with the old hardcoded secret is rejected.

**Verification** — `tests/test_cube_auth.py`: direct unauthenticated `POST /cubejs-api/v1/load` returns `403`; SQL API login with an arbitrary password fails.

#### US-1.4 — Close the RBAC allowlist gap

**Status** — **DONE** 2026-09-20. Proven by `tests/test_us_1_4_rbac_allowlist.py` (15).
> **As a** Security Officer, **I want** the cube allowlists to match the cubes that exist, **so that**
> permissions describe reality.

**Acceptance criteria**
- Every name in `ROLE_PERMISSIONS[*].allowedCubes` resolves to a defined cube, or is removed.
- A startup assertion fails the container if an allowlisted cube is undefined.
- `SHARED_DIMENSIONS` is reviewed: `DimMember` is removed from the unconditional whitelist, since it carries PII and currently bypasses the cube-boundary check for every role.

**Verification** — `tests/test_rbac_and_models.py` extended: for each role, enumerate allowlisted cubes and issue a trivial query to each; all succeed. For each non-allowlisted cube, assert `AccessDenied`.

---

### EPIC 2 — Secrets Elimination  *(addresses P4)*

#### US-2.1 — Rotate every exposed credential
> **As a** Security Officer, **I want** all credentials that ever appeared in the repo revoked,
> **so that** a leaked copy of the tree grants nothing.

**Acceptance criteria**
- GCS HMAC key `GOOG1EZOW…` is **deleted** in GCP, not merely removed from code.
- `CUBEJS_API_SECRET` is regenerated.
- Cloud SQL users `ducklake_admin`, `metabase_admin` have new passwords; Metabase is redeployed against the new one.
- A written note records that the tree is not currently a git repository, and that if any of these files were ever committed elsewhere, rotation — not deletion — was the required action. Rotation done ⇒ history exposure is moot.

#### US-2.2 — Source all secrets from Secret Manager
> **As a** Platform Engineer, **I want** runtime credentials injected at deploy time, **so that** no
> secret has an in-code default.

**Acceptance criteria**
- Secrets `scbi-cube-api-secret`, `scbi-gcs-hmac-key`, `scbi-gcs-hmac-secret` exist in Secret Manager.
- `cube.js` and every engine read from env with **no `||` fallback literal**; a missing variable raises at startup.
- Cloud Run services mount secrets via `--set-secrets`.
- Provisioning scripts take passwords from `read -s` / Secret Manager, never a `param` default.

**Verification** — `tests/test_no_secrets.py`: a regex sweep for `GOOG1`, `AKIA`, `ScbiCubeSecret`, `ChangeMe`, `Prod2026!` over `data-recon/**` returns zero hits. Wired into CI (US-7.4).

#### US-2.3 — Prefer keyless access
> **As a** Platform Engineer, **I want** Cube to read GCS via Workload Identity, **so that** there is
> no long-lived key to leak.

**Acceptance criteria**
- `scbi-cube` runs as a dedicated service account with `roles/storage.objectViewer` on the bucket only.
- DuckDB's GCS access uses the ambient credential chain where the driver supports it; HMAC from Secret Manager is the documented fallback with a rotation interval recorded.
- The bucket denies public access and uniform bucket-level access stays on.

---

### EPIC 3 — Catalog Decision: DuckLake or Retire  *(addresses P1)*

#### US-3.0 — Upgrade Cube 0.35.x → 1.7.x  *(hard prerequisite for US-3.1 Option A; ship before EPIC 3 implementation)*
> **As a** Data Engineer, **I want** the semantic layer running on a supported Cube major with pinned
> dependencies, **so that** DuckLake can be attached at all and the container stops drifting between builds.

**Why this is a blocker, not housekeeping** — ADR-0001 §3.1 verified empirically that
`@cubejs-backend/duckdb-driver@^0.35.0` binds to the legacy `duckdb` npm package, where
`ATTACH 'ducklake:…'` **segfaults the process (exit 139, reproducible)**. The same `ATTACH` succeeds on
`@duckdb/node-api@1.5.5-r.5`, which is exactly what `duckdb-driver@1.7.42` depends on. A version
comparison alone gives a false green here: `duckdb@1.4.4` clears the DuckLake 1.3.0 floor *and* loads the
extension — it is specifically `ATTACH` that crashes. US-3.1 Option A cannot be implemented until this lands.

**Current state (verified 2026-09-20)**
- `cube/package.json` pins `^0.35.0` for `@cubejs-backend/server`, `duckdb-driver`, `postgres-driver` and `server-core`. Latest for all four is **1.7.42**.
- **No lockfile exists** — the `^` caret means every build resolves a different dependency tree.
- `cube/Dockerfile` is `FROM cubejs/cube:latest`. `latest` currently resolves to **v1.7.42** (pushed 2026-09-18 in the same release as the `v1`/`v1.7`/`v1.7.42` tags). `CMD ["npm","run","start"]` runs `cubejs-server` from `/cube/conf/node_modules`, so **the container today is a 1.7.42 base image running a 0.35.x server** — and the base image moves under us on every rebuild.
- Local Node is **v22.14.0**.

**Breaking changes to handle**

| Change | Where it bites | Fix |
|---|---|---|
| `dbType` was **removed in v1.7.0** and now throws | `cube/cube.js:137` — `dbType: process.env.CUBEJS_DB_TYPE \|\| 'duckdb'` — immediate hard failure on boot | Delete the key. `driverFactory` must return a `DriverConfig` (`{ type: 'duckdb', … }`), or rely on `CUBEJS_DB_TYPE`, which `Dockerfile` already sets to `duckdb` |
| Node.js v20 **removed**, v22 **deprecated**, both in v1.7.0 | Runtime | Confirm the target Node against the 1.7.x base image; do not assume v22.14.0 stays supported |
| Floating base image + floating `^` ranges, no lockfile | Both layers non-reproducible | Pin `FROM cubejs/cube:v1.7.42`; pin exact versions; **commit `package-lock.json`** |

**Explicitly NOT breaking — do not scope work for these** (checked against `cube-js/cube` `DEPRECATION.md`)
- `checkSqlAuth` (`cube.js:147`), `contextToAppId` (`:176`) and `queryRewrite` (`:183`) all survive the upgrade unchanged.
- `SECURITY_CONTEXT` was deprecated in v0.33 in favour of `queryRewrite` — this repo already uses `queryRewrite`, so there is no work here.
- **camelCase JS models remain supported in v1.** The **13 cubes across 4 files** (`AnnuityQuotation.js` 118, `InvestmentAnalysis.js` 108, `MemberAnalysis.js` 70, `SharedDimensions.js` 213 — 509 lines total) do **not** need renaming. This is materially smaller than first estimated.

**Acceptance criteria**
- All four `@cubejs-backend/*` dependencies pinned to an exact 1.7.x version; `package-lock.json` committed.
- `Dockerfile` pins an immutable base tag (`cubejs/cube:v1.7.42`), not `latest`.
- `cube.js` boots with no `dbType` key and the driver type resolved through `driverFactory`'s `DriverConfig` or `CUBEJS_DB_TYPE`.
- The three existing dashboards pass a regression pass against the upgraded server — every cube in the allowlist still resolves, and `checkSqlAuth` still rejects an unverified caller (US-1.3).
- `INSTALL ducklake; LOAD ducklake; ATTACH 'ducklake:…'` completes without segfault against the upgraded driver, in the deployed container — the exit condition that unblocks US-3.1 step 3.

**Verification** — boot the container, run the three dashboards' queries, and run the ADR §3.2 smoke test (attach → load → reload → snapshot enumeration → `AT (VERSION => n)` time travel) against the container's own driver rather than a scratch rig.

**Sequencing** — behind US-2.1 (credential rotation remains the critical path), ahead of US-3.1's implementation. Treat as its own workstream with its own regression pass; ADR-0001 §4 step 1.

#### US-3.1 — Decide, with evidence
> **As a** Product Owner, **I want** a recorded decision on DuckLake, **so that** we stop paying for a
> component that does nothing.

**Acceptance criteria**
- An ADR (`data-recon/docs/adr/0001-ducklake-or-parquet.md`) records the choice with a cost line and a capability comparison covering: snapshot isolation, time travel, schema evolution, and concurrent-write safety during the monthly reload.
- **Option A — Adopt**: `ATTACH 'ducklake:postgres:…' AS lake` in `initSql`; tables registered in `ducklake_catalog`; Cube queries `lake.scbi_cdp_mart.<table>`; the migration script writes through DuckLake.
- **Option B — Retire**: drop `ducklake_catalog`; downsize the instance to the smallest tier Metabase tolerates; rename it away from `scbi-ducklake-catalog`; purge "DuckLake" from docs, naming and the telemetry cockpit, which currently reports it as live infrastructure.
- Whichever is chosen, `telemetry_engine.py`'s `cloud_sql.databases` output reflects reality.

**Recommendation** — Option A if the monthly reload will ever run while the portal serves traffic
(readers currently see a torn view mid-reload, since `read_parquet` has no snapshot isolation);
otherwise Option B. This is the single largest open decision in this PRD.

#### US-3.2 — Make the telemetry cockpit truthful
> **As an** Analyst, **I want** the SysAdmin panel to show real infrastructure state, **so that** I can
> trust it during an incident.

**Acceptance criteria**
- `_build_default_gcp_cache()`'s hardcoded revision names, CPU/memory limits and `total_mart_tables: 44` are replaced by live `gcloud`/Cloud Monitoring reads, or clearly labelled `STATIC — not live`.
- `cube_ping` remains live.
- No panel reports a component as `ACTIVE` without having contacted it.

---

### EPIC 4 — Semantic Layer Completeness  *(foundation for P2)*

#### US-4.1 — Generate lakehouse views from a manifest
> **As a** Data Engineer, **I want** every migrated table exposed to Cube automatically, **so that**
> the semantic layer is never silently short of source data.

**Acceptance criteria**
- `initSql` view DDL is generated by iterating `scripts/migration_state.json` (44 tables), not hand-written.
- Adding a table to the migration state and redeploying makes it queryable with no edit to `cube.js`.
- Startup logs the view count; a count below the manifest count fails the container.

#### US-4.2 — Fix the broken dimension bindings
> **As a** Data Engineer, **I want** every declared dimension to resolve to a real column, **so that**
> queries do not fail at runtime.

**Acceptance criteria**
- `DimMember.currentAge` → `member_age`. Add `memberStatus`, `memberRetirementAge`, `memberRetirementDate`, `memberDateOfBirth`.
- New cubes: `DimAggregator` (`aggregator_brokerage_name`, `aggregator_client_broker_consultant`), `DimRevisionAssociation` (`revision_association_name`, `_code`, `_grouping_code`), `DimRiskProduct` (`risk_product_derived_name`, `risk_product_component_description`, `risk_group_product_description`).
- A schema-conformance test executes `SELECT <every declared dimension> LIMIT 1` for every cube and fails on any unresolved column.

**Verification** — `tests/test_model_conformance.py`. This test fails on current `main` (`current_age`).

#### US-4.3 — Build the `FundAnalyticsMonthlyMetrics` cube
> **As a** Data Engineer, **I want** the consolidated member fact modelled in Cube, **so that**
> Dashboard 1 has a real source.

**Acceptance criteria**
- Cube over `cnf__agg_consolidated_member_measures_monthly` with the joins in §4.2.
- Measures: `totalAua`, `totalVestedAua`, `totalSavingsAua`, `totalRetirementAua`, `totalNonVestedAua`, `totalMemberContribution`, `totalEmployerContribution`, `totalAdminContribution`, `totalAvcContribution`, `totalGrossContribution`, `totalNetContribution`, `riskPremiumTotalBilled`, `riskBenefitCover`, `distinctMembers`, `activeMemberCount`.
- Measure names and semantics are reconciled one-for-one against the DAX measures in the PBI model (`Total_Aua`, `Distinct_Membership_Count`, `Active_Member_Count`, …). Divergences are documented, not silent.
- Dimensions expose all eight filter members from §4.3.

#### US-4.4 — Build the `MemberSegmentation` cube
> **As a** Data Engineer, **I want** member segmentation modelled, **so that** age, salary, retirement
> and contribution-rate visuals have a source.

**Acceptance criteria**
- Cube over `cnf__fact_member_segmentation` joined to `DimMember` on `member_hk` and `DimDate` on `date_sk`.
- Dimensions: `ageBandDescription`, `salaryBandDescription`, `termToRetirementBandDescription`, `yearsPastEarlyRetirementBandDescription`, `pensionableServiceYearsBandDescription`, plus raw `age`, `retirementAge`, `monthlySalary`, `termToRetirement`.
- Measures: `avgAge`, `avgMonthlySalary`, `avgGrossContributionRate`, `avgNetContributionRate`, `distinctMembers`.
- **Join-path decision recorded**: the PBI model marks `member_segmentation_nk` inactive. Document whether Cube joins via `member_segmentation_nk` or via `member_hk + date_sk`, and prove the chosen path does not fan out — a row-count test asserting `distinctMembers` is identical either way.

**Risk** — this is the highest-risk story in the PRD. A wrong join here silently inflates every
member count on the dashboard. It must not be marked `DONE` on a passing smoke test alone.

#### US-4.5 — Define or delete the remaining allowlisted cubes
> **As a** Data Engineer, **I want** the 8 named-but-missing cubes resolved, **so that** the
> Digital Operations role is not entitled to nothing.

**Acceptance criteria**
- `MemberTransactions`, `AssetflowsMemberMonthly`, `InFundExitMemberMonthly`, `DigitalPortal`, `DigitalPortalEvents`, `DigitalPortalRegistrations`, `AggregatedDigitalPortalRegistrations` are each either defined over their (already migrated) source table, or removed from `ROLE_PERMISSIONS` with a note.
- No role has an empty effective entitlement.

---

### EPIC 5 — Data-Driven Cascading Slicers  *(addresses G2)*

#### US-5.1 — Replace the slicer handler with Cube-derived options
> **As an** Analyst, **I want** dropdown values to reflect the data, **so that** I never select a
> combination that returns nothing.

**Acceptance criteria**
- `handle_cube_slicers()` contains no literal option arrays. `master_dates`, `master_umbrella_funds`, `master_standalone_funds`, `master_clients`, `master_employers` and the hardcoded brokerage / association / paypoint lists are deleted.
- Each slicer is resolved by the §5.2 algorithm.
- The `"All"` sentinel is added client-side.
- On a Cube error the endpoint returns `5xx` with a message. It never returns a stale or invented list.
- The shared alias across member/investment/annuity slicer routes is removed; each dashboard resolves against its own fact.

**Verification** — `tests/test_slicers_live.py`: for each slicer, assert every returned option yields ≥ 1 row when applied; assert a value absent from the lakehouse never appears.

#### US-5.2 — Bidirectional narrowing
> **As an** Analyst, **I want** every slicer to constrain every other, **so that** the filter panel is
> internally consistent.

**Acceptance criteria**
- For each of the 56 ordered pairs `(a, b)`, selecting a value in `a` returns `options(b)` that is a subset of unfiltered `options(b)`.
- For each `⇒ determines` / `strong` cell in §5.3, the narrowing is strict (proper subset) for at least one real value.
- Selecting a Fund sets Business Unit to that fund's `fund_classification`.
- A slicer's own options are computed excluding its own selection (rule 3, §5.1).

**Verification** — `tests/test_cascade_matrix.py`, parameterised over the 56 pairs using values drawn live from the lakehouse — not from a fixture list.

#### US-5.3 — Invalid-selection recovery
> **As an** Analyst, **I want** stale selections handled gracefully, **so that** the dashboard never
> goes blank or errors.

**Acceptance criteria**
- If a selection is absent from its recomputed options, the server returns the reset in an `adjusted_filters` block.
- `app.js` applies the reset and shows a non-blocking toast naming the slicer.
- No `500` is ever produced by a legal-but-empty filter combination; an empty result set renders as a zero-state, and the KPI cards read `0` / `R 0.00`, not a fabricated floor.
- The `max(10, …)` and `max(1000000.0, …)` floors are deleted.

#### US-5.4 — Request hygiene
> **As an** Analyst, **I want** rapid slicer changes to settle correctly, **so that** I see the result
> of my last action.

**Acceptance criteria**
- Slicer changes are debounced (250 ms) and in-flight requests aborted via the existing `AbortController`.
- Firing 5 changes within 200 ms produces exactly one rendered result, matching the final state.
- Aborted requests are not recorded as errors in telemetry.

---

### EPIC 6 — Dashboard 1 De-fabrication  *(addresses P2)*

#### US-6.0 — Stop asserting "live" *(ship first, ahead of everything else)*
> **As a** Product Owner, **I want** the portal to stop claiming fabricated data is live, **so that**
> no decision is taken on it while the rebuild runs.

**Acceptance criteria**
- `"live_feed": true` and `"cube_status": "scbi-cube Cloud Run Active (Linked)"` are removed from the synthetic path.
- Dashboard 1 renders a visible `DEMO DATA — NOT FROM SOURCE` banner until US-6.1…6.4 land.
- Merged within one working day of PRD approval.

#### US-6.1 — Headline KPI cards from Cube
> **As an** Analyst, **I want** the demographic and financial headline cards computed from the
> lakehouse, **so that** I can rely on them.

**Acceptance criteria**
- `handle_member_analysis_query()` calls `query_cube()`. `base_total`, `base_male`, `base_female`, `base_total_aua` and the entire `scale` cascade are deleted.
- Total / Male / Female member counts come from `FundAnalyticsMonthlyMetrics.distinctMembers` grouped by `DimMember.memberGender`.
- `Total = Male + Female` holds **only if the data says so.** If a third gender value or nulls exist, the UI shows an `Unspecified` column. The test asserts `sum(by gender) == total`, not `male + female == total`.
- Average age from `MemberSegmentation.avgAge`; average monthly salary from `MemberSegmentation.avgMonthlySalary`.
- `avg_aua = total_aua / distinct_members` computed from Cube values.
- All 8 filters applied as Cube filters.

**Verification** — `tests/test_member_recon.py`: ground truth computed by an independent DuckDB query over the same Parquet, for ≥ 10 filter combinations. Tolerance: exact for counts, < 0.01% for currency.

#### US-6.2 — Pages 1–3 from Cube
> **As an** Analyst, **I want** the age, retirement and salary visuals to reflect my filters.

**Acceptance criteria**
- Age band histogram: `distinctMembers` by `MemberSegmentation.ageBandDescription`. Bands come from the data; the seven hardcoded `age_dist` percentages are deleted.
- Retirement proximity: by `termToRetirementBandDescription` and `yearsPastEarlyRetirementBandDescription`, split by gender.
- Age × Salary matrix: `ageBandDescription` × `salaryBandDescription`.
- `sum(bins) == total_members` is asserted as a *property of the query result*, not guaranteed by a rounding-absorber. The `values.append(total_members - cum)` trick is deleted.

#### US-6.3 — Page 4 Contributions from Cube
**Acceptance criteria**
- Gross/net contribution rates by age band and salary band from `MemberSegmentation.avgGrossContributionRate` / `avgNetContributionRate`, or from `totalGrossContribution / totalMonthlySalary` — whichever matches the PBI DAX. Document which.
- The hardcoded rate arrays (`[12.5, 13.8, …]`) are deleted.

#### US-6.4 — Page 5 Products & Risk from Cube
**Acceptance criteria**
- Product-group AUA from `FundAnalyticsMonthlyMetrics.totalAua` by `DimInvestmentProduct` / `DimAdminProduct` grouping. The fixed 45/30/15/10 split is deleted.
- Top risk products by `DimRiskProduct.riskProductDerivedName`, measured by `distinctMembers` or `riskBenefitCover` per the PBI report. Split by gender.
- "Top 10" is a real `order by … limit 10`, not a fixed list of five.

#### US-6.5 — Filter state persists across tabs
**Acceptance criteria**
- Switching between the five sub-tabs re-queries with unchanged filter state.
- `distinctMembers` under identical filters is identical on all five tabs.
- Tab switch does not reset any slicer.

#### US-6.6 — Remove silent fallbacks everywhere
> **As an** Analyst, **I want** failures to look like failures, **so that** I never read a constant as
> a measurement.

**Acceptance criteria**
- The `except Exception: total_mv = 152182905749.29` style fallbacks in `handle_investment_analysis_query()` are removed; errors propagate as `5xx` and the card renders an error state.
- No handler returns a numeric literal in a response body.
- Every response carries `data_source: "cube"` and the `queryId`/timing actually observed.

---

### EPIC 7 — A Test Suite That Can Fail  *(addresses G6)*

#### US-7.1 — Independent ground truth
> **As a** Data Engineer, **I want** recon tests to compare against a separately computed answer,
> **so that** a bug in the server cannot make its own test pass.

**Acceptance criteria**
- A fixture opens DuckDB against the same Parquet and computes expected values with hand-written SQL.
- Tautological assertions (`total == male + female` where the server constructs it so) are replaced by comparisons to that ground truth.
- `CASCADING_FILTERS_TEST_REPORT.md` is regenerated and its provenance stated; the current 19/19 report is marked superseded and explained.

#### US-7.2 — Mutation check
**Acceptance criteria**
- A CI job perturbs one Cube measure (e.g. `totalAua` → `sum * 1.01`) and asserts the recon suite **fails**.
- A suite that passes under mutation fails the build.

#### US-7.3 — Browser verification
**Acceptance criteria**
- Headless run asserts: 8 `<select>` elements populated from the API, loading overlay appears and clears, zero console exceptions, selected state round-trips.
- p95 slicer < 800 ms, query < 2500 ms over 20 iterations, measured — not asserted from a telemetry field the server sets itself.

#### US-7.4 — CI gate
**Acceptance criteria**
- Pipeline runs: secret sweep (US-2.2), model conformance (US-4.2), no-literals check (§3 invariant), recon suite, mutation check.
- The no-literals check greps handler bodies for numeric literals outside pagination/timeout constants and fails on a hit.
- Merges are blocked on failure.

---

### EPIC 8 — Deployment & Consolidation

#### US-8.1 — Deploy the thin app
> **As a** Platform Engineer, **I want** the portal deployed like the rest of the stack, **so that** it
> is not a laptop-only artefact.

**Acceptance criteria**
- `thin-web-app/Dockerfile` exists; the app is deployed as Cloud Run `scbi-thin-web` behind IAP (US-1.1).
- `CUBEJS_BASE_URL` and secrets come from the environment; the hardcoded Cloud Run URL default is removed.
- `python http.server` is replaced by a production WSGI/ASGI server — the current handler is single-threaded and will serialise every concurrent user.

#### US-8.2 — Retire `data-recon/web/`
> **As a** Data Engineer, **I want** one front end, **so that** logic cannot diverge between two
> copies of `app.js`.

**Acceptance criteria**
- Any capability in `web/` but missing from `thin-web-app/` (e.g. `/api/catalog`, `/api/roles`) is ported.
- `web/` is archived and deleted, removing the last embedded-DuckDB + hardcoded-HMAC path.
- `MIGRATION_PLAN.md` is updated to state which principles were met and when.

#### US-8.3 — Serve Metabase and Power BI over the Cube SQL API

**Status** — **DONE (code)** 2026-09-20. Proven by `tests/test_us_8_3_sql_api_runtime.py` (33).
The deploy itself is owed by the user — EXECUTION_PLAN.md §6.

> **As a** BI Analyst, **I want** Metabase and Power BI to query the semantic layer directly, **so
> that** every tool sees the same metrics, role boundaries and PII masking as the portal.

Added 2026-09-20 on the user's direction. The PRD's serving layer stopped at the thin web app;
the architecture is **GCS → ducklake (GCSQL) → CubeJS → clients (Metabase, Power BI, thin web
client)**, and Metabase had no story at all.

**Acceptance criteria**
- Cube's SQL API is enabled on the variable Cube actually reads, `CUBEJS_PG_SQL_PORT`. The inert
  `CUBEJS`+`_SQL_PORT` appears in no artefact, and a misconfiguration fails the container at
  startup rather than leaving it silently unbound.
- The SQL API runs on a runtime that can carry the Postgres wire protocol. Cloud Run cannot: it
  routes one port and speaks HTTP/1, HTTP/2, gRPC and WebSockets only.
- Each BI client connects with its own credential, one per role domain, scrypt-digested in
  `CUBEJS_SQL_USERS`. No shared login, and no connection holding `ROLE_EXECUTIVE_ALL`.
- Port 5432 is never reachable from `0.0.0.0/0`. Metabase reaches it over VPC egress; an analyst
  reaches it over an IAP tunnel.
- Every Cube deploy supplies both `CUBEJS_DB_DUCKDB_S3_*` halves, which `cube.js` `requireEnv`s.
- No provisioning script, in any language, carries a password default.

**Verification** — `tests/test_us_8_3_sql_api_runtime.py` (33): a Node harness loads the real
`cube.js` and asserts each incoherent SQL configuration throws at module load and each coherent
one does not; per-role `checkSqlAuth` and `queryRewrite` assertions; and sweeps over the deploy
artefacts for the inert variable, an internet-open port, a missing HMAC pair, an executive
connection and password literals.

**Operator guide** — `docs/METABASE_CUBE_SQL.md`.

---

## 7. Milestones

| Milestone | Stories | Exit criterion |
|---|---|---|
| **M0 — Stop the bleeding** (day 1) | US-6.0, US-2.1 | No "live" claim on fabricated data; every exposed credential rotated |
| **M1 — Trust boundary** | US-1.1 → 1.4, US-2.2, US-2.3 | No endpoint accepts a client-asserted role; no secret in the tree |
| **M2 — Semantic foundation** | US-4.1 → 4.5 | Model conformance suite green; `FundAnalyticsMonthlyMetrics` and `MemberSegmentation` queryable |
| **M3 — Cascading filters** | US-5.1 → 5.4 | Zero hardcoded option arrays; 56-pair cascade matrix green |
| **M4 — Dashboard 1 real** | US-6.1 → 6.6 | Every Dashboard 1 number traced to a Cube query; demo banner removed |
| **M5 — Proof** | US-7.1 → 7.4 | Recon suite fails under mutation; CI gate enforced |
| **M6 — Consolidate** | US-3.0, US-3.1, US-3.2, US-8.1, US-8.2 | Cube on a supported major with a lockfile; catalog decision recorded and executed; one deployed front end |

M0 and M1 do not depend on M2–M4 and should run in parallel with them.

> **Execution order is tracked in `data-recon/docs/EXECUTION_PLAN.md`**, which is the authority on sequence and per-story status. It deviates from this table in three places, deliberately and with reasons recorded: EPIC 3 moves to phase 2 (ADR-0001 made the Cube upgrade a hard prerequisite, not a consolidation task), US-4.1 moves next to US-3.1 (the ADR satisfies it in the same change), and US-7.1/US-7.3 move ahead of EPICs 5–6 (so the dashboard rewrites are provable rather than self-certified). This table remains the milestone framing; the plan is the running order.

---

## 8. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| `MemberSegmentation` join fans out and inflates member counts | High — silently wrong dashboard | US-4.4 row-count equivalence test; reconcile against PBI published totals before release |
| Real numbers differ visibly from the fabricated ones users have already seen | Medium — credibility | Communicate before M4 ships; keep the demo banner until recon is signed off |
| Full-scan `read_parquet` latency breaches the 800 ms slicer SLA | Medium | Measure in M2; if breached, add Cube pre-aggregations for the 8 slicer dimensions — this is the intended lever, not caching fabricated values |
| Brokerage via `DimAggregator` is not what the business means by "brokerage" | Medium — wrong filter semantics | Confirm with the report owner before US-4.3; `aggregator_client_broker_consultant` is the alternative |
| IAP rollout blocks existing users | Low | Stage on a preview revision; verify the group mapping before cutover |
| Monthly reload tears reads mid-flight | Medium | Resolved by US-3.1 Option A; if Option B, schedule reloads in a maintenance window |

---

## 9. Open Decisions

1. ~~**DuckLake: adopt or retire?** (US-3.1)~~ — **RESOLVED 2026-09-20: adopt (Option A)**, recorded in `data-recon/docs/adr/0001-ducklake-or-parquet.md`. The reload does overlap live traffic, which was the deciding condition. Carries a Cube 0.35.x → 1.7.x major upgrade as a hard prerequisite — scoped as US-3.0.
2. **Brokerage semantics** — `DimAggregator.aggregator_brokerage_name` (the only member-domain path) vs. `aggregator_client_broker_consultant`. Needs the report owner.
3. **Identity source** — Google Groups vs. a `role_assignments` table. Groups are simpler; a table is auditable in-app.
4. **Segmentation join path** — `member_segmentation_nk` (PBI's inactive relationship) vs. `member_hk + date_sk`.
5. **Gender values** — does the source carry values beyond M/F, or nulls? Determines whether the UI needs an `Unspecified` column (US-6.1).
6. **Do Dashboards 2 and 3 get the same recon treatment?** Currently out of scope; they query Cube but their slicers share the hardcoded handler, so US-5.1 touches them regardless.

---

## 10. Appendix — Source Inventory

- **Lakehouse**: 44 tables, all `COMPLETED` 2026-09-17 (`scripts/migration_state.json`). Every table this PRD requires is already present, including `CNF__AGG_CONSOLIDATED_MEMBER_MEASURES_MONTHLY`, `CNF__FACT_MEMBER_SEGMENTATION`, `CNF__DIM_AGGREGATOR`, `CNF__DIM_REVISION_ASSOCIATION`, `CNF__DIM_RISK_PRODUCT`. **No new data migration is required.**
- **Cube views currently defined**: 12 of 44.
- **Authoritative lineage for Dashboard 1**: `pbi-scbi/semantic_models/use-case/FundAnalyticsMonthlyMetrics`.
- **dbt contracts**: `dbt-scbi-cnf/models/marts/common/*.yml`.
