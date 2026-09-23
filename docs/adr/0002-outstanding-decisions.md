# ADR 0002 — The six outstanding decisions gating EPIC 1, 4, 5 and 6

| | |
|---|---|
| **Status** | **Accepted**, with **D6 and §8's three open items superseded by [ADR-0003](0003-access-model-and-role-roster.md)** the same day. Six decisions taken 2026-09-20 on best-practice grounds, to unblock the stories they gate |
| **Date** | 2026-09-20 |
| **Deciders** | Data Engineering, Platform Engineering. **D2 and D5 are provisional — see §8** |
| **Story** | US-1.2, US-2.1, US-4.3, US-4.4, US-5.1, US-6.1 |
| **Supersedes** | Nothing. Complements ADR-0001 |
| **Affects** | `docs/EXECUTION_PLAN.md` §6, `cube/model/cubes/`, `thin-web-app/server.py`, `thin-web-app/app.js`, GCS HMAC keys on `886154918734-compute@developer.gserviceaccount.com` |

---

## 1. Context

`EXECUTION_PLAN.md` §6 lists five open questions "that need a human answer, not research", plus
a sixth that arrived with the credential work: what to do with the compromised GCS HMAC key. They
have been carried across eight sessions without an answer, and four stories cannot start without
them.

Waiting is not free. Three of the six have a **defensible default that is strictly safer than
the alternative and cheap to reverse**, and two more are settled by evidence already in the
repository rather than by preference. This ADR takes each one on best-practice grounds and marks
the two that remain a business judgement, so that work proceeds under a stated assumption rather
than stalling — and so that a later correction changes a documented decision instead of
discovering an undocumented one.

**Every decision here is reversible.** Where reversal has a cost, §8 records it.

---

## 2. D1 — The compromised GCS HMAC key: deactivate, never delete

**Question.** The old HMAC pair on `886154918734-compute@developer.gserviceaccount.com` has its
secret committed to this repository's history, which is what makes it compromised. A new,
uncompromised pair was minted on 2026-09-20 and is live on the SQL VM. Retire the old one how?

**Decision: deactivate it. Do not delete it.**

| | Deactivate | Delete |
|---|---|---|
| Security effect | Key authenticates nothing | Key authenticates nothing |
| Reversal | `gcloud storage hmac update --activate`, seconds | Impossible — access id and secret are both gone |
| If an unlisted consumer existed | Restore, then migrate it deliberately | Outage, then mint a new pair and hunt every consumer under pressure |

**The security benefit is identical; only the blast radius of being wrong differs.**

Being wrong is a live possibility. Measured 2026-09-20: nothing *deployed* reads the old pair —
`scbi-cube` has no `CUBEJS_DB_DUCKDB_S3_*` variables at all, and the SQL VM's
`/etc/cube-sql.env` holds the new pair. But the local reconciliation engines
(`web/member_engine.py:25-26` and its siblings) read whatever is in the **analyst's own user
environment**, and no one has surveyed those workstations. An analyst still on the old pair is
exactly the case a deletion would break irrecoverably and a deactivation would merely interrupt.

A key that has been deactivated and demonstrably unused for a week can be deleted later,
deliberately, by someone who no longer has to guess. That is a strictly better-informed decision
than the same one taken today.

**Implemented by** `scripts/blocked/06_deactivate_old_hmac.sh`, which deactivates only, carries
`--rollback`, and refuses to act when the named key is the only `ACTIVE` one.

---

## 3. D2 — Brokerage semantics (gates US-4.3): `DimAggregator`

**Question.** `DimAggregator.aggregator_brokerage_name` or
`aggregator_client_broker_consultant`?

**Decision: `DimAggregator.aggregatorBrokerageName`, over
`cnf__dim_aggregator.aggregator_brokerage_name`, joined via `aggregator_hk`.**

Three reasons, in order of weight:

1. **Grain.** The slicer filters an *organisation*. `aggregator_brokerage_name` is the brokerage;
   `aggregator_client_broker_consultant` is the named individual consultant on the account — a
   different grain. Filtering a brokerage slicer by consultant would silently return a subset of
   the brokerage's business.
