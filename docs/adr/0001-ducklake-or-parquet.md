# ADR 0001 — Adopt DuckLake as the lakehouse catalog, or retire it

| | |
|---|---|
| **Status** | **Accepted (Option A — Adopt).** P1 resolved 2026-09-20: DuckLake is viable, but **requires a Cube major upgrade (0.35.x → 1.7.x) first** — see §3.1 |
| **Date** | 2026-09-20 |
| **Deciders** | Product Owner, Data Engineering, Platform Engineering |
| **Story** | US-3.1 (`PRD_ARCHITECTURE_REALIGNMENT.md`, EPIC 3) |
| **Supersedes** | Nothing |
| **Affects** | `cube/cube.js`, `scripts/migrate_cube_data_to_parquet.py`, `web/telemetry_engine.py`, Cloud SQL `scbi-ducklake-catalog`, GCS `gs://scbi-ducklake-myanalyticsproduct` |

---

## 1. Context

The platform is named for DuckLake throughout — the GCS bucket is
`scbi-ducklake-myanalyticsproduct`, the Cloud SQL instance is `scbi-ducklake-catalog`
with a `ducklake_catalog` database, and there are scripts called
`register_ducklake_views.sql` and `pbi_to_ducklake_transpiler.py`.

**None of it is DuckLake.** Verified 2026-09-20:

- A repository-wide search for `ATTACH` across every `.py`, `.js`, `.sql`, `.sh` and
  `.ps1` under `data-recon/` returns **zero hits**. No DuckLake catalog is ever attached.
- `cube/cube.js` `initSql` (lines 85–140) creates hand-written DuckDB views over
  `read_parquet('s3://<bucket>/<schema>/<table>/*.parquet')`.
- The `ducklake_catalog` database is provisioned and billing. Its only live consumer is
  Metabase's `metabase_appdb` sharing the same instance.

What exists is a **Parquet-on-GCS lake read through glob patterns**, wearing a DuckLake
label. There is no catalog, no snapshot isolation, no ACID, no time travel, and no
schema evolution.

### 1.1 The deciding question, now answered

The open question was whether the monthly reload ever overlaps with the portal serving
traffic. **The Product Owner confirmed on 2026-09-20 that it does.** That makes the
concurrency behaviour of the current design a correctness defect, not a theoretical one.

### 1.2 What the reload actually does

`scripts/migrate_cube_data_to_parquet.py` (`migrate_table_end_to_end`) runs per table:

1. `REMOVE @~/parquet_migration/<table>/` — clears the **Snowflake** stage
2. `COPY INTO '<stage>' ... OVERWRITE = TRUE` — unloads fresh Parquet
3. `GET <stage> file://<local>` — downloads to a local temp directory
4. `gcloud storage cp --recursive "<local>" "gs://<bucket>/<schema>/"` — uploads to GCS
5. verify, then delete the local copy

Two consequences follow, and the second is more serious than the PRD recorded:

**(a) Torn reads.** Step 4 is a non-atomic multi-object upload into the same prefix the
Cube views glob. A query landing mid-upload sees a partial file set — some tables new,
some old, some half-present. Every number on the portal is wrong for the duration of the
reload, with no error raised.

**(b) Stale-file double counting.** There is **no GCS prefix cleanup anywhere** in the
tree — a search for `storage rm`, `storage delete` and `gsutil rm` across `scripts/`
returns nothing. `gcloud storage cp` overwrites objects *by name* but never deletes
objects the new unload did not produce. Snowflake `COPY INTO` chunks output by data
volume, so the file count and names vary between months. **If a reload emits fewer or
differently-named files than the previous one, the prior month's Parquet files survive in
the prefix and the `*.parquet` glob reads both generations as one table.** That is silent
double counting which persists indefinitely after the reload finishes — not merely for
its duration.

Defect (b) alone justifies changing the design. It is currently unguarded and undetected.

---

## 2. Options considered

