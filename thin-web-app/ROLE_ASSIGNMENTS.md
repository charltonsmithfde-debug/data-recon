# `role_assignments.json` — who gets what

The one file that answers both halves of "who is this person": what they may **see**, and what
they may **reach**. Keyed by the email IAP verifies. US-1.2's answer to "Google Groups or a
table": a table, because it is auditable in-app and reviewable in a diff.

It shipped empty until **2026-09-20**, when the system owner was mapped. See
[The current roster](#the-current-roster).

## Schema

```json
{
  "someone@sanlam.co.za": {
    "role": "ROLE_INVESTMENTS",
    "can_view_pii": false,
    "groups": ["portal", "metabase"],
    "note": "why they have this"
  }
}
```

| Field | Read by | Meaning |
|---|---|---|
| *key* | both | The email as IAP asserts it. Never a header the caller can write. |
| `role` | `server.py` | One of `KNOWN_ROLES`. **An unrecognised role is not an error — it is a silent demotion to `ROLE_FINANCE_MEMBER`.** |
| `can_view_pii` | `server.py` | Absent or non-bool reads as `false`. Means nothing outside the executive role: `cube.js` sets `canViewPii: false` for every other role and `cube.js` wins. |
| `groups` | `09_apply_access.sh` | What GCP access to grant. Ignored by `server.py`. |
| `note` | humans | Ignored by everything. Write why, not what. |

`server.py` reads only `role` and `can_view_pii`
([server.py:103-111](server.py#L103-L111), [server.py:179-196](server.py#L179-L196)); override the
path with `SCBI_ROLE_ASSIGNMENTS`. Because both consumers read the same file, "who may open
Metabase" cannot drift from "who is in the portal" the way a roster plus a separate IAM list
would.

## The two vocabularies

**Data roles — what a person sees.** Exactly one each. Defined in
[`cube/cube.js`](../cube/cube.js) `ROLE_PERMISSIONS`; this file only points at one.

| Role | Cubes | PII |
|---|---|---|
| `ROLE_EXECUTIVE_ALL` | `*` | **in the clear** — the only role that sees an unmasked member |
| `ROLE_FINANCE_MEMBER` | member measures and flows | masked *(the fallback)* |
| `ROLE_DIGITAL_OPERATIONS` | none yet — US-4.5 | masked |
| `ROLE_INVESTMENTS` | products, market values | masked |
| `ROLE_ANNUITY` | annuity quotations | masked |

**Access groups — what a person reaches.** Any number each. Turned into IAM bindings by
[`scripts/blocked/09_apply_access.sh`](../scripts/blocked/09_apply_access.sh).

| Group | Grants | On |
|---|---|---|
| `portal` | `roles/iap.httpsResourceAccessor` | `scbi-thin-web` |
| `metabase` | `roles/run.invoker` | `scbi-metabase` |
| `sql_analyst` | `roles/iap.tunnelResourceAccessor` + `roles/compute.viewer` | project (tunnel to `scbi-cube-sql:5432`) |
| `sys_admin` | **all of the above**, plus `roles/run.invoker` on `scbi-cube` | — |

`sys_admin` implies the other three plus the derived `cube_rest`. That is the point of it: one
word in the JSON means Metabase *and* the Cube REST API *and* the tunnel, rather than three
bindings somebody has to remember to tick.

A role and a group are independent. Someone can be `sys_admin` on `ROLE_ANNUITY` — full reach,
one cube — and that is a normal, useful combination for an operator who should not see member
data.

## The current roster

| Person | Role | PII | Groups |
|---|---|---|---|
| `charltonsmithfde@gmail.com` | `ROLE_EXECUTIVE_ALL` | in the clear | `sys_admin` |

The system owner, mapped on 2026-09-20 as the answer to the three authorisation questions that
were blocking the runbook. One person holding everything is correct for a system with one
operator; it stops being correct the moment a second person needs part of it, and the point of
`groups` is that they can then be given exactly that part.

## Adding someone

The same procedure, written for a reader rather than a builder, is
[`docs/USER_MANUAL.md` §3](../docs/USER_MANUAL.md#3-administering-access). Keep the two in
step: this file carries the reasoning, the manual carries the steps.

Use the tool. Hand-editing works, but three of the rules are invisible in the JSON.

```bash
# see what the roles and groups actually grant
python scripts/access/manage_access.py roles

# an analyst who only needs the portal
python scripts/access/manage_access.py add anna.smith@sanlam.co.za \
    --role=ROLE_INVESTMENTS --group=portal --note="US-4.3 report owner"

# a second sys-admin: Metabase, scbi-cube, the tunnel and the portal, in one word
python scripts/access/manage_access.py add ops@sanlam.co.za \
    --role=ROLE_FINANCE_MEMBER --group=sys_admin --note="on call for the recon platform"

# someone who needs Power BI against Cube SQL as well
python scripts/access/manage_access.py group anna.smith@sanlam.co.za --add=sql_analyst

python scripts/access/manage_access.py check          # validate
(cd thin-web-app && python -m pytest -q)              # the suite guards the same rules
./scripts/blocked/09_apply_access.sh --dry-run        # show the IAM it would change
./scripts/blocked/09_apply_access.sh                  # grant it
./scripts/blocked/07_deploy_thin_web.sh               # ship the roster into the image
```

Both last two steps matter and they do different things. **`09` changes IAM immediately.
`role` and `can_view_pii` change nothing until `07` redeploys**, because the roster is baked
into the container image.

## Removing someone

```bash
python scripts/access/manage_access.py remove anna.smith@sanlam.co.za
./scripts/blocked/09_apply_access.sh --prune          # revokes what the roster no longer justifies
./scripts/blocked/07_deploy_thin_web.sh
```

`--prune` only ever removes `user:` principals, because `09` only ever adds `user:` principals —
a `serviceAccount`, `group`, `domain` or `allUsers` binding was put there by something else and
is not `09`'s to take away. It also refuses to remove the account running it.

Until `07` runs, a removed person who still has `portal` in IAM resolves to
`ROLE_FINANCE_MEMBER` with PII masked. Least privilege, not nothing — if the intent is *out*,
the prune is the step that does it.

## What none of this grants

* **A Metabase account.** `metabase` opens the Metabase login page. The account behind it is
  Metabase's own user admin.
* **A SQL credential.** `sql_analyst` opens a tunnel to 5432. The login is still checked against
  `CUBEJS_SQL_USERS`, and the role that connection gets is fixed by which user it authenticates
  as — see [`02b_remint_sql_users.sh`](../scripts/blocked/02b_remint_sql_users.sh) and
  [`docs/METABASE_CUBE_SQL.md`](../docs/METABASE_CUBE_SQL.md).
* **Anything, if the service is still public.** `09` grants the real invokers; removing
  `allUsers` is [`05_lock_down_cloud_run.sh`](../scripts/blocked/05_lock_down_cloud_run.sh), once,
  in that order.

## The rules that are not visible in the file

Checked by `manage_access.py check`, by
`tests/test_us_8_3_sql_api_runtime.py::test_the_role_roster_validates`, and by
`99_verify.sh` before a deploy.

1. **A typo in `role` is a silent demotion**, not an error. `server.py:186-188` falls back to
   `ROLE_FINANCE_MEMBER` and says nothing, anywhere.
2. **`test.user@sanlam.co.za` must never be mapped.** `tests/conftest.py:40` mints the suite's
   IAP assertions as that address and the US-1.2 tests assert it falls back to least privilege.
3. **No non-human principal may hold `ROLE_EXECUTIVE_ALL`.** A person holding it is the intended
   use; a service account or shared BI credential holding it is the shared connection that
   defeats every mask in `SharedDimensions.js` for everyone using it. This file is the only
   artefact under `data-recon/` permitted to name that role at all — every other `.sh`, `.ps1`,
   `.json`, `.env` and `.yaml` is swept for it by
   `test_no_deploy_artefact_wires_a_bi_client_to_the_executive_role`.
4. **`can_view_pii: true` outside the executive role grants nothing.** `cube.js` decides, and it
   sets `canViewPii: false` for the other four. A `true` there only misleads the next reader.

Presence of the file proves nothing on its own, so `01_preflight.sh`, `07_deploy_thin_web.sh`
and `99_verify.sh` report how many people are mapped rather than that the file exists.