2. **Join path.** `broker_consultant_hk` appears only on the **annuity** facts.
   `PRD_ARCHITECTURE_REALIGNMENT.md:152-154` already records that the earlier `MIGRATION_PLAN.md`
   binding to `DimBrokerConsultant` is wrong for this dashboard, and §4.3's corrected table
   (`:163`) names `DimAggregator` explicitly. This decision ratifies a correction the PRD has
   already made rather than introducing one.
3. **POPIA.** A consultant name is personal information about an identifiable natural person. A
   brokerage name is not. Given equal analytical utility, the non-PII column is the correct
   default, and it keeps the slicer out of scope for the PII masking in `SharedDimensions.js`.

**Also expose the consultant**, as a separate dimension member on the annuity cubes where
`broker_consultant_hk` actually lives, PII-masked like every other personal attribute. The two
are complementary; the mistake is conflating them in one slicer.

**Provisional.** `PRD_ARCHITECTURE_REALIGNMENT.md:670` carries this as a live risk — "Brokerage
via `DimAggregator` is not what the business means by 'brokerage'". The report owner can still
overturn it, and §8 records what that would cost.

---

## 4. D3 — Segmentation join path (gates US-4.4): `member_hk + date_sk`

**Question.** Join `cnf__fact_member_segmentation` on `member_segmentation_nk` — the relationship
the PBI model marks **inactive** — or on the composite `member_hk + date_sk`?

**Decision: `member_hk + date_sk`.**

`cnf__fact_member_segmentation` is member × month
(`PRD_ARCHITECTURE_REALIGNMENT.md:126`). `member_hk + date_sk` **is** that grain, so the join is
one-to-one by construction and cannot fan out. That is the whole risk in this story: US-4.4 is
flagged as the highest-risk story in the PRD (`:441`) precisely because a wrong join silently
inflates every member count on the dashboard, and §8's risk table names the same failure.

Using `member_segmentation_nk` would mean adopting a relationship its own source model has
deliberately deactivated, without any record of why it was deactivated. A surrogate key whose
uniqueness nobody has established is the weaker choice when a composite key matching the declared
grain is available.

**This decision does not relax the verification.** US-4.4's row-count equivalence test —
`distinctMembers` identical with and without the segmentation join — remains a hard gate
(`:439`). Choosing the safer join is not evidence that it is safe; the test is.

---

## 5. D4 — Gender values (gates US-6.1): render what the data returns

**Question.** Does the source carry values beyond M/F, or nulls? Does the UI need an
`Unspecified` column?

**Decision: render whatever the data returns, and bucket NULL, blank and unknown into one
explicit `Unspecified` category. Do not assume a closed domain.**

The question as posed asks us to predict a demographic attribute's domain. That is the wrong
shape of question: the answer can change without notice, in a source system nobody here owns,
and the failure is silent. The correct engineering answer is to remove the assumption instead of
resolving it.

The assumption is real and currently hardcoded. `thin-web-app/app.js` fixes **exactly two**
series in three places:

- `:769-770` — `age_band_gender`, datasets labelled `Female` and `Male`
- `:794-795` — `salary_band_gender`, the same two
- `:1242` — `gender_donut`, a two-element `backgroundColor` array, so a third category renders
  with an undefined colour even though its labels come from the data

Today a third value or a NULL does not produce an error. It produces a chart that quietly omits
members, and totals that do not reconcile to the headline count — the exact class of defect this
whole recon project exists to remove.

**Consequences for US-6.1.** The handler groups by the value returned, mapping NULL/blank to
`Unspecified`; the chart builders take their series and colours from the returned categories
rather than from a literal pair; and the reconciliation asserts that the gender breakdown sums
to the unfiltered member count. That last assertion is what makes an omitted category loud
instead of silent.

`memberGender` remains PII-masked per US-1.4 — this decision concerns aggregation, not
disclosure.

---

## 6. D5 — Dashboards 2 and 3: fix the handler for all three, keep recon scope on Dashboard 1