### Option A — Adopt DuckLake

`ATTACH 'ducklake:postgres:...' AS lake` in `initSql`; register the 44 migrated tables in
`ducklake_catalog`; Cube queries `lake.scbi_cdp_mart.<table>`; the migration script writes
through DuckLake rather than uploading loose Parquet.

### Option B — Retire DuckLake

Drop `ducklake_catalog`; downsize the instance to the smallest tier Metabase tolerates;
rename it away from `scbi-ducklake-catalog`; purge "DuckLake" from docs, naming and the
telemetry cockpit. Mitigate the reload problem with a blue/green prefix swap
(write to `<table>_next/`, then repoint the view) and a mandatory prefix cleanup step.

### 2.1 Capability comparison

| Capability | Option A — DuckLake | Option B — Parquet globs (+ blue/green) |
|---|---|---|
| **Snapshot isolation** | Yes. Readers pin a catalog snapshot; a concurrent write is invisible until committed. | No, natively. Approximated by an atomic view repoint — a reader mid-query still spans the swap. |
| **Concurrent-write safety during reload** | Yes. Writes land in a new snapshot; readers continue on the old one until commit. | Partial. The swap is one DDL statement, but multi-table consistency needs all 44 views repointed together, which is not atomic. |
| **Stale-file double counting** | Structurally impossible — the catalog lists the files in a snapshot; unlisted files are ignored. | Must be prevented by an explicit cleanup step that does not currently exist. A missed cleanup silently corrupts totals. |
| **Time travel** | Yes. Query any prior snapshot; reproduce a month-end after the fact. | No. Requires manually retained dated prefixes and storage to match. |
| **Schema evolution** | Yes. Add/drop/rename columns tracked in the catalog. | No. A column change makes older Parquet files unreadable by a view expecting the new shape; `SELECT *` silently changes meaning. |
| **Multi-table reload consistency** | Yes — one commit across all 44 tables. | No. 44 independent swaps; a failure halfway leaves a mixed-generation lake. |
| **Operational complexity** | Higher. A Postgres catalog is now on the critical read path. | Lower. No catalog dependency; a bucket and a glob. |
| **Extra cost vs. today** | None — the instance is already provisioned and billing. | Saves the difference between the current tier and Metabase's minimum. |

### 2.2 Cost line

The instance is `db-custom-2-7680` (2 vCPU, 7.5 GB) with 50 GB SSD, zonal, in
`europe-west1`, per `scripts/provision_gcp_infra.sh:33-37`.

At list price that is approximately **USD 105–115 per month** (≈ USD 60 vCPU + ≈ USD 38
memory + ≈ USD 9 SSD). **This is an estimate from published rates, not a billing read —
confirm against the billing console before quoting it externally.**

- **Option A** adds **no new cost**. It puts a component already being paid for to work.
- **Option B** saves only the delta down to Metabase's minimum viable tier — realistically
  on the order of USD 50–70 per month — and spends engineering time building a blue/green
  swap and cleanup that DuckLake provides for free.

**The cost argument does not favour retirement.** The instance is sunk either way for
Metabase; the only saving is a partial downsize.

---

## 3. Decision

**Adopt DuckLake (Option A).**

The reload overlaps live traffic, which is exactly the condition the PRD named as
decisive. Option B would require building snapshot isolation, atomic multi-table commit
and stale-file cleanup by hand, and would still not deliver time travel or schema
evolution. DuckLake provides all four as properties of the format, on infrastructure
already provisioned and already paid for.

The hand-rolled alternative is strictly more work for strictly less correctness.

### 3.1 Precondition P1 — RESOLVED 2026-09-20: viable, but gated on a Cube major upgrade

**DuckLake requires DuckDB >= 1.3.0.** This was verified empirically rather than assumed. Result:
**DuckLake works, but not on the DuckDB bindings the pinned Cube version uses.**

