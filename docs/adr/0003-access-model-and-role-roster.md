# ADR 0003 — One roster for what a person sees and what they reach

| | |
|---|---|
| **Status** | **Accepted.** The three authorisation questions are answered by the system owner; the model that holds the answer is decided here |
| **Date** | 2026-09-20 |
| **Deciders** | System owner (`charltonsmithfde@gmail.com`), Platform Engineering |
| **Story** | US-1.2, US-1.3, and the `scripts/blocked/` runbook |
| **Supersedes** | ADR-0002 §7 (D6, "create it empty") and ADR-0002 §8's *Still needing a human*, all three items |
| **Affects** | `thin-web-app/role_assignments.json`, `scripts/access/manage_access.py`, `scripts/blocked/05`, `07`, `08`, `09`, `99`, `tests/test_us_8_3_sql_api_runtime.py` |

---

## 1. Context

ADR-0002 §7 created `role_assignments.json` empty, on the grounds that *who* gets which role is
a decision about real people and an invented mapping would be an access grant nobody authorised.
That left three questions open, and after the runbook was finished they were the **only** thing
blocking it:

1. Who invokes `scbi-cube`, and who may open Metabase? — `05_lock_down_cloud_run.sh`
2. Which analysts get an IAP tunnel to 5432? — `08_grant_analyst_iap.sh`
3. Who gets which role in `role_assignments.json`? — the file existed; the mapping did not.

The system owner has answered them. That answer is recorded in §2. The rest of this ADR is about
the shape the answer is stored in, which is the part with consequences beyond today.

---

## 2. The answer

| Person | Role | PII | Groups |
|---|---|---|---|
| `charltonsmithfde@gmail.com` | `ROLE_EXECUTIVE_ALL` | in the clear | `sys_admin` |

One system owner, holding every role and every access surface. Two observations, because both
matter later:

**It is correct now and will not stay correct.** A platform with one operator has nothing to
separate. The moment a second person needs part of it, this entry is exactly the wrong template
to copy — which is why the model below makes "part of it" expressible.

**"All roles" is one role, not five.** `cube.js:ROLE_PERMISSIONS` gives `ROLE_EXECUTIVE_ALL`
`allowedCubes: ['*']` and `canViewPii: true`; it is the superset, so a person holds one role and
that role reaches everything. There is no multi-role state to represent, and inventing one would
have added a concept the semantic layer does not have.

---

## 3. D1 — The roster answers both halves of identity

**Decision: `role_assignments.json` keeps a `groups` field alongside `role` and `can_view_pii`.
`server.py` ignores it; `09_apply_access.sh` reads it.**

Every person raises two questions, and they had two different homes:

| | Question | Was answered in | Read by |
|---|---|---|---|
| sees | which cubes, PII or masked | `role_assignments.json` | `server.py:179-196` |
| reaches | portal, Metabase, Cube REST, 5432 | a `--metabase-invoker=` on someone's command line | GCP IAM |

The second home is not a home. It is a shell history plus the IAM console's audit log, and it
has no reviewer, no diff and no answer to "why does this person have this". Keeping the two in
one file makes a join or a leave a change somebody can read.

**Rejected: a separate `access.json`.** It would need the same keys and would drift from the
roster on the first hurried change — a person removed from one and not the other is precisely
the failure this is meant to prevent.

**Rejected: Google Groups as the principal.** Right answer at a different size. It is where this
goes when the list outgrows a handful of people (`08_grant_analyst_iap.sh` already says so for
`tunnelResourceAccessor`), but a group is opaque in a diff, and with one person mapped the
indirection would cost more than it buys today.

The ignored-field trick is what makes one file safe: `server.py` reads `role` and
`can_view_pii` and nothing else, so `groups` cannot change what anybody sees, and a malformed
group cannot break the app.

## 4. D2 — `sys_admin` implies the rest

**Decision: four groups — `portal`, `metabase`, `sql_analyst`, `sys_admin` — and `sys_admin`
expands to all of them plus the derived `cube_rest`.**

| Group | Grants | On |
|---|---|---|
| `portal` | `roles/iap.httpsResourceAccessor` | `scbi-thin-web` |
| `metabase` | `roles/run.invoker` | `scbi-metabase` |
| `sql_analyst` | `roles/iap.tunnelResourceAccessor` + `roles/compute.viewer` | project |
| `sys_admin` | all of the above, plus `roles/run.invoker` on `scbi-cube` | — |

The implication is the point. "Sys-admin gets Metabase and `scbi-cube`" is then true by
construction rather than by three bindings somebody remembers to tick, and the three questions
in §1 collapse into one word in one file. `cube_rest` is derived rather than assignable because
calling the Cube REST API by hand is a sys-admin act; the service account that calls it *per
request* is the thin web app's runtime and is granted by 05, not from this roster.

**Role and group are independent.** `sys_admin` on `ROLE_ANNUITY` — full reach, one cube — is a
normal combination for an operator who should not see member data, and is the shape the second
person should probably take.

## 5. D3 — The executive-role sweep is sharpened, not blunted

**Decision: `role_assignments.json` is exempt from
`test_no_deploy_artefact_wires_a_bi_client_to_the_executive_role`, and two stricter tests cover
it instead.**

The sweep fails the suite on the executive role's literal name in any `.sh`, `.ps1`, `.json`,
`.env`, `.yaml` or `.yml` artefact under `data-recon/`. Last session it caught two of the
runbook's own scripts and **the scripts were reworded rather than the guard relaxed** — the
right call then, and the precedent that makes this decision worth stating.