**Question.** Do Dashboards 2 and 3 get the same recon treatment?

**Decision: two separate answers, because it is two questions.**

1. **The shared slicer handler is fixed correctly for all three dashboards.** Not optional, and
   not extra scope: `EXECUTION_PLAN.md:207` records that Dashboards 2 and 3 share the hardcoded
   handler, so US-5.1 touches them whatever we decide. US-5.1's own final acceptance criterion
   already requires it — "the shared alias across member/investment/annuity slicer routes is
   removed; each dashboard resolves against its own fact"
   (`PRD_ARCHITECTURE_REALIGNMENT.md:456ff`). Leaving 2 and 3 on a half-migrated handler would
   mean knowingly shipping the alias bug to two dashboards while fixing it for one.
2. **The reconciliation scope stays Dashboard 1.** Recon means tracing every number to a Cube
   query and reconciling it against published PBI totals — EPIC 6's work, milestone M4. Widening
   that now would delay the one dashboard that is closest to signed off, for no gain to it.

The distinction is between *not breaking* Dashboards 2 and 3 (mandatory, and already in US-5.1)
and *certifying* them (a separate, later scope decision). The first is engineering hygiene; the
second is a roadmap call, and this ADR does not pre-empt it.

**Provisional** in the second half only: whether 2 and 3 eventually get recon is the Product
Owner's call, not this ADR's.

---

## 7. D6 — `role_assignments.json`: create it, empty, with the executive role absent

> **Superseded on the same day by [ADR-0003](0003-access-model-and-role-roster.md).** The system
> owner answered the mapping question that afternoon, so the file is no longer empty, and the
> "never name the executive role here" constraint was replaced by a stricter one: a *person* may
> hold it, a service account may not. The reasoning below stands as written — it is why the file
> was created honestly empty rather than filled with a guess, which is what made the answer a
> one-line edit when it arrived.

**Question.** `EXECUTION_PLAN.md:311` lists creating `thin-web-app/role_assignments.json` as
owed, marked *Optional — a business decision about who gets what*.

**Decision: create the file with the correct shape and no entries. Do not invent mappings. Never
name the executive role in it.**

The file is the US-1.2 mechanism and its absence was the last reason to keep the question open.
But *who* gets which role is a decision about real people that nobody has made, and an invented
mapping is an access grant nobody authorised. Those are separable: the file can exist, be valid,
and be honest about mapping nobody.

The behaviour is unchanged and safe either way — `load_role_assignments()` treats an absent file
and an empty map identically (`server.py:105-111`), so every verified caller resolves to
`ROLE_FINANCE_MEMBER` with `can_view_pii` false. What changes is that the schema, the role list
and the two hard constraints are now written down next to the file, in
`thin-web-app/ROLE_ASSIGNMENTS.md`, for whoever fills it.

**The executive role must never appear here.** It is the only role that sees PII in the clear, so
an assignment holding it defeats every mask in `SharedDimensions.js`.
`tests/test_us_8_3_sql_api_runtime.py::test_no_deploy_artefact_wires_a_bi_client_to_the_executive_role`
sweeps every `.sh`, `.ps1`, `.json`, `.env`, `.yaml` and `.yml` artefact under `data-recon/` for
that role's literal name and fails the whole suite on a hit;
`scripts/blocked/99_verify.sh` checks the same before a deploy. Both were left intact and the
runbook scripts were reworded to stop tripping the sweep — blunting the guard to accommodate the
tooling would have been the wrong trade.

**Presence is not completion.** An empty map that reads as "done" on a state board is worse than
no file at all, so `01_preflight.sh`, `07_deploy_thin_web.sh` and `99_verify.sh` now report **how
many callers are mapped**, not merely that the file exists.

---

## 8. Consequences

### What is unblocked

