# `scripts/blocked/` — the runbook a human has to run

Every script in this directory is a step the agent could not take itself. Each one is
outward-facing, reads a credential, takes a live service down, or is an authorisation decision
that belongs to a person rather than to a tool. They are written to be run **by a human, from
Git Bash, in order, from the `data-recon` directory**:

```bash
cd /c/Users/G988557/Documents/Code/github_DBT/data-recon
./scripts/blocked/01_preflight.sh
```

Nothing here has been executed. See [The caveat](#6-the-caveat) at the end.

---

## 1. First, the Zscaler prerequisite

Run this once, from **PowerShell**, before anything else:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\blocked\00_export_ca_bundle.ps1
```

It exports `LocalMachine\Root`, `LocalMachine\CA` and `CurrentUser\Root` to one PEM (roughly 190
certificates, about 330 KB) at `$HOME\.scbi-runbook\win-ca-bundle.pem`, and prints a `setx` line.
Run that line, then open a new shell so it takes effect.

**Why this is needed, and why the problem looked intermittent.** This workstation sits behind
Zscaler TLS interception. `gcloud` validates TLS against its own bundled CA store, which has no
Zscaler root; the Windows certificate store does. Calls that open an IAP tunnel or an SSH
session — `gcloud compute start-iap-tunnel`, `gcloud compute ssh --tunnel-through-iap` — fail
with

```
[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate
```

while ordinary API calls (`gcloud run services list`, and so on) succeed, because they take a
different code path. That split is exactly why this read as an intermittent network fault for
two sessions. It is not intermittent: it is deterministic, per code path.

The bundle holds only public certificates — no private keys, nothing secret. It is written
outside the repo anyway, because it is machine-specific and would be noise in a diff.

---

## 2. The order

| # | Script | Downtime | Reversible |
|---|---|---|---|
| 00 | `00_export_ca_bundle.ps1` | none | delete the file |
| 01 | `01_preflight.sh` | none — read-only | n/a |
| 02 | `02_diagnose_sql_login.sh` | none — read-only | n/a |
| 02b | `02b_remint_sql_users.sh` | **yes** — every BI connection | re-run with the old store |
| 03 | `03_enable_secret_manager.sh` | none | delete the secrets |
| 04 | `04_rotate_and_mount_secrets.sh` | **yes** — Cube and Metabase, 5–10 min | not a single command; see below |
| 05 | `05_lock_down_cloud_run.sh` | none if the invoker list is right | re-add the binding |
| 06 | `06_deactivate_old_hmac.sh` | none | `--rollback`, seconds |
| 07 | `07_deploy_thin_web.sh` | none — new service | delete the service |
| 08 | `08_grant_analyst_iap.sh` | none | `--revoke` |
| 09 | `09_apply_access.sh` | none | `--prune`, or re-run after editing the roster |
| 99 | `99_verify.sh` | none — read-only | n/a |

Only **02b** and **04** take anything down. Everything else is additive, read-only, or a
one-command reversal.

Every script that changes a live service takes `--dry-run` (echo the commands, run none of
them) and `--yes` (skip the prompt, for an unattended run). Without `--yes` you are asked to
type the literal word `proceed`; anything else aborts.

---

## 3. What each one is for

### `01_preflight.sh` — the state board

Read-only. Changes nothing, and is safe before and after anything else. Every line it prints is
measured, not assumed — which is the entire reason it exists. Three sessions in a row inherited
claims about GCP that had never been checked against the project.

### `02_diagnose_sql_login.sh` — one question left

`pg_probe.py` gets a real Postgres wire response from Cube for all five users and is rejected by
every one. That is progress, not a failure: it proves the tunnel, IAP, the host firewall, the
listener and `checkSqlAuth` are all alive and actively rejecting. **Everything network-level is
already solved.** One question is left, and this script answers it: does the plaintext in the
probe file match the digests actually deployed in the VM's `CUBEJS_SQL_USERS`?

The leading hypothesis is that the probe file came from a different `mint_sql_users.js` run than
the one whose digests reached the VM, so they were never going to match.

Nothing here prints a secret — `pull_store.py` emits fingerprints, `verify_creds.py` emits
booleans. That is also why the agent could not run it: every route to the answer reads
credential material, and the sandbox refuses that categorically.

### `02b_remint_sql_users.sh` — the fix, and the trap it avoids

Run this when 02 says the plaintext does not match the deployed digests, or when the plaintext
is simply gone.

**The trap.** `cube/deploy_cube_sql_vm.sh:51-54` requires four values from the environment and
defaults none of them: `CUBEJS_API_SECRET`, both halves of the GCS HMAC pair, and
`CUBEJS_SQL_USERS`. Three of those were only ever in a session transcript — and **a GCS HMAC
secret is shown once at creation and is never retrievable afterwards**. Re-running the deploy
blind therefore forces minting a fresh HMAC pair *and* a fresh API secret: rotating two live
credentials to fix a third, and breaking DuckDB's lakehouse reads on the way past.

**The way out.** The container runs with `--env-file /etc/cube-sql.env`
(`deploy_cube_sql_vm.sh:252`), and cloud-init wrote all four values into that file on the
instance. They are recoverable from the VM. So this script carries the other three across
untouched and rotates only the SQL user store.

**Why it goes through the deploy script rather than editing the live file.** Editing
`/etc/cube-sql.env` in place works until the next `gcloud compute instances reset`, at which
point cloud-init rewrites it from instance metadata and the change vanishes. The deploy script
rewrites that metadata, so the rotation survives a reset. It also installs the iptables
`ExecStartPre` (`deploy_cube_sql_vm.sh:251`) that keeps 5432 open across a reboot — COS is
default-DROP, and the rule on the live VM today was added by hand and is runtime-only.

**What it costs.** Every existing BI connection stops authenticating the moment the new store is
live. Metabase and Power BI must be updated with the passwords it prints. Nothing else rotates.

### `03_enable_secret_manager.sh` — the no-downtime half of US-2.2

Enables the API, creates four empty secrets, grants the runtime service account
`secretAccessor` per secret. **Nothing here touches a running service**, no value is written and
no deployment changes, so there is nothing to roll back beyond deleting the secrets.

Measured 2026-09-20: `secretmanager.googleapis.com` is `SERVICE_DISABLED` on this project, so
every credential the platform holds is today a plain `--set-env-vars` value, readable by anyone
with `gcloud run services describe` — `deploy_cube_rest_cloudrun.sh:71-73` says so in its own
closing output.

03 and 04 are separate on purpose: this half can be run now, in working hours, and reviewed
before the half that bites.

### `04_rotate_and_mount_secrets.sh` — the half that bites

**This takes services down.** Read the script's own header before running it.

Rotates `CUBEJS_API_SECRET` (48 bytes of urlsafe entropy) and the `ducklake_admin` and
`metabase_admin` Cloud SQL passwords. The GCS HMAC pair is **carried across, not re-minted** —
retiring the old pair is 06's job and a separate decision.

**The bug it also fixes.** `scbi-cube` has *neither* `CUBEJS_DB_DUCKDB_S3_*` variable today
(measured 2026-09-20), while `cube/cube.js:392-393` `requireEnv()`s both at module load. The
currently deployed revision predates that check. **Any redeploy of `scbi-cube` that does not set
them crash-loops the container** — so this script sets them, and a plain
`deploy_cube_rest_cloudrun.sh` run would not.

**Order, and why.** Secret Manager versions are added before any service is redeployed, and
Cloud SQL passwords are changed before the services that use them. A service redeployed against
a password that has not been changed yet comes up healthy and then fails on first query, which
is the worst of both.

**Rollback is not a single command.** Once the Cloud SQL passwords have changed, going back
means setting them back and redeploying again. Use `--dry-run` first, and run it in a window you
can afford to lose.

`--include-vm` also carries the new API secret to the SQL VM; it is optional and separate.

### `05_lock_down_cloud_run.sh` — off the public internet

Measured 2026-09-20: **both** `scbi-cube` *and* `scbi-metabase` have `allUsers` on
`roles/run.invoker`. Every note before that session pinned this on `scbi-cube` alone. Metabase is
the more serious of the two — it is a login UI sitting directly over the warehouse, so an
unauthenticated caller reaches a credential prompt backed by real data, rather than an API that
at least wants a signed token.

**The order is not negotiable.** Removing `allUsers` before granting the real invokers takes the
platform down for everyone, including the people who are meant to have access. The script grants
first and revokes second, and **refuses to revoke when the grant list is empty** — an empty list
plus a revoke is an outage with no way back in except another IAM change.

**It will break `data-recon/web/` — measured 2026-09-20, before running it.** The legacy app
sends only Cube's own JWT (`web/server.py:583-592`), and the telemetry cockpit sends nothing at
all (`web/telemetry_engine.py:166`). Neither obtains a Google ID token — `X-Serverless-
Authorization`, `id_token` and `fetch_id_token` return **zero hits** in both files. The two
`Authorization` headers are different credentials checked by different systems: Cube's JWT is
checked by Cube *after* the request arrives, `roles/run.invoker` by Cloud Run *before* it does.
`allUsers` is the only reason the legacy app reaches Cube today, and being bound as an invoker
does not help a process that never presents an identity.

`thin-web-app/server.py:247-259` does mint one and is unaffected. So 05 is correct and `web/` is
US-8.2's to retire — but the cockpit goes dark the minute 05 runs, with a 403 that never reaches
Cube and will not look like an auth problem in Cube's logs. If `web/` is still needed afterwards,
give it the same `X-Serverless-Authorization` header; do not re-add `allUsers`.

**Run 09 first.** 05 refuses to revoke against an empty grant list, and 09 is what makes the list
non-empty. As of 2026-09-20 the roster's one person holds `run.invoker` on both services.

There is deliberately no default invoker list. Guessing one here would either grant too much or
lock somebody out, so pass them explicitly:

```bash
./scripts/blocked/05_lock_down_cloud_run.sh --dry-run \
    --cube-invoker=serviceAccount:... \
    --metabase-invoker=user:someone@sanlam.co.za
```

### `06_deactivate_old_hmac.sh` — deactivate, never delete

Deactivation is reversible in seconds (`--rollback`). Deletion is final: the access id and its
secret are gone, and if anything unlisted was still using the pair there is no way back except
minting a new one and finding every consumer under an outage. **The security benefit is
identical** — a deactivated key authenticates nothing. A key that is deactivated and
demonstrably unused for a week can be deleted later, deliberately, by someone who no longer has
to guess. This is the argument recorded in `docs/adr/0002-outstanding-decisions.md`.

Measured 2026-09-20: nothing deployed reads the old pair. The only consumers are the local
reconciliation engines (`web/member_engine.py:25-26` and siblings), which read whatever is in
the analyst's user environment — so an analyst still on the old pair is exactly the case this
script must not silently break. It refuses if the key it is asked to deactivate is the only
`ACTIVE` one.

### `07_deploy_thin_web.sh` — the app, behind IAP

`scbi-thin-web` does not exist in Cloud Run (measured 2026-09-20). The app's 26-test
authentication gate therefore protects nothing today: it is all in the repository and none of it
is in front of a user.

**No `--allow-unauthenticated`, ever, on this service.** `server.py`'s entire authorisation model
reads the IAP assertion header and derives the caller's role from it (`server.py:67,169`). A
service with `allUsers` on `roles/run.invoker` receives requests with no assertion at all, so the
app would either refuse everything or fall through to its default role. It must be private from
its first revision; retrofitting privacy after a public deploy leaves a window in which the
dashboards were world-readable.

**The audience is not optional and not guessable.** `server.py:67` requires
`SCBI_IAP_AUDIENCE`, and IAP tokens are validated against it exactly. For a Cloud Run backend it
is `/projects/<PROJECT_NUMBER>/apps/<PROJECT_ID>`. A wrong audience does not fail at deploy
time — it fails on the first real request, with every caller rejected. Stage 4 prints what was
set, so it can be compared against the IAP console before anyone is told the app is live.

Order: deploy private → grant IAP's service agent → enable IAP → grant the users
`roles/iap.httpsResourceAccessor`. Nothing is reachable between steps 1 and 3, which is the
intended shape of a first deploy.

### `08_grant_analyst_iap.sh` — a route to 5432 that is not the internet

The SQL VM has no public address, and the firewall rule allows only IAP's fixed forwarding
range, `35.235.240.0/20` (`deploy_cube_sql_vm.sh:47-48`). An analyst's Power BI or Metabase
connection reaches the VM only by opening an IAP tunnel on their own machine, and IAP checks IAM
before a single packet arrives. The port is authenticated by Google before it is reachable,
rather than being protected by the password alone.

Two roles, both needed: `roles/iap.tunnelResourceAccessor` is the access itself;
`roles/compute.viewer` lets `gcloud` resolve the VM's name and zone before tunnelling — without
it the tunnel fails with a not-found that reads as though the VM were gone.

**It grants nothing inside the database.** A tunnel reaches the listener; the login is still
checked against `CUBEJS_SQL_USERS`, and the role that connection gets is fixed by which user it
authenticates as. Granting tunnel access to someone with no SQL credential gives them a port
that refuses them.

Both roles are project-scoped here. `tunnelResourceAccessor` can be narrowed to a single
instance with an IAM condition, and should be if the list grows beyond a handful of people — at
that point a Google group is the right principal, not a list of individuals.

### `09_apply_access.sh` — make the roster true in IAM

05 and 08 each ask "who?" and take the answer on the command line. That works once. It does not
survive a second person joining, because the answer then lives in two shell histories and the
IAM console's audit log rather than in anything reviewable.

09 reads `thin-web-app/role_assignments.json` — the same file `server.py` reads for what a
person may *see* — and turns its `groups` field into the bindings that decide what they may
*reach*:

| Group | Grants | On |
|---|---|---|
| `portal` | `roles/iap.httpsResourceAccessor` | `scbi-thin-web` |
| `metabase` | `roles/run.invoker` | `scbi-metabase` |
| `sql_analyst` | `roles/iap.tunnelResourceAccessor` + `roles/compute.viewer` | project — delegated to 08 |
| `sys_admin` | all of the above, plus `roles/run.invoker` on `scbi-cube` | — |

`server.py` ignores `groups`, so one file serves both consumers and they cannot drift apart.
The tunnel pair is delegated to 08 rather than reimplemented, so two scripts never hold an
opinion about the same two bindings.

It reports drift on every run — anyone bound in IAM whom the roster does not justify — and
removes it only under `--prune`, and then only `user:` principals, because `user:` principals
are the only thing it ever adds. A `serviceAccount`, `group`, `domain` or `allUsers` binding
was put there by something else. It also refuses to remove the account running it.

**It does not remove `allUsers`** — that is 05, once, in the grant-then-revoke order — and it
does not deploy. A change to `role` or `can_view_pii` reaches users only on the next 07, because
the roster is baked into the container image.

Add and remove people with `scripts/access/manage_access.py`, which enforces the rules the JSON
cannot state about itself; see `thin-web-app/ROLE_ASSIGNMENTS.md`.

### `99_verify.sh` — did the runbook land?

01 answers "what is the state?". This answers "did the runbook actually land?", which is a
different question: a step can run without error and still leave the platform short of the
criterion it was meant to meet. It checks that secrets are mounted by `secretKeyRef` rather than
pasted, that both HMAC halves are present on `scbi-cube`, that `allUsers` is gone from both
services, that at most one HMAC key is `ACTIVE`, that an anonymous GET does not return 200, and
that `role_assignments.json` validates, and that the executive role — the only one with PII in
the clear — is held by named people and by no service account.

Given a probe file it also runs a live cube query through a tunnel. **That last check is the
point:** `SELECT 1` never touches DuckDB or GCS, so it can pass while the lakehouse path is
broken. US-8.3 is not done until a real cube query runs.

---

## 4. Conventions

- **`lib/common.sh` is sourced, never executed.** It holds the project constants, the output
  helpers, `confirm`, `parse_common_flags` and `run`. Override any constant from the
  environment: `PROJECT_ID`, `REGION`, `ZONE`, `SQL_VM`, and so on.
- **State lives in `~/.scbi-runbook`** (`SCBI_RUNBOOK_STATE` to move it), created `0700`, files
  `0600`. The CA bundle, the probe credential file and rotation transcripts go there — never
  into the repo.
- **No secret ever reaches a command line.** That is what makes `run()`'s echo safe by
  construction, and it is why values are piped to `gcloud secrets versions add --data-file=-`
  rather than passed as arguments.
- **Nothing prints a secret.** Fingerprints, booleans and identifiers only. Access ids and
  usernames are identifiers, not secrets, and are printed freely.
- `tests/test_us_2_2_no_secrets.py` sweeps `.sh` and `.ps1` files in this directory, so no real
  credential value and no key-prefix literal may appear here, even in a comment or an example.
- **`--dry-run` does not skip `confirm()`** (found 2026-09-20, *not* fixed — see below). `run()`
  no-ops under `--dry-run`, so nothing executes, but the confirmation prompt still asks. In a
  script with several confirmations a `--dry-run` therefore stops at the **first** one and never
  shows the surfaces after it, and with no TTY the `read` gets EOF and the script aborts. Until
  it is changed, use **`--list`** on 09 (read-only by design, no prompts, shows every surface)
  and expect `--dry-run` on the others to need either a terminal or `--yes`.

  It was left alone deliberately: making `confirm()` a no-op under `--dry-run` is correct, but it
  edits a confirmation gate in a runbook whose whole safety story is that gate, so it is the
  user's change to approve rather than one to slip in while using the script.

- **`"${ARR[@]:-}"` is a trap under `set -u`** — it expands to one empty-string argument, not
  zero, which silently defeats an `[ ${#ARR[@]} -eq 0 ]` guard. Use `${ARR[@]+"${ARR[@]}"}`.
  Every occurrence in 04/05/06/08 was fixed; watch for it in anything new.

---

## 5. Who gets what — answered 2026-09-20

The three authorisation questions that blocked 05, 07 and 08 are answered, and the answer lives
in `thin-web-app/role_assignments.json` rather than in this paragraph:

| Person | Role | PII | Groups |
|---|---|---|---|
| `charltonsmithfde@gmail.com` | `ROLE_EXECUTIVE_ALL` | in the clear | `sys_admin` |

One system owner, holding every role and every access surface. That is correct for a platform
with one operator and stops being correct the moment a second person needs part of it — which
is what `groups` is for.

So the lists 05, 07 and 08 used to demand now come out of the roster:

```bash
# what the roster says each surface's principals are
python scripts/access/manage_access.py principals --group=metabase
python scripts/access/manage_access.py principals --group=cube_rest

# 05 still needs them on the command line — it is the one-time lockdown, and its
# grant-then-revoke order is what keeps the revoke from being an outage
./scripts/blocked/05_lock_down_cloud_run.sh --dry-run \
    --cube-invoker=serviceAccount:886154918734-compute@developer.gserviceaccount.com \
    $(python scripts/access/manage_access.py principals --group=cube_rest | sed 's/^/--cube-invoker=/') \
    $(python scripts/access/manage_access.py principals --group=metabase | sed 's/^/--metabase-invoker=/')

# 07's first deploy takes its portal list the same way
./scripts/blocked/07_deploy_thin_web.sh --dry-run \
    $(python scripts/access/manage_access.py principals --group=portal | sed 's/^/--user=/')

# everything afterwards — every join, every leave — is 09
./scripts/blocked/09_apply_access.sh --dry-run
```

Note the extra `--cube-invoker` for the compute service account: the thin web app's runtime
mints an ID token per request and is the *normal* caller of `scbi-cube`. A `sys_admin` in the
roster is granted it as well, to call the REST API by hand when something is wrong.

Add the next person with `scripts/access/manage_access.py add`, then re-run 09 — not by editing
a command line here. `thin-web-app/ROLE_ASSIGNMENTS.md` is the full procedure
`docs/USER_MANUAL.md` §3 is the same procedure as steps, for whoever ends up operating this.

---

## 6. The caveat

**None of these scripts has been executed.** They are `bash -n` clean and were written against
state measured on 2026-09-20 against the live project, with every referenced line checked in
source rather than assumed — but measured is not the same as run. Use `--dry-run` first on
anything that changes a live service, and run `01_preflight.sh` immediately before, so you are
acting on today's state rather than on this paragraph.