This is a different case. The rule's subject is a **shared BI client connection**: one
credential, held by a tool, that unmasks every member for everyone who uses it. A roster entry
is the opposite — a single human whose identity IAP verified, which is exactly who
`cube.js:ROLE_PERMISSIONS` defines the role for. Read literally, the guard meant no person could
ever hold the role the cube defines for people.

So the check moved from *does this file name the role* to *who holds it, and is any of them
non-human*:

- `test_the_role_roster_grants_the_executive_role_only_to_named_people` — parses the roster,
  fails on any `.gserviceaccount.com` holder.
- `test_the_role_roster_validates` — runs `manage_access.py`'s validator, so a hand-edit that
  skips the tool is still caught before a deploy.
- `99_verify.sh` — the same two checks, before the deploy rather than in CI.

Verified by temporarily adding a `.gserviceaccount.com` entry with the executive role: both new
tests fail on it, with the shared-connection reasoning in the assertion message.

## 6. D4 — The rules live in a tool, because the file cannot state them

**Decision: `scripts/access/manage_access.py` is how people are added and removed. Hand-editing
still works and is still validated.**

Four rules are invisible in the JSON, and three of them fail *silently*:

1. **A typo in `role` is a demotion, not an error.** `server.py:186-188` falls back to
   `ROLE_FINANCE_MEMBER` and says nothing, anywhere. Someone loses access and the only symptom
   is a thinner dashboard.
2. **`test.user@sanlam.co.za` is reserved.** `tests/conftest.py:40` mints the suite's IAP
   assertions as that address; mapping it turns the US-1.2 least-privilege tests red.
3. **`can_view_pii: true` outside the executive role grants nothing.** `cube.js` decides and
   sets it false for the other four. A `true` there only misleads the next reader.
4. **No non-human principal may hold the executive role** — D3.

A validator that only runs in CI would catch these after the commit. The tool catches them at
the moment of the decision, which is when the person making it still has the context to fix it.

---

## 7. Consequences

### What is unblocked

| | Was gated on | Now |
|---|---|---|
| `05_lock_down_cloud_run.sh` | an invoker list it refuses to guess | `manage_access.py principals --group=…` produces both lists |
| `07_deploy_thin_web.sh` | who may open the portal | `--group=portal`, same shape |
| `08_grant_analyst_iap.sh` | which analysts tunnel to 5432 | `--group=sql_analyst`, or 09 delegates to it |
| every later join and leave | nothing — it had no process | `manage_access.py` + `09_apply_access.sh` |

### Cost of reversal

- **D1** — near none. `groups` is additive and ignored by the app; deleting the field leaves a
  roster that behaves exactly as ADR-0002 §7 left it.
- **D2** — none while the roster is one person. Splitting `sys_admin` later is an edit to one
  table in `manage_access.py` plus a re-run of 09.
- **D3** — this is the one with a real cost if wrong. The exemption is a hole in a guard, and
  the two tests replacing it are only as good as their definition of "not a person"
  (`.gserviceaccount.com`). A shared *human* mailbox mapped to the executive role would pass
  all three checks and is exactly the abuse the original rule existed to stop. **Review who
  holds that role whenever the roster changes** — 99_verify prints the list for that reason.
- **D4** — none. The tool is optional by construction; the validator behind it is not.

### Still needing a human

Nothing, for access. What remains open is unrelated and already recorded: ADR-0002's D2
(brokerage) and the second half of D5 (recon scope for Dashboards 2–3).

### Explicitly out of scope

- **A Metabase account.** `metabase` opens the login page; the account behind it is Metabase's
  own user admin.
- **A SQL credential.** `sql_analyst` opens a tunnel; the login is still checked against
  `CUBEJS_SQL_USERS` (`02b_remint_sql_users.sh`), and the role that connection gets is fixed by
  which user it authenticates as.
- **Removing `allUsers`.** That is 05, once, grant-then-revoke. 09 deliberately does not touch
  it and warns when it sees it.

---

## 8. Verification log

| Claim | How checked | Result |
|---|---|---|
| `ROLE_EXECUTIVE_ALL` is the superset role | `cube/cube.js:28-33` — `allowedCubes: ['*']`, `canViewPii: true` | Confirmed |
| `server.py` reads only `role` and `can_view_pii` | `thin-web-app/server.py:103-111,179-196` | Confirmed; `groups` and `note` are inert |
| An unknown role is a silent demotion | `thin-web-app/server.py:186-188` | Confirmed; no log, no error |
| `test.user@sanlam.co.za` must stay unmapped | `tests/conftest.py:40,226-233` | Confirmed |
| The sweep covers `.json` under `data-recon/` | `tests/test_us_8_3_sql_api_runtime.py:420-430` | Confirmed |
| The new tests catch a non-human executive holder | Temporarily added a `.gserviceaccount.com` entry | Both failed as intended; roster restored |
| 09 reconciles all four surfaces | `--dry-run` against a stub `gcloud`: grant, `--prune`, `--list`, self-prune refusal, `allUsers` and `serviceAccount` guards | Confirmed |
| The suite is green | `python -m pytest -q` in `thin-web-app/` | 168 passed, exit 0 |
| Every runbook script parses | `bash -n scripts/blocked/*.sh` | Clean |

**Not verified: anything against the live project.** 09 has never been run with a real `gcloud`,
and no IAM binding in `myanalyticsproduct` has been created or changed.

---

## 9. References

- `thin-web-app/ROLE_ASSIGNMENTS.md` — the schema, the procedure, the four invisible rules
- `scripts/blocked/README.md` §5 — the runbook's copy of the answer and the derived command lines
- `docs/adr/0002-outstanding-decisions.md` §7, §8 — what this supersedes
- `docs/EXECUTION_PLAN.md` §6 — the question list this closes