| Story | Was gated on | Now |
|---|---|---|
| US-4.3 | Brokerage semantics | D2 — build against `DimAggregator` |
| US-4.4 | Segmentation join path | D3 — `member_hk + date_sk`, row-count test still a hard gate |
| US-5.1 | Dashboards 2 and 3 | D5 — handler fixed for all three |
| US-6.1 | Gender values | D4 — no domain assumption to resolve |
| US-1.2 | `role_assignments.json` | D6 — file exists, schema documented |
| US-2.1 | Old HMAC key disposal | D1 — script 06 ready to run |

### Cost of reversal

- **D1** — seconds (`--rollback`). The only irreversible path is the one this decision declines.
- **D2** — the one decision with a real cost if overturned. Re-pointing the slicer means a cube
  change, a re-run of US-4.3's recon, and any figure already published under the brokerage
  breakdown being restated. **Confirm with the report owner before US-4.3 starts**, not after.
- **D3** — cheap before US-4.4 ships, expensive after: every published member count would be
  restated. The row-count equivalence test is what makes an error visible on day one.
- **D4** — none. It removes an assumption; nothing has to be undone to add one back.
- **D5** — none for the handler. The recon-scope half is a roadmap decision, deliberately left open.
- **D6** — none. Filling the map is the intended next step, not a reversal.

### Still needing a human, and not decided here

> **All three were answered later the same day — [ADR-0003](0003-access-model-and-role-roster.md).**
> The system owner takes `ROLE_EXECUTIVE_ALL` and the `sys_admin` group, which covers every
> surface below; `scripts/access/manage_access.py` and `scripts/blocked/09_apply_access.sh` are
> how the next person is added.

These were authorisation decisions about named people. No default was defensible, so nothing in
this ADR guessed at them:

1. **Who invokes `scbi-cube`, and who may open Metabase** — `05_lock_down_cloud_run.sh` has no
   default invoker list and refuses to revoke `allUsers` against an empty one.
2. **Which analysts get an IAP tunnel to 5432** — `08_grant_analyst_iap.sh`, same shape.
3. **Who gets which role** in `role_assignments.json` — D6 created the file, not the mapping.

### Explicitly out of scope

`on_schema_change` on `cnf__fact_investment_transactions` → `append_new_columns` is a reasonable
change and is **not** actioned here. It belongs to `Active Priorities` items 0–5, which are
**PARKED**; unparking is the user's call.

---

## 9. Verification log

| Claim | How checked | Result |
|---|---|---|
| Brokerage path is member-domain via `aggregator_hk` | `PRD_ARCHITECTURE_REALIGNMENT.md:152-154,163` | Confirmed; PRD already corrected it |
| `broker_consultant_hk` is annuity-only | `PRD_ARCHITECTURE_REALIGNMENT.md:153` | Confirmed |
| Segmentation fact is member × month | `PRD_ARCHITECTURE_REALIGNMENT.md:126` | Confirmed |
| Row-count equivalence is a required gate | `PRD_ARCHITECTURE_REALIGNMENT.md:439`, risk at `:670` | Confirmed |
| Gender series are hardcoded to two | `thin-web-app/app.js:769-770,794-795,1242` | Confirmed, three sites |
| Dashboards 2 and 3 share the slicer handler | `EXECUTION_PLAN.md:207`, `PRD:456ff` criterion 5 | Confirmed |
| Absent and empty `role_assignments.json` behave identically | `thin-web-app/server.py:105-111,179-196` | Confirmed |
| The executive-role sweep covers `.json` | `tests/test_us_8_3_sql_api_runtime.py` | Confirmed; suite green, 166 passed *(168 after ADR-0003's two tests)* |
| Nothing deployed reads the old HMAC pair | Measured on the project 2026-09-20 | Confirmed; local engines unsurveyed |

---

## 10. References

- `docs/EXECUTION_PLAN.md` §6 — the questions this ADR closes
- `docs/adr/0001-ducklake-or-parquet.md` — the lakehouse decision this one complements
- `thin-web-app/PRD_ARCHITECTURE_REALIGNMENT.md` §4.3, §4.4, §5, §8
- `thin-web-app/ROLE_ASSIGNMENTS.md` — D6's schema and constraints
- `scripts/blocked/README.md` — the runbook implementing D1, and the two open authorisation questions
