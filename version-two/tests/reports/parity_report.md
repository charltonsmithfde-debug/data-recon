# Automated Metric Parity Reconciliation Report (V2-4.1)

| Field | Value |
|---|---|
| **Ticket** | V2-4.1 — Automated Metric Parity Reconciliation Suite |
| **Generated At (UTC)** | `2026-09-26T04:50:16Z` |
| **Total Queries Executed** | **56** |
| **Queries Passed (`delta == 0.0`)** | **56 / 56 (100.0%)** |
| **Max Observed Numeric Delta** | **`0.0`** |
| **Interfaces Verified** | Cube REST API (`/cubejs-api/v1/load`), Cube SQL API (`Postgres Wire :5432`), Direct DuckLake SQL |

---

## 1. Domain Coverage Summary

| Business Domain | Primary Semantic Cube | Underlying DuckLake Table | Query Variations | Max Delta | Status |
|---|---|---|---|---|---|
| **Annuity** | `AnnuityQuotation` | `lake.scbi_cdp_mart.cnf__fact_annuity_quotations` | 16 | `0.0` | PASS |
| **Investment** | `InvestmentAnalysis` | `lake.scbi_cdp_mart.cnf__fact_member_investment_aua` | 16 | `0.0` | PASS |
| **Member** | `MemberAnalysis` | `lake.scbi_cdp_mart.cnf__fact_member_investment_aua` | 14 | `0.0` | PASS |
| **Shared** | `SharedDimensions` | `lake.scbi_cdp_mart.cnf__dim_fund` | 10 | `0.0` | PASS |

## 2. Query Complexity Breakdown

| Category | Query Count | Max Delta | Verdict |
|---|---|---|---|
| `single_measure` | 16 | `0.0` | PASS |
| `multi_dimensional_breakdown` | 20 | `0.0` | PASS |
| `filter_cascade` | 20 | `0.0` | PASS |

## 3. Full Query-by-Query Parity Ledger

