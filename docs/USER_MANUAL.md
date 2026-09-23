# SC BI Recon Platform — User Manual

**Status: outline plus one finished chapter.** Created 2026-09-20 so that the access procedure is
not lost between the session that worked it out and the session that writes the manual.

**Audience:** whoever operates and uses the platform — the system owner, a second operator when
there is one, and the analysts given a role. It is *not* a build document. Where a chapter is
still a stub it names the source it will be written from, so nobody has to rediscover where the
answer lives.

Everything else under `docs/` is written for a builder. This file is the only one written for a
reader who simply has to run the thing.

---

## Contents

| # | Chapter | State |
|---|---|---|
| 1 | [Who this platform is for](#1-who-this-platform-is-for) | stub |
| 2 | [Getting in](#2-getting-in) | stub |
| 3 | [**Administering access — adding and removing people**](#3-administering-access) | **written** |
| 4 | [The dashboards](#4-the-dashboards) | stub |
| 5 | [Metabase](#5-metabase) | stub |
| 6 | [Power BI against Cube SQL](#6-power-bi-against-cube-sql) | stub |
| 7 | [When something is wrong](#7-when-something-is-wrong) | stub |

---

## 1. Who this platform is for

*Stub.* Write from `thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md` §1 and the architecture the
system owner restated on 2026-09-20: **GCS → DuckLake (Cloud SQL Postgres catalog) → Cube →
clients (Metabase, Power BI, the thin web app)**.

Must state plainly, because a reader will otherwise assume otherwise: **Dashboard 1's numbers are
demonstration data until US-6.6 is green.** The in-app banner says so; the manual must not
contradict it.

## 2. Getting in

*Stub.* Write once `scbi-thin-web` is deployed (US-8.1 / `07_deploy_thin_web.sh`) — there is no URL
to document yet. Covers: the Google sign-in that IAP puts in front of the app, what "you are not
authorised" looks like, and who to ask.

---

## 3. Administering access

This chapter is complete and is the reference procedure. The deeper rationale — why a JSON roster
rather than Google Groups, and the rules the JSON cannot state about itself — is
[`thin-web-app/ROLE_ASSIGNMENTS.md`](../thin-web-app/ROLE_ASSIGNMENTS.md). The runbook these
scripts belong to is [`scripts/blocked/README.md`](../scripts/blocked/README.md).

### 3.1 The two things a person is given

Independent, and both set in the same entry.

* A **data role** — what they *see*. Exactly one. `ROLE_EXECUTIVE_ALL` is the only role that sees
  an unmasked member; every other role gets PII masked, and `ROLE_FINANCE_MEMBER` is the fallback.
* One or more **access groups** — what they *reach*. `portal`, `metabase`, `sql_analyst`, or
  `sys_admin`, which implies all three plus the Cube REST API.

Someone can be `sys_admin` on `ROLE_ANNUITY`: full reach, one cube. That is a normal combination
for an operator who should not see member data.

Print the definitions rather than trusting this paragraph — the command reads them from the code:

```bash
python scripts/access/manage_access.py roles          # what each role and group grants
```

### 3.2 Adding someone

Run from the `data-recon` directory, in Git Bash.

```bash
python scripts/access/manage_access.py roles          # what each role and group grants
python scripts/access/manage_access.py add ops@sanlam.co.za \
    --role=ROLE_FINANCE_MEMBER --group=sys_admin --note="on call"
./scripts/blocked/09_apply_access.sh --dry-run        # then without it — changes IAM
./scripts/blocked/07_deploy_thin_web.sh               # roster is baked into the image
```

**The last two steps are not interchangeable, and both are needed.**

| Step | Takes effect | Covers |
|---|---|---|
| `09_apply_access.sh` | immediately | `groups` — what they may *reach*. IAM bindings. |
| `07_deploy_thin_web.sh` | on the next revision | `role`, `can_view_pii` — what they may *see*. The roster is baked into the container image, so nothing changes until the app is redeployed. |

Run `09` with `--dry-run` first, every time. It prints the IAM it would change, and it reports
drift — anyone bound in IAM whom the roster does not justify.

For the checks without the deploy:

```bash
python scripts/access/manage_access.py check          # validate the roster
(cd thin-web-app && python -m pytest -q)              # the suite guards the same rules
```

### 3.3 Variations

```bash
# an analyst who only needs the portal
python scripts/access/manage_access.py add anna.smith@sanlam.co.za \
    --role=ROLE_INVESTMENTS --group=portal --note="US-4.3 report owner"

# give an existing person Power BI against Cube SQL as well
python scripts/access/manage_access.py group anna.smith@sanlam.co.za --add=sql_analyst

# change what someone sees, without touching what they reach
python scripts/access/manage_access.py set-role anna.smith@sanlam.co.za --role=ROLE_ANNUITY

python scripts/access/manage_access.py list           # the whole roster
python scripts/access/manage_access.py show anna.smith@sanlam.co.za
```

### 3.4 Removing someone

```bash
python scripts/access/manage_access.py remove anna.smith@sanlam.co.za
./scripts/blocked/09_apply_access.sh --prune          # revokes what the roster no longer justifies
./scripts/blocked/07_deploy_thin_web.sh
```

`--prune` is the step that actually removes access; without it the entry is gone from the roster
but the IAM binding stays. It only ever removes `user:` principals — a service account, group or
domain binding was put there by something else — and it refuses to remove the account running it.

Between the `remove` and the `07`, a removed person who still has `portal` in IAM resolves to
`ROLE_FINANCE_MEMBER` with PII masked. Least privilege, not nothing. If the intent is *out*, the
prune is the step that does it.

### 3.5 Four things that surprise people

1. **A typo in the role name is a silent demotion, not an error.** The app falls back to
   `ROLE_FINANCE_MEMBER` and says nothing, anywhere. `manage_access.py` is the guard against that;
   hand-editing the JSON removes the guard.
2. **`can_view_pii: true` grants nothing outside the executive role.** Cube decides, and it masks
   PII for the other four roles whatever the roster says.
3. **No service account may hold `ROLE_EXECUTIVE_ALL`.** A shared BI connection holding it defeats
   every mask for everyone using that connection. The test suite sweeps for it.
4. **`test.user@sanlam.co.za` must never be mapped.** The test suite mints its assertions as that
   address and asserts it falls back to least privilege.

### 3.6 What access does *not* include

* **A Metabase account.** The `metabase` group opens the Metabase login page. The account behind
  it is Metabase's own user admin.
* **A SQL credential.** `sql_analyst` opens an IAP tunnel to port 5432. The login is still checked
  against Cube's own SQL user store — see [`docs/METABASE_CUBE_SQL.md`](METABASE_CUBE_SQL.md) and
  `scripts/blocked/02b_remint_sql_users.sh`.

## 4. The dashboards

*Stub.* Blocked on Phase 6 (US-6.1 … US-6.6) — writing it now would document fabricated numbers.
Write from the PRD's EPIC 6 once the demo banner comes down.

## 5. Metabase

*Stub.* Source: [`docs/METABASE_CUBE_SQL.md`](METABASE_CUBE_SQL.md), which is written for the
operator who provisions it. The manual chapter is the shorter half: how to connect, what each role
domain can query, and why one connection per role domain is deliberate.

## 6. Power BI against Cube SQL

*Stub.* Sources: [`docs/METABASE_CUBE_SQL.md`](METABASE_CUBE_SQL.md) and
[`docs/PBI_TO_DUCKLAKE_REPLICA_GUIDE.md`](PBI_TO_DUCKLAKE_REPLICA_GUIDE.md). Must cover opening the
IAP tunnel, because there is no public address and the connection fails confusingly without one.

## 7. When something is wrong

*Stub.* Three candidates already known, each worth a paragraph, from `scripts/blocked/README.md`:

* `CERTIFICATE_VERIFY_FAILED` on any tunnel or SSH call — Zscaler TLS interception, fixed once by
  `scripts/blocked/00_export_ca_bundle.ps1`. It reads as intermittent; it is deterministic per
  code path.
* A tunnel that fails with a not-found — usually the missing `compute.viewer` half of
  `sql_analyst`, not a missing VM.
* A SQL login rejected on a tunnel that works — the credential, not the network.

---

## Before this manual is published

Two conditions, both currently unmet:

1. **`scbi-thin-web` must exist.** Chapters 2 and 4 have no subject until it is deployed.
2. **The demo banner must be down**, or chapter 4 must say in its first line that the numbers are
   demonstration data.

And the standing caveat: nothing in `scripts/blocked/` has been executed against the live project.
Chapter 3's commands are `bash -n` clean and were exercised against a stub `gcloud`; they have not
been run for real.