| Check | Result |
|---|---|
| `@cubejs-backend/duckdb-driver@^0.35.0` resolves to | `0.35.81`, which depends on `duckdb: ^1.0.0` |
| `duckdb@^1.0.0` resolves to | `1.4.4` (engine reports `v1.4.4`) — clears the 1.3.0 floor |
| `INSTALL ducklake; LOAD ducklake;` on `duckdb@1.4.4` | **OK** — extension installs and loads |
| `ATTACH 'ducklake:...' AS lake (DATA_PATH ...)` on `duckdb@1.4.4` | **SEGFAULT** (exit 139), reproducible |
| Same `ATTACH` on `@duckdb/node-api@1.5.5-r.5` (engine `v1.5.5`) | **OK** |
| Full lifecycle on `@duckdb/node-api` — attach, create, load, delete+reload, snapshots, time travel | **All OK** (see §3.2) |
| `@cubejs-backend/duckdb-driver@latest` (`1.7.42`) depends on | **`@duckdb/node-api: 1.5.5-r.5`** — exactly the stack proven to work |

**The blocker is the legacy `duckdb` npm package, not DuckLake.** Cube 0.35.x binds to the old
node bindings, where the `ATTACH` that this entire decision rests on crashes the process. Cube
1.7.x binds to `@duckdb/node-api`, where it works.

Note the `^1.0.0` caret with **no lockfile** means the current container resolves whatever `duckdb`
1.x is latest at build time — builds are not reproducible today, independent of this decision. A
lockfile should be committed regardless of the outcome here.

**Consequence for scope:** adopting DuckLake now carries a **Cube 0.35.x → 1.7.x major upgrade** as
a hard prerequisite. That is a significant, breaking-change migration across `cube.js`, the driver
config, and 13 cubes across 4 model files — larger than the DuckLake work itself. It does not change the
decision, because Option B does not avoid it (the same stale-file and isolation defects remain, and
Cube 0.35.x is in any case long unmaintained), but it must be planned and resourced as its own
workstream ahead of step 3.

### 3.2 Evidence — functional smoke test

Run against `@duckdb/node-api@1.5.5-r.5`, simulating a monthly reload against a live reader:

```
engine: v1.5.5
attach / create table / insert   -> OK
  after load 1                   -> 300.00
delete + reinsert ("reload")     -> OK
  after reload                   -> 450.00
snapshots                        -> 0,1,2,3,4
time travel: SELECT ... AT (VERSION => 2)
  @v2 (pre-reload)               -> 300.00   <- prior state recovered while current reads 450.00
```

This demonstrates the two properties the decision turns on: the pre-reload state remains readable
at a pinned snapshot after the reload has committed, and snapshots are enumerable for auditing.

## 4. Implementation outline

Ordered; each step independently verifiable.

1. **Upgrade Cube 0.35.x → 1.7.x** (`@cubejs-backend/server`, `duckdb-driver`, `postgres-driver`,
   `server-core` are all at `1.7.42`). Commit a lockfile. Treat as its own workstream with its own
   regression pass over the existing 3 dashboards — P1 proved DuckLake cannot work before this.
   **Scoped 2026-09-20 as US-3.0** in `data-recon/thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md`
   (EPIC 3), which carries the full breaking-change inventory. Note the container is already
   inconsistent: `cube/Dockerfile` is `FROM cubejs/cube:latest`, and `latest` resolves to **v1.7.42**
   (pushed 2026-09-18), so a 1.7.42 base image today runs a 0.35.x `cubejs-server` out of
   `/cube/conf/node_modules`. Both layers must be pinned.
2. **Create the catalog schema.** `ducklake_admin` on `ducklake_catalog`, with the
   rotated password from US-2.1 — not the provisioning default.
3. **Attach in `initSql`.** Replace the 44 hand-written `read_parquet` views with
   `ATTACH 'ducklake:postgres:dbname=ducklake_catalog host=...' AS lake (DATA_PATH 's3://<bucket>/');`
   Connection string from Secret Manager, no in-code fallback (US-2.2 invariant).