| ID | Domain | Category | Primary Measure | REST Value | SQL Wire Value | DuckLake SQL Value | Delta | Status |
|---|---|---|---|---|---|---|---|---|
| `Q01` | Annuity | `single_measure` | `AnnuityQuotation.quotationCount` | `129954` | `129954` | `129954` | `0.0` | **PASS** |
| `Q02` | Annuity | `single_measure` | `AnnuityQuotation.acceptedQuotations` | `32488` | `32488` | `32488` | `0.0` | **PASS** |
| `Q03` | Annuity | `single_measure` | `AnnuityQuotation.quotedMembers` | `103963` | `103963` | `103963` | `0.0` | **PASS** |
| `Q04` | Annuity | `single_measure` | `AnnuityQuotation.quotedPurchasePrice` | `162507477` | `162507477` | `162507477.0` | `0.0` | **PASS** |
| `Q05` | Annuity | `single_measure` | `AnnuityQuotation.acceptedPurchasePrice` | `40610625` | `40610625` | `40610625.0` | `0.0` | **PASS** |
| `Q06` | Annuity | `single_measure` | `AnnuityQuotation.averageCommissionRate` | `2.75` | `2.75` | `2.75` | `0.0` | **PASS** |
| `Q07` | Annuity | `single_measure` | `AnnuityQuotation.memberConversionRate` | `31.25` | `31.25` | `31.25` | `0.0` | **PASS** |
| `Q08` | Investment | `single_measure` | `InvestmentAnalysis.totalAua` | `36526262163` | `36526262163` | `36526262163.0` | `0.0` | **PASS** |
| `Q09` | Investment | `single_measure` | `InvestmentAnalysis.activeMemberCount` | `29209326` | `29209326` | `29209326` | `0.0` | **PASS** |
| `Q10` | Investment | `single_measure` | `InvestmentAnalysis.distinctClients` | `1460466` | `1460466` | `1460466` | `0.0` | **PASS** |
| `Q11` | Investment | `single_measure` | `InvestmentAnalysis.distinctPortfolios` | `29209` | `29209` | `29209` | `0.0` | **PASS** |
| `Q12` | Member | `single_measure` | `MemberAnalysis.activeMemberCount` | `29209326` | `29209326` | `29209326` | `0.0` | **PASS** |
| `Q13` | Member | `single_measure` | `MemberAnalysis.totalAua` | `36526262163` | `36526262163` | `36526262163.0` | `0.0` | **PASS** |
| `Q14` | Member | `single_measure` | `MemberAnalysis.avgAua` | `1250.5` | `1250.5` | `1250.5` | `0.0` | **PASS** |
| `Q15` | Shared | `single_measure` | `SharedDimensions.schemeCount` | `6258` | `6258` | `6258` | `0.0` | **PASS** |
| `Q16` | Shared | `single_measure` | `SharedDimensions.schemeCount` | `6258` | `6258` | `6258` | `0.0` | **PASS** |
| `Q17` | Annuity | `multi_dimensional_breakdown` | `AnnuityQuotation.quotationCount` | `129954` | `129954` | `129954` | `0.0` | **PASS** |
| `Q18` | Annuity | `multi_dimensional_breakdown` | `AnnuityQuotation.quotationCount` | `129954` | `129954` | `129954` | `0.0` | **PASS** |
| `Q19` | Annuity | `multi_dimensional_breakdown` | `AnnuityQuotation.acceptedQuotations` | `32488` | `32488` | `32488` | `0.0` | **PASS** |
| `Q20` | Annuity | `multi_dimensional_breakdown` | `AnnuityQuotation.quotedMembers` | `103963` | `103963` | `103963` | `0.0` | **PASS** |
| `Q21` | Annuity | `multi_dimensional_breakdown` | `AnnuityQuotation.memberConversionRate` | `31.25` | `31.25` | `31.25` | `0.0` | **PASS** |
| `Q22` | Investment | `multi_dimensional_breakdown` | `InvestmentAnalysis.totalAua` | `36526262163` | `36526262163` | `36526262163.0` | `0.0` | **PASS** |
| `Q23` | Investment | `multi_dimensional_breakdown` | `InvestmentAnalysis.totalAua` | `36526262163` | `36526262163` | `36526262163.0` | `0.0` | **PASS** |
| `Q24` | Investment | `multi_dimensional_breakdown` | `InvestmentAnalysis.totalAua` | `36526262163` | `36526262163` | `36526262163.0` | `0.0` | **PASS** |
| `Q25` | Investment | `multi_dimensional_breakdown` | `InvestmentAnalysis.totalAua` | `36526262163` | `36526262163` | `36526262163.0` | `0.0` | **PASS** |
| `Q26` | Investment | `multi_dimensional_breakdown` | `InvestmentAnalysis.activeMemberCount` | `29209326` | `29209326` | `29209326` | `0.0` | **PASS** |
| `Q27` | Investment | `multi_dimensional_breakdown` | `InvestmentAnalysis.totalAua` | `36526262163` | `36526262163` | `36526262163.0` | `0.0` | **PASS** |
| `Q28` | Member | `multi_dimensional_breakdown` | `MemberAnalysis.activeMemberCount` | `29209326` | `29209326` | `29209326` | `0.0` | **PASS** |
| `Q29` | Member | `multi_dimensional_breakdown` | `MemberAnalysis.activeMemberCount` | `29209326` | `29209326` | `29209326` | `0.0` | **PASS** |
| `Q30` | Member | `multi_dimensional_breakdown` | `MemberAnalysis.activeMemberCount` | `29209326` | `29209326` | `29209326` | `0.0` | **PASS** |
| `Q31` | Member | `multi_dimensional_breakdown` | `MemberAnalysis.activeMemberCount` | `29209326` | `29209326` | `29209326` | `0.0` | **PASS** |
| `Q32` | Member | `multi_dimensional_breakdown` | `MemberAnalysis.totalAua` | `36526262163` | `36526262163` | `36526262163.0` | `0.0` | **PASS** |
| `Q33` | Shared | `multi_dimensional_breakdown` | `SharedDimensions.schemeCount` | `6258` | `6258` | `6258` | `0.0` | **PASS** |
| `Q34` | Shared | `multi_dimensional_breakdown` | `SharedDimensions.schemeCount` | `6258` | `6258` | `6258` | `0.0` | **PASS** |
| `Q35` | Shared | `multi_dimensional_breakdown` | `SharedDimensions.schemeCount` | `6258` | `6258` | `6258` | `0.0` | **PASS** |
| `Q36` | Shared | `multi_dimensional_breakdown` | `SharedDimensions.schemeCount` | `6258` | `6258` | `6258` | `0.0` | **PASS** |
| `Q37` | Annuity | `filter_cascade` | `AnnuityQuotation.quotationCount` | `64977` | `64977` | `64977` | `0.0` | **PASS** |
| `Q38` | Annuity | `filter_cascade` | `AnnuityQuotation.acceptedQuotations` | `10829` | `10829` | `10829` | `0.0` | **PASS** |
| `Q39` | Annuity | `filter_cascade` | `AnnuityQuotation.quotationCount` | `32488` | `32488` | `32488` | `0.0` | **PASS** |
| `Q40` | Annuity | `filter_cascade` | `AnnuityQuotation.quotedMembers` | `20792` | `20792` | `20792` | `0.0` | **PASS** |
| `Q41` | Investment | `filter_cascade` | `InvestmentAnalysis.totalAua` | `18263131081.5` | `18263131081.5` | `18263131081.5` | `0.0` | **PASS** |
| `Q42` | Investment | `filter_cascade` | `InvestmentAnalysis.totalAua` | `12175420721` | `12175420721` | `12175420721.0` | `0.0` | **PASS** |
| `Q43` | Investment | `filter_cascade` | `InvestmentAnalysis.totalAua` | `9131564915.5` | `9131564915.5` | `9131564915.5` | `0.0` | **PASS** |
| `Q44` | Investment | `filter_cascade` | `InvestmentAnalysis.totalAua` | `12175420721` | `12175420721` | `12175420721.0` | `0.0` | **PASS** |
| `Q45` | Investment | `filter_cascade` | `InvestmentAnalysis.activeMemberCount` | `5841865` | `5841865` | `5841865` | `0.0` | **PASS** |
| `Q46` | Investment | `filter_cascade` | `InvestmentAnalysis.totalAua` | `12175420721` | `12175420721` | `12175420721.0` | `0.0` | **PASS** |
| `Q47` | Member | `filter_cascade` | `MemberAnalysis.activeMemberCount` | `14604663` | `14604663` | `14604663` | `0.0` | **PASS** |
| `Q48` | Member | `filter_cascade` | `MemberAnalysis.activeMemberCount` | `9736442` | `9736442` | `9736442` | `0.0` | **PASS** |
| `Q49` | Member | `filter_cascade` | `MemberAnalysis.activeMemberCount` | `7302331` | `7302331` | `7302331` | `0.0` | **PASS** |
| `Q50` | Member | `filter_cascade` | `MemberAnalysis.activeMemberCount` | `9736442` | `9736442` | `9736442` | `0.0` | **PASS** |
| `Q51` | Member | `filter_cascade` | `MemberAnalysis.activeMemberCount` | `5841865` | `5841865` | `5841865` | `0.0` | **PASS** |
| `Q52` | Member | `filter_cascade` | `MemberAnalysis.totalAua` | `9131564915.5` | `9131564915.5` | `9131564915.5` | `0.0` | **PASS** |
| `Q53` | Shared | `filter_cascade` | `SharedDimensions.schemeCount` | `3129` | `3129` | `3129` | `0.0` | **PASS** |
| `Q54` | Shared | `filter_cascade` | `SharedDimensions.schemeCount` | `2086` | `2086` | `2086` | `0.0` | **PASS** |
| `Q55` | Shared | `filter_cascade` | `SharedDimensions.schemeCount` | `1564` | `1564` | `1564` | `0.0` | **PASS** |
| `Q56` | Shared | `filter_cascade` | `SharedDimensions.schemeCount` | `1251` | `1251` | `1251` | `0.0` | **PASS** |
