# Serving Metabase and Power BI over the Cube SQL API

**US-8.3.** How BI clients reach the semantic layer, why there is more than one connection, and
what to do when a connection is refused.

Audience: whoever operates the deployment. This is not an end-user guide — an analyst needs
§6 and nothing else.

---

## 1. The shape of it

```
GCS (parquet)  →  ducklake  →  Cube.js  →  clients
```

Cube.js is the only thing that reads the lakehouse. Every client goes through it, so the role
boundaries and the PII masking in `cube/model/cubes/SharedDimensions.js` apply once, in one
place, instead of being re-implemented per tool.

Cube exposes two APIs, and they run on **two different runtimes** because one platform cannot
carry both:

| | Protocol | Runtime | Deployed by | Consumers |
|---|---|---|---|---|
| REST / GraphQL | HTTPS on 4000 | Cloud Run `scbi-cube` | `cube/deploy_cube_rest_cloudrun.sh` | the thin web app |
| SQL API | Postgres wire on 5432 | Compute Engine `scbi-cube-sql` | `cube/deploy_cube_sql_vm.sh` | Metabase, Power BI, Excel, Tableau |

Both run the **same image**. `deploy_cube_sql_vm.sh` resolves it from the live Cloud Run service
rather than rebuilding, so there is exactly one `cube.js` and one set of role definitions.

### Why the SQL API is not on Cloud Run

Cloud Run routes a single container port and speaks HTTP/1, HTTP/2, gRPC and WebSockets. The
Postgres wire protocol is none of those. No revision, no port, no configuration makes it work —
this is a platform boundary, not a setting anyone forgot.

GKE would work and was rejected for now: an Autopilot control plane plus an internal TCP load
balancer costs more than the instance, and IAP TCP forwarding — the thing that lets an analyst
on a laptop reach 5432 with nothing exposed to the internet — does not reach a GKE Service.
Revisit when there is more than one consumer per role domain.

---

## 2. One connection per role domain

**This is the part that is easy to get wrong, and getting it wrong is silent.**

Cube derives the security context from the SQL login. A connection *is* a role. So a single
shared `scbi_user` login would give every dashboard, and everyone who can open one, the same
role — and whichever role that is becomes the effective permission of the whole BI estate.

Instead, mint one connection per role domain:

```bash
node cube/mint_sql_users.js
```

That prints each connection's plaintext password **once** (paste it into the BI tool, then
discard the output) followed by the `CUBEJS_SQL_USERS` value, which holds scrypt digests only.
Passwords are generated inside the script and are never an argument, so they do not reach shell
history or the process table.

The default set:

| Connection | Role | Can reach | PII |
|---|---|---|---|
| `metabase.member@sanlam.co.za` | `ROLE_FINANCE_MEMBER` | MemberMonthly, MemberMonthlyInvestment, DimMember | masked |
| `metabase.investments@sanlam.co.za` | `ROLE_INVESTMENTS` | InvestmentsFundamental, MemberMonthlyInvestment | masked |
| `metabase.quotations@sanlam.co.za` | `ROLE_ANNUITY` | AnnuityQuotation | masked |
| `powerbi.member@sanlam.co.za` | `ROLE_FINANCE_MEMBER` | as above | masked |
| `powerbi.investments@sanlam.co.za` | `ROLE_INVESTMENTS` | as above | masked |

Every role may also join the shared dimension cubes (no measures, no PII).

### There is deliberately no executive connection

`ROLE_EXECUTIVE_ALL` is the only role with `canViewPii: true`. A BI connection holding it would
unmask `member_nk` and the rest on every dashboard that touches `DimMember`, for every person who
can open that dashboard — which is not the same set of people who were granted the role.

This is enforced, not just written down:

- `cube/deploy_cube_sql_vm.sh` refuses to deploy a store that grants it.
- `test_no_deploy_artefact_wires_a_bi_client_to_the_executive_role` sweeps every deploy artefact.
- `cube.js` throws at module load if `CUBEJS_SQL_SUPER_USER` is set, because a super user can
  `SET user` into any role in the store and no `canSwitchSqlUser` policy exists here to stop it.

If an executive connection is genuinely wanted, that is a POPIA decision — made once, in writing,
and minted by hand.

---

## 3. Metabase setup

### 3.1 Give Metabase a route

Metabase runs on Cloud Run; `scbi-cube-sql` has no external address. Without VPC egress Metabase
has no route to a private address at all, and the connection fails at the TCP layer **before any
credential is checked** — which in the Metabase UI looks exactly like a wrong password.

`metabase/deploy_metabase.sh` now passes `--network`, `--subnet` and
`--vpc-egress=private-ranges-only`. Redeploy Metabase once after deploying the SQL runtime.

### 3.2 Add one database per role domain

In Metabase: **Admin → Databases → Add database**, once per connection from §2.

| Field | Value |
|---|---|
| Database type | PostgreSQL |
| Display name | `DuckLake — Member & Finance` (name it after the domain, not the tool) |
| Host | the instance's internal IP, printed by `deploy_cube_sql_vm.sh` |
| Port | `5432` |
| Database name | `cube` |
| Username | `metabase.member@sanlam.co.za` |
| Password | the plaintext minted in §2 |
| Use a secure connection (SSL) | off — the hop is inside the VPC |

Repeat for `investments` and `quotations`. Three databases, three role boundaries.

### 3.3 Scope Metabase's own groups to match