4. **Register the 44 tables** into `lake.scbi_cdp_mart` / `lake.scbi_sdp_mart`, driven by
   `scripts/migration_state.json` — not hand-written. This satisfies US-4.1's manifest
   requirement in the same change.
5. **Repoint the model.** Cube `sql_table` references become `lake.<schema>.<table>`.
6. **Rewrite the reload to write through DuckLake** — `COPY ... TO lake.<schema>.<table>`
   in a transaction, so all 44 tables commit as one snapshot. Delete the
   `gcloud storage cp` path.
7. **Prove isolation.** Run a reload while issuing continuous portal queries; assert every
   response is internally consistent and no response mixes generations.
8. **Reconcile stale files.** Audit the bucket for orphaned Parquet from prior reloads
   before the first DuckLake registration — defect (b) may already have corrupted current
   totals. Compare row counts against Snowflake per table.
9. **Make telemetry truthful** (US-3.2, below).

### 4.1 Telemetry correction — a defect found while writing this ADR

`web/telemetry_engine.py:217-229` hardcodes the Cloud SQL instance as tier
`db-custom-1-3840`, 1 vCPU, 3.75 GB. The provisioning script creates
**`db-custom-2-7680` — 2 vCPU, 7.68 GB**. The cockpit under-reports the instance by half
and has never contacted it. Whatever the outcome here, that block must read live or be
labelled `STATIC — not live`.

---

## 5. Consequences

**Positive**

- Torn reads and stale-file double counting are eliminated structurally, not by discipline.
- Month-end figures become reproducible via time travel — directly useful for the
  reconciliation suite (EPIC 6), which can pin a snapshot instead of racing the reload.
- Schema evolution stops being a silent-corruption risk.
- The billed Cloud SQL instance earns its cost.
- US-4.1's manifest-driven view generation is satisfied by step 4 rather than separately.

**Negative**

- The Postgres catalog joins the critical read path. If `scbi-ducklake-catalog` is down,
  the portal cannot serve — today a Cloud SQL outage would leave it running. Zonal
  availability is now a portal availability risk; revisit `--availability-type=regional`.
- The migration script needs real rework, not a flag.
- DuckLake is a young format; the team takes on a dependency with a shorter track record
  than plain Parquet.
- **A Cube major upgrade (0.35.x → 1.7.x) is now in scope as a hard prerequisite**, and is likely
  larger than the DuckLake work itself. Option B would defer but not avoid it.

**Neutral**

- Naming becomes accurate for the first time. No rename needed under Option A — the
  bucket, instance and scripts finally describe what they are.

---

## 6. Verification log

| Date | Check | Result |
|---|---|---|
| 2026-09-20 | `ATTACH` present in tree | **No** — zero hits, confirming P1 of the PRD |
| 2026-09-20 | GCS prefix cleanup present | **No** — stale-file double counting is unguarded |
| 2026-09-20 | Reload overlaps live traffic | **Yes** — confirmed by Product Owner |
| 2026-09-20 | Cloud SQL tier, actual vs. reported | `db-custom-2-7680` provisioned vs. `db-custom-1-3840` reported |
| _TBD_ | **P1 — DuckDB version ≥ 1.3.0** | _not yet verified; no lockfile, no `node_modules/`_ |
| _TBD_ | P1 — `ducklake` extension loads | _not yet verified_ |

---

## 7. References

- `data-recon/thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md` — EPIC 3, US-3.1 / US-3.2
- `data-recon/cube/cube.js:85-140` — current `read_parquet` view definitions
- `data-recon/scripts/migrate_cube_data_to_parquet.py:491-585` — reload path
- `data-recon/scripts/provision_gcp_infra.sh:29-45` — instance and catalog provisioning
- `data-recon/scripts/migration_state.json` — the 44-table manifest
- `data-recon/web/telemetry_engine.py:217-229` — hardcoded infrastructure claims