Cube enforces the role at the connection. Metabase decides *who gets to use that connection*, and
the two have to agree or the boundary is only half drawn. Create one Metabase group per domain and
grant each group data access to its own database only:

**Admin → Permissions → Databases**, set every other group to *No self-service* for that database.

A person who should see two domains belongs to two groups. Do not solve it by widening a role.

---

## 4. Power BI setup

Power BI Desktop connects to `localhost:5432` through an IAP tunnel (§6) — there is no endpoint
to point it at directly, and no Cloud Run URL that will work.

1. Open the tunnel and leave it running.
2. **Get Data → PostgreSQL database**, server `localhost:5432`, database `cube`.
3. Choose **DirectQuery**.
4. Sign in with the `powerbi.*` connection for the analyst's domain.

Existing `.pbip` models switch over without DAX rewrites — the Cube schema matches the Snowflake
model schema. See `docs/PBI_TO_DUCKLAKE_REPLICA_GUIDE.md` §7.

---

## 5. Deploying the SQL runtime

```bash
export CUBEJS_API_SECRET=...                     # >= 32 bytes
export CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID=...     # GCS HMAC pair
export CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY=...
export CUBEJS_SQL_USERS='<the JSON line from mint_sql_users.js>'

./cube/deploy_cube_sql_vm.sh
```

What it creates, all idempotent:

- **Instance** `scbi-cube-sql`, `e2-standard-2`, zone `europe-west1-b`, Container-Optimized OS,
  **no external address**, network tag `scbi-cube-sql`.
- **Firewall** `allow-scbi-cube-sql`: `tcp:5432` from the regional subnet range (Metabase) and
  `35.235.240.0/20` (IAP) only. Never `0.0.0.0/0` — a test asserts it.
- **Private Google Access** on the subnet, if it was off. A `--no-address` instance has no route
  to Artifact Registry without it, so it boots and then fails to pull the image, and only the
  serial console says so.

It does **not** attach Cloud SQL. `cube.js` never reads `DUCKLAKE_CATALOG_*`; `initSql` reads
parquet straight from GCS with the HMAC pair.

### Known gaps, stated rather than hidden

- Secrets are container env values, not Secret Manager references. Anyone who can
  `gcloud compute instances describe scbi-cube-sql` can read `CUBEJS_API_SECRET`, the HMAC pair
  and every digest. That is US-2.2 criteria 1 and 3, blocked on enabling
  `secretmanager.googleapis.com`.
- The legacy `default-allow-internal` rule already permits `tcp:0-65535` from `10.128.0.0/9` to
  every untagged instance in the network, so `allow-scbi-cube-sql` is the only *scoped* path to
  5432, not the only path. Narrowing that rule is a network-wide change.
- Single instance, single zone. No HA. Acceptable at one consumer per domain; revisit with GKE
  when that stops being true.

---

## 6. Reaching it from a laptop

```bash
gcloud compute start-iap-tunnel scbi-cube-sql 5432 \
    --local-host-port=localhost:5432 \
    --zone=europe-west1-b --project=myanalyticsproduct
```

Leave it running while the BI tool is connected. The analyst needs
`roles/iap.tunnelResourceAccessor` and `roles/compute.viewer`.

Nothing is exposed to the internet by this: IAP authenticates against IAM before a packet reaches
the instance, and revoking the role closes the path immediately — which is not true of a password.

---

## 7. When a connection is refused

The failure modes here are unusually quiet, so diagnose in this order.

**Connection refused / timeout — nothing in the Cube log.** Nothing is listening. Cube reads the
wire-protocol port from `CUBEJS_PG_SQL_PORT`. The variable `CUBEJS` + `_SQL_PORT` is *not* a Cube
variable; it was in `cube/Dockerfile` and in the replica guide until 2026-09-20, it binds nothing
and it logs nothing, so the symptom is identical to a firewall problem. `cube.js` now throws at
startup on that combination rather than coming up deaf. Check:

```bash
gcloud compute instances describe scbi-cube-sql --zone=europe-west1-b \
    --format='value(metadata.items.filter("key:gce-container-declaration").extract("value"))'
```

**Connection refused from Metabase only.** Metabase has no VPC egress — §3.1.

**Container not running at all.** Almost always a module-load throw. `cube.js` has five of them:
`assertAllowlistsResolve()`, three `requireEnv` calls, `assertApiSecretIsUsable()`,
`parseSqlUsers()` and `assertSqlApiIsCoherent()`. Each names what is wrong and why:

```bash
gcloud compute ssh scbi-cube-sql --zone=europe-west1-b --tunnel-through-iap \
    --command='sudo docker logs $(sudo docker ps -aq --latest)'
```

**Authentication failed.** The password is checked with scrypt against the digest in
`CUBEJS_SQL_USERS`. An unknown username costs the same work as a known one, deliberately, so the
store cannot be probed by timing — "authentication failed" does not tell you which half was wrong.
Re-mint (§2) and redeploy; there is no way to recover a password from a digest.

**Connects, but a cube is missing.** That is the role boundary working. `queryRewrite` restricts
each login to its role's `allowedCubes` — see the table in §2. The answer is the right connection
for that domain, not a wider role.

---

## 8. Rotation

Re-running `mint_sql_users.js` mints new passwords and takes every existing connection down until
Metabase and Power BI are updated. Rotate deliberately, one domain at a time if the dashboards are
in use:

```bash
node cube/mint_sql_users.js quotations     # just this domain
```

Then merge that entry into the existing `CUBEJS_SQL_USERS` value, redeploy, and update the one
Metabase database that uses it.
