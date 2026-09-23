# Target Enterprise Architecture Migration Plan: Thin Web App & Centralized Cube.js

**Location:** `C:\Users\G988557\Documents\Code\github_DBT\data-recon\thin-web-app`  
**Target Date:** September 2026  
**Architecture:** Thin Web App (Client UI) + Google Cloud Run (`scbi-cube`) + Google Cloud SQL (`scbi-ducklake-catalog`) + Google Cloud Storage (`scbi-ducklake-myanalyticsproduct`)

---

## 1. Executive Summary & Principles

This document defines the formal, test-driven migration plan to transition the Sanlam Online Analytics Portal from its current hybrid state (where the web app runs an embedded in-memory DuckDB engine querying GCS directly) into the **Target Enterprise Architecture**.

### Core Architecture Principles:
1. **Single Source of Truth**: All data transformations, metrics, measures, and dimension calculations reside strictly inside **`scbi-cube` (Google Cloud Run)**.
2. **Thin Web App**: The web app in `thin-web-app` is a lightweight client. It contains **no embedded DuckDB**, **no local database files**, and **no direct GCS credentials**. It acts purely as a presentation layer consuming `/cubejs-api/v1/load`.
3. **100% Data-Driven (Zero Hardcoding)**: No filter dropdown, KPI card, or chart axis may contain hardcoded arrays. Every single value is dynamically resolved from live data via Cube.js.
4. **Dynamic Data Parameters Everywhere (No Hardcoded WHERE Clauses)**: Slicers and dashboard queries never execute against static literals. Every ground truth recon query and Cube.js API payload is explicitly parameterized by the active UI filter state (`:selected_date_sk`, `:selected_fund_name`, `:selected_client_name`, `:selected_employer_name`, etc.).
5. **Preserved Look, Feel & UX**: The visual design, CSS design system, typography, card layouts, loading overlays, fetch counters, and SysAdmin observability cockpit remain identical to the approved portal design.
6. **Test-Driven Development (TDD) with Quality Gates**: Development is split into small, manageable user stories. No user story is marked `DONE` without a verifiable ground-truth SQL test query executed against the Lakehouse Marts and proven to match the Cube.js response under identical dynamic filter parameters.

---

## 2. Dynamic Slicer & Filter Parameter Architecture

### 2.1 The Active Filter State (`SlicerParams`)
At any given moment, the user's selections across the portal constitute a unified **Active Filter State** object:

```typescript
interface ActiveFilterState {
  calendarYear?: number | null;           // :selected_year (e.g. 2025)
  dateSk?: number | null;                 // :selected_date_sk (e.g. 20251231)
  businessUnit?: string | null;           // :selected_business_unit ('Sanlam Umbrella Fund')
  fundName?: string | null;               // :selected_fund_name ('Sanlam Umbrella Pension Fund')
  clientName?: string | null;             // :selected_client_name ('Controlled Irrigation CC')
  employerName?: string | null;           // :selected_employer_name ('Standard Bank SA')
  brokerage?: string | null;              // :selected_brokerage ('Alexander Forbes')
  paypoint?: string | null;               // :selected_paypoint ('Head Office')
}
```

### 2.2 Standard SQL Ground Truth Parameter Binding Pattern
To verify data reconciliation between GCS Lakehouse Marts and `scbi-cube`, ground truth SQL queries use parameter placeholders (`:param_name`). When a filter parameter is unselected (`NULL`), the clause acts as a wildcard, returning the full dataset without restricting that dimension:

```sql
WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
  AND (:selected_year IS NULL OR d.CALENDAR_YEAR = :selected_year)
  AND (:selected_business_unit IS NULL OR fd.FUND_CLASSIFICATION = :selected_business_unit)
  AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
  AND (:selected_client_name IS NULL OR c.CLIENT_NAME = :selected_client_name)
  AND (:selected_employer_name IS NULL OR e.EMPLOYER_NAME = :selected_employer_name)
  AND (:selected_brokerage IS NULL OR bc.BROKER_CONSULTANT_BROKERAGE = :selected_brokerage)
  AND (:selected_paypoint IS NULL OR pp.PAYPOINT_NAME = :selected_paypoint)
```

### 2.3 Cube.js Dynamic Payload Filter Compilation
The Thin Web App frontend translates active non-null filters into Cube.js query filter definitions dynamically:

```javascript
function buildCubeFilters(filterState) {
  const filters = [];
  if (filterState.dateSk) {
    filters.push({ member: "MemberMonthly.dateSk", operator: "equals", values: [String(filterState.dateSk)] });
  }
  if (filterState.calendarYear) {
    filters.push({ member: "DimDate.calendarYear", operator: "equals", values: [String(filterState.calendarYear)] });
  }
  if (filterState.businessUnit) {
    filters.push({ member: "DimFund.fundClassification", operator: "equals", values: [filterState.businessUnit] });
  }
  if (filterState.fundName) {
    filters.push({ member: "DimFund.fundName", operator: "equals", values: [filterState.fundName] });
  }
  if (filterState.clientName) {
    filters.push({ member: "DimClient.clientName", operator: "equals", values: [filterState.clientName] });
  }
  if (filterState.employerName) {
    filters.push({ member: "DimEmployer.employerName", operator: "equals", values: [filterState.employerName] });
  }
  return filters;
}
```

### 2.4 Cascading Dependency Matrix (DAG)
Filter dropdowns are not isolated; their available choices are themselves dynamically parameterized by the selections of other active filters:

| Slicer Target | Driven By Parameters | Cascading Action |
|---|---|---|
| **Snapshot Date** | `:selected_year` | When Year changes, Date dropdown queries only dates in that year. |
| **Business Unit** | `:selected_date_sk` | Narrows down to classifications active in that valuation snapshot. |
| **Fund Name** | `:selected_business_unit`, `:selected_client_name`, `:selected_employer_name`, `:selected_date_sk` | Narrows fund choices to those matching active client, employer, and classification. |
| **Client Name** | `:selected_fund_name`, `:selected_business_unit`, `:selected_employer_name`, `:selected_date_sk` | Restricts clients to participating entities under selected fund and employer. |
| **Employer Name** | `:selected_fund_name`, `:selected_client_name`, `:selected_date_sk` | Restricts employers to participating units under selected fund and client. |
| **Brokerage** | `:selected_date_from`, `:selected_date_to`, `:selected_fund_name` | Restricts brokerages to active quotation writers in the period. |
| **Paypoint** | `:selected_fund_name`, `:selected_employer_name`, `:selected_classification` | Narrows down to paypoints belonging to selected employer and scheme. |

---

## 3. Sprint Roadmap Overview

| Sprint | Focus Area | Deliverables & Quality Gates |
|---|---|---|
| **Sprint 0** | **Foundation & Model Alignment** | Scaffolding of `thin-web-app/`, aligning `data-recon/cube/model/cubes/SharedDimensions.js` and cube definitions. |
| **Sprint 1** | **Data-Driven Cascading Filters** | Parameterized user stories and recon queries for Date, Year, Business Unit, Fund, Client, Employer, Brokerage, and Paypoint. |
| **Sprint 2** | **Member Analysis Summary** | Parameterized Demographics, Financial KPIs, and Pages 1–5 (Age Bands, Retirement, Salary Matrix, Contributions, Products & Risk). |
| **Sprint 3** | **Investment Analysis** | Parameterized Market Value KPIs and Pages 1–5 (Holdings, Risk Matrix, Distribution, Pensionable Service, Allocations). |
| **Sprint 4** | **Life Annuity Reporting** | Parameterized 10 individual pages migrated to `AnnuityQuotation` cube with pre-aggregations. |
| **Sprint 5** | **Automated Test Suite & APM** | Parameterized matrix regression suite validating SQL ground-truth against Cube.js API; Thin APM cockpit. |

---

## 4. Sprint 0: Foundation & Model Alignment

### User Story 0.1: Thin Web App Repository Scaffolding
* **User Story**:
  > *As a SysAdmin / Enterprise Architect, I want the web application to run from `thin-web-app/` without an embedded DuckDB engine or GCS secrets, so that the client footprint is minimal, secure, and purely API-driven.*
* **Implementation Tasks**:
  1. Initialize `C:\Users\G988557\Documents\Code\github_DBT\data-recon\thin-web-app`.
  2. Deploy clean `index.html`, `style.css`, `app.js` using the exact approved CSS tokens and layouts.
  3. Deploy lightweight proxy `server.py` (without DuckDB) that signs Cube.js JWT tokens and proxies `/cubejs-api/v1/load`.
* **Acceptance Test**:
  * Verify `psutil` process memory is `< 50MB` (vs 500MB+ for local DuckDB).
  * Confirm zero references to `import duckdb`, `INSTALL httpfs`, or `GOOG1E...` keys in the thin web app codebase.

### User Story 0.2: `SharedDimensions.js` Alignment in `scbi-cube`
* **User Story**:
  > *As a BI Developer, I want `DimFund` and `DimDate` in `data-recon/cube/model/cubes/SharedDimensions.js` to expose `fundClassification`, `fundStatus`, and calendar hierarchies, so that Cube.js supports all cascading filter parameters.*
* **Ground Truth SQL (Parameterized by classification filter)**:
  ```sql
  -- Parameter: :filter_classifications (e.g. ['Sanlam Umbrella Fund', 'Standalone Fund'])
  SELECT 
      fund_hk,
      fund_name,
      fund_classification,
      fund_status
  FROM scbi_cdp_mart.cnf__dim_fund
  WHERE (:selected_classification IS NULL OR fund_classification = :selected_classification)
  LIMIT 10;
  ```
* **Cube.js Target Schema Update (`SharedDimensions.js`)**:
  ```javascript
  cube('DimFund', {
    sql: `SELECT * FROM scbi_cdp_mart.cnf__dim_fund`,
    dimensions: {
      fundHk: { sql: 'fund_hk', type: 'string', primaryKey: true },
      fundName: { sql: 'fund_name', type: 'string' },
      fundClassification: { sql: 'fund_classification', type: 'string' },
      fundStatus: { sql: 'fund_status', type: 'string' }
    }
  });
  ```
* **Acceptance Test**: Querying `DimFund.fundClassification` via Cube.js REST API returns live classifications matching the database.

---

## 5. Sprint 1: Test-Driven Cascading Filters (All 3 Dashboards)

### User Story 1.1: Snapshot Date Filter (`DD-MON-YYYY`)
* **User Story**:
  > *As a User, I want to be able to filter reports and dashboards based on a Date formatted as `DD-MON-YYYY` (e.g. `31-DEC-2025`), restricted by the selected Year if one is chosen.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameter: :selected_year (e.g. 2025 or NULL for all available years)
  SELECT DISTINCT 
      f.DATE_SK,
      UPPER(STRFTIME(CAST(f.DATE_NK AS DATE), '%d-%b-%Y')) as formatted_date,
      COUNT(DISTINCT f.MEMBER_HK) as member_count
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_sdp_mart.dim_date d ON f.DATE_SK = d.DATE_SK
  WHERE (:selected_year IS NULL OR d.CALENDAR_YEAR = :selected_year)
  GROUP BY 1, 2
  ORDER BY f.DATE_SK DESC;
  ```
* **Cube.js API Payload**:
  ```json
  {
    "measures": ["MemberMonthly.distinctMembers"],
    "dimensions": ["MemberMonthly.dateSk", "DimDate.dateNk"],
    "filters": [
      // Injected dynamically when :selected_year is provided:
      { "member": "DimDate.calendarYear", "operator": "equals", "values": [":selected_year"] }
    ],
    "order": { "MemberMonthly.dateSk": "desc" }
  }
  ```
* **Acceptance Test**: Pass `:selected_year = 2025` -> Verify all returned date snapshot options belong strictly to calendar year 2025.

---

### User Story 1.2: Calendar Year Filter with Date Hierarchy Cascade
* **User Story**:
  > *As a User, I want to be able to filter reports on "Year", and ensure that the Date dropdown options dynamically restrict to snapshot valuation dates within that year.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameter: :selected_year (fed from the Year dropdown)
  SELECT DISTINCT 
      d.CALENDAR_YEAR,
      f.DATE_SK,
      UPPER(STRFTIME(CAST(f.DATE_NK AS DATE), '%d-%b-%Y')) as formatted_date
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_sdp_mart.dim_date d ON f.DATE_SK = d.DATE_SK
  WHERE (:selected_year IS NULL OR d.CALENDAR_YEAR = :selected_year)
  ORDER BY f.DATE_SK DESC;
  ```
* **Cube.js API Payload**:
  ```json
  {
    "dimensions": ["DimDate.calendarYear", "MemberMonthly.dateSk", "DimDate.dateNk"],
    "filters": [
      { "member": "DimDate.calendarYear", "operator": "equals", "values": [":selected_year"] }
    ],
    "order": { "MemberMonthly.dateSk": "desc" }
  }
  ```
* **Acceptance Test**: When `:selected_year = 2025`, exactly 12 month-end valuation dates are returned; zero 2024 dates appear.

---

### User Story 1.3: Business Unit Filter (`dim_fund.fund_classification`)
* **User Story**:
  > *As a User, I want to filter by Business Unit (`dim_fund.fund_classification`), restricting all downstream funds, clients, and employers according to the chosen business unit and snapshot date.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_business_unit
  SELECT 
      fd.FUND_CLASSIFICATION as business_unit,
      COUNT(DISTINCT fd.FUND_HK) as available_funds,
      COUNT(DISTINCT f.CLIENT_HK) as available_clients,
      COUNT(DISTINCT f.EMPLOYER_HK) as available_employers
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_business_unit IS NULL OR fd.FUND_CLASSIFICATION = :selected_business_unit)
  GROUP BY 1
  ORDER BY 2 DESC;
  ```
* **Cube.js API Payload**:
  ```json
  {
    "dimensions": ["DimFund.fundClassification"],
    "measures": ["MemberMonthly.distinctMembers", "MemberMonthly.totalAua"],
    "filters": [
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundClassification", "operator": "equals", "values": [":selected_business_unit"] }
    ]
  }
  ```
* **Acceptance Test**: Selecting `Sanlam Umbrella Fund` restricts fund dropdown choices exclusively to umbrella funds.

---

### User Story 1.4: Fund Name Filter with Bidirectional Cascade
* **User Story**:
  > *As a User, I want to filter by Fund Name, and have Client, Employer, and Date filters restricted strictly to participants of that fund.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters fed from UI filter state:
  -- :selected_fund_name, :selected_business_unit, :selected_date_sk
  SELECT DISTINCT 
      c.CLIENT_NAME,
      e.EMPLOYER_NAME,
      COUNT(DISTINCT f.MEMBER_HK) as active_members
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  JOIN scbi_cdp_mart.cnf__dim_client c ON f.CLIENT_HK = c.CLIENT_HK
  JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  WHERE (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_business_unit IS NULL OR fd.FUND_CLASSIFICATION = :selected_business_unit)
    AND (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
  GROUP BY 1, 2
  ORDER BY 3 DESC
  LIMIT 25;
  ```
* **Cube.js API Payload**:
  ```json
  {
    "dimensions": ["DimClient.clientName", "DimEmployer.employerName"],
    "measures": ["MemberMonthly.distinctMembers"],
    "filters": [
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] },
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] }
    ],
    "order": { "MemberMonthly.distinctMembers": "desc" },
    "limit": 25
  }
  ```
* **Acceptance Test**: Passing `:selected_fund_name` dynamically populates the Client and Employer dropdowns with only entities linked to that fund.

---

### User Story 1.5: Client Name Filter (`dim_client.client_name`)
* **User Story**:
  > *As a User, I want to filter by Client Name, and ensure that the Fund and Employer dropdowns cascade down to only those participating under that client.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters fed from UI filter state:
  -- :selected_client_name, :selected_fund_name, :selected_date_sk
  SELECT DISTINCT 
      fd.FUND_NAME,
      e.EMPLOYER_NAME,
      COUNT(DISTINCT f.MEMBER_HK) as active_members
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_client c ON f.CLIENT_HK = c.CLIENT_HK
  JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  WHERE (:selected_client_name IS NULL OR c.CLIENT_NAME = :selected_client_name)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
  GROUP BY 1, 2
  ORDER BY 3 DESC;
  ```
* **Cube.js API Payload**:
  ```json
  {
    "dimensions": ["DimFund.fundName", "DimEmployer.employerName"],
    "measures": ["MemberMonthly.distinctMembers"],
    "filters": [
      { "member": "DimClient.clientName", "operator": "equals", "values": [":selected_client_name"] },
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] }
    ],
    "order": { "MemberMonthly.distinctMembers": "desc" }
  }
  ```
* **Acceptance Test**: Pass `:selected_client_name` -> Assert only employers and funds participating under that client are returned.

---

### User Story 1.6: Employer Filter (`dim_employer.employer_name`)
* **User Story**:
  > *As a User, I want to filter by Employer Name, and have all remaining filters dynamically restricted to that employer's fund schemes and member cohorts.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters fed from UI filter state:
  -- :selected_employer_name, :selected_client_name, :selected_fund_name, :selected_date_sk
  SELECT DISTINCT 
      fd.FUND_NAME,
      c.CLIENT_NAME,
      COUNT(DISTINCT f.MEMBER_HK) as member_count
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  JOIN scbi_cdp_mart.cnf__dim_client c ON f.CLIENT_HK = c.CLIENT_HK
  WHERE (:selected_employer_name IS NULL OR e.EMPLOYER_NAME = :selected_employer_name)
    AND (:selected_client_name IS NULL OR c.CLIENT_NAME = :selected_client_name)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
  GROUP BY 1, 2
  ORDER BY 3 DESC;
  ```
* **Cube.js API Payload**:
  ```json
  {
    "dimensions": ["DimFund.fundName", "DimClient.clientName"],
    "measures": ["MemberMonthly.distinctMembers"],
    "filters": [
      { "member": "DimEmployer.employerName", "operator": "equals", "values": [":selected_employer_name"] },
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] }
    ]
  }
  ```
* **Acceptance Test**: Pass `:selected_employer_name` -> Returned funds match the exact employer portfolio schemes.

---

### User Story 1.7: Brokerage / Consultant Filter (`dim_broker_consultant`)
* **User Story**:
  > *As a Regional Sales Director, I want to filter by Brokerage Name, so that quotation volumes and consultant lists reflect only business handled by that brokerage.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters fed from UI filter state:
  -- :selected_brokerage, :selected_date_from, :selected_date_to
  SELECT DISTINCT 
      bc.BROKER_CONSULTANT_NAME,
      bc.BROKER_CONSULTANT_TEAM,
      COUNT(DISTINCT f.QUOTATION_NUMBER) as quote_count,
      ROUND(SUM(f.QUOTATION_PURCHASE_PRICE), 2) as total_quoted_value
  FROM scbi_cdp_mart.cnf__fact_annuity_quotations f
  JOIN scbi_cdp_mart.cnf__dim_broker_consultant bc ON f.QUOTED_BROKER_CONSULTANT_HK = bc.BROKER_CONSULTANT_HK
  WHERE (:selected_brokerage IS NULL OR bc.BROKER_CONSULTANT_BROKERAGE = :selected_brokerage)
    AND (:selected_date_from IS NULL OR f.DATE_NK >= :selected_date_from)
    AND (:selected_date_to IS NULL OR f.DATE_NK <= :selected_date_to)
  GROUP BY 1, 2
  ORDER BY 4 DESC;
  ```
* **Cube.js API Payload**:
  ```json
  {
    "dimensions": ["DimBrokerConsultant.brokerConsultantName", "DimBrokerConsultant.brokerConsultantTeam"],
    "measures": ["AnnuityQuotation.quotationCount", "AnnuityQuotation.quotedPurchasePrice"],
    "filters": [
      { "member": "DimBrokerConsultant.brokerConsultantBrokerage", "operator": "equals", "values": [":selected_brokerage"] }
    ]
  }
  ```
* **Acceptance Test**: Consultant and team lists cascade exclusively to advisors under that brokerage.

---

### User Story 1.8: Paypoint Classification Filter (`dim_paypoint`)
* **User Story**:
  > *As an Operations Manager, I want to filter by Paypoint Classification, so that paypoint and member distributions reflect that operational segment.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters fed from UI filter state:
  -- :selected_classification, :selected_fund_name, :selected_employer_name, :selected_date_sk
  SELECT DISTINCT 
      pp.PAYPOINT_NAME,
      COUNT(DISTINCT f.MEMBER_HK) as active_members,
      ROUND(SUM(f.AUA_AMOUNT), 2) as total_aua
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_paypoint pp ON f.PAYPOINT_HK = pp.PAYPOINT_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  WHERE (:selected_classification IS NULL OR pp.PAYPOINT_CLASSIFICATION = :selected_classification)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_employer_name IS NULL OR e.EMPLOYER_NAME = :selected_employer_name)
    AND (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
  GROUP BY 1
  ORDER BY 2 DESC;
  ```
* **Cube.js API Payload**:
  ```json
  {
    "dimensions": ["DimPaypoint.paypointName"],
    "measures": ["MemberMonthly.distinctMembers", "MemberMonthly.totalAua"],
    "filters": [
      { "member": "DimPaypoint.paypointClassification", "operator": "equals", "values": [":selected_classification"] },
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] }
    ]
  }
  ```
* **Acceptance Test**: Returned paypoint names belong strictly to the selected operational class and fund scheme.

---

## 6. Sprint 2: Member Analysis Summary — KPIs & 5 Sub-Pages

### User Story 2.1: Executive Demographics & Financial Headline Cards
* **User Story**:
  > *As a Finance Executive, I want to see Total Members, Male/Female breakdown, Weighted Average Age, Total AUA, Average AUA, and Total Monthly Salary calculated from live data via Cube.js, fed dynamically by the active filter state.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters fed dynamically from active UI filter state:
  -- :selected_date_sk, :selected_fund_name, :selected_business_unit, :selected_client_name, :selected_employer_name
  SELECT 
      COUNT(DISTINCT f.MEMBER_HK) as total_members,
      ROUND(SUM(f.AUA_AMOUNT), 2) as total_aua,
      ROUND(AVG(f.AUA_AMOUNT), 2) as avg_aua,
      COUNT(DISTINCT CASE WHEN m.MEMBER_GENDER = 'Male' THEN m.MEMBER_HK END) as male_count,
      COUNT(DISTINCT CASE WHEN m.MEMBER_GENDER = 'Female' THEN m.MEMBER_HK END) as female_count,
      ROUND(AVG(COALESCE(m.CURRENT_AGE, 40)), 1) as avg_age
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_member m ON f.MEMBER_HK = m.MEMBER_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_client c ON f.CLIENT_HK = c.CLIENT_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_business_unit IS NULL OR fd.FUND_CLASSIFICATION = :selected_business_unit)
    AND (:selected_client_name IS NULL OR c.CLIENT_NAME = :selected_client_name)
    AND (:selected_employer_name IS NULL OR e.EMPLOYER_NAME = :selected_employer_name);
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": [
      "MemberMonthly.distinctMembers",
      "MemberMonthly.totalAua",
      "MemberMonthly.avgAua"
    ],
    "dimensions": ["DimMember.memberGender"],
    "filters": [
      // Dynamically added based on user's active selections:
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] },
      { "member": "DimClient.clientName", "operator": "equals", "values": [":selected_client_name"] },
      { "member": "DimEmployer.employerName", "operator": "equals", "values": [":selected_employer_name"] }
    ]
  }
  ```
* **Acceptance Test**: UI KPI cards match the SQL query output exactly across varied filter slices with 0.00% variance.

---

### User Story 2.2: Page 1 — Age Band Histogram
* **User Story**:
  > *As an Actuary, I want to view Member Distribution by Age Band (<18, 18-24, 25-34, 35-44, 45-54, 55-64, 65+) driven dynamically by active slicers.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters fed dynamically from active UI filter state:
  -- :selected_date_sk, :selected_fund_name, :selected_client_name, :selected_employer_name
  SELECT 
      m.MEMBER_AGE_BAND,
      COUNT(DISTINCT f.MEMBER_HK) as member_count
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_member m ON f.MEMBER_HK = m.MEMBER_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_client c ON f.CLIENT_HK = c.CLIENT_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_client_name IS NULL OR c.CLIENT_NAME = :selected_client_name)
    AND (:selected_employer_name IS NULL OR e.EMPLOYER_NAME = :selected_employer_name)
  GROUP BY 1
  ORDER BY 1;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": ["MemberMonthly.distinctMembers"],
    "dimensions": ["DimMember.memberAgeBand"],
    "filters": [
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ]
  }
  ```
* **Acceptance Test**: Chart bar heights reconcile 1:1 with SQL counts for each age bracket under the active filter slice.

---

### User Story 2.3: Page 2 — Normal Retirement Age & Proximity Distribution
* **User Story**:
  > *As a Plan Consultant, I want to analyze member proximity to Normal Retirement Age (Years to NRA) dynamically filtered by scheme and employer.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name, :selected_employer_name
  SELECT 
      CASE 
          WHEN (COALESCE(m.NORMAL_RETIREMENT_AGE, 65) - m.CURRENT_AGE) <= 0 THEN 'At / Past NRA'
          WHEN (COALESCE(m.NORMAL_RETIREMENT_AGE, 65) - m.CURRENT_AGE) <= 5 THEN '0 - 5 Years'
          WHEN (COALESCE(m.NORMAL_RETIREMENT_AGE, 65) - m.CURRENT_AGE) <= 10 THEN '6 - 10 Years'
          WHEN (COALESCE(m.NORMAL_RETIREMENT_AGE, 65) - m.CURRENT_AGE) <= 20 THEN '11 - 20 Years'
          ELSE '20+ Years'
      END as nra_bracket,
      COUNT(DISTINCT f.MEMBER_HK) as member_count,
      ROUND(SUM(f.AUA_AMOUNT), 2) as total_aua
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_member m ON f.MEMBER_HK = m.MEMBER_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_employer_name IS NULL OR e.EMPLOYER_NAME = :selected_employer_name)
  GROUP BY 1
  ORDER BY 2 DESC;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": ["MemberMonthly.distinctMembers", "MemberMonthly.totalAua"],
    "dimensions": ["DimMember.nraProximityBand"],
    "filters": [
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ]
  }
  ```

---

### User Story 2.4: Page 3 — Age & Salary 2D Heatmap Matrix
* **User Story**:
  > *As an Executive, I want to inspect a cross-tabulated matrix of Member Salary Tiers vs Age Bands, parameterized by the active slicers.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name, :selected_client_name
  SELECT 
      m.MEMBER_AGE_BAND,
      m.ANNUAL_SALARY_BAND,
      COUNT(DISTINCT f.MEMBER_HK) as member_count,
      ROUND(AVG(f.AUA_AMOUNT), 2) as avg_aua
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_member m ON f.MEMBER_HK = m.MEMBER_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_client c ON f.CLIENT_HK = c.CLIENT_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_client_name IS NULL OR c.CLIENT_NAME = :selected_client_name)
  GROUP BY 1, 2
  ORDER BY 1, 2;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": ["MemberMonthly.distinctMembers", "MemberMonthly.avgAua"],
    "dimensions": ["DimMember.memberAgeBand", "DimMember.annualSalaryBand"],
    "filters": [
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ]
  }
  ```

---

### User Story 2.5: Page 4 — Member & Employer Contributions Analysis
* **User Story**:
  > *As a Benefits Specialist, I want to track Gross Contributions, Net Contributions, and Admin Deductions dynamically filtered by active slicers.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name, :selected_employer_name
  SELECT 
      ROUND(SUM(f.MEMBER_CONTRIBUTION_AMOUNT), 2) as total_member_contrib,
      ROUND(SUM(f.EMPLOYER_CONTRIBUTION_AMOUNT), 2) as total_employer_contrib,
      ROUND(SUM(f.TOTAL_CONTRIBUTION_AMOUNT), 2) as total_gross_contrib,
      ROUND(SUM(f.NET_CONTRIBUTION_AMOUNT), 2) as total_net_contrib
  FROM scbi_cdp_mart.cnf__fact_member_contributions f
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_employer_name IS NULL OR e.EMPLOYER_NAME = :selected_employer_name);
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": [
      "MemberContributions.totalMemberContrib",
      "MemberContributions.totalEmployerContrib",
      "MemberContributions.totalGrossContrib",
      "MemberContributions.totalNetContrib"
    ],
    "filters": [
      { "member": "MemberContributions.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ]
  }
  ```

---

### User Story 2.6: Page 5 — Top 10 Risk Products & Coverage
* **User Story**:
  > *As a Risk Underwriter, I want to view the Top 10 Risk Products by insured cover, grouped by member gender and filtered by the active slicers.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name, :selected_client_name
  SELECT 
      rp.PRODUCT_NAME,
      m.MEMBER_GENDER,
      COUNT(DISTINCT f.MEMBER_HK) as covered_members,
      ROUND(SUM(f.SUM_ASSURED), 2) as total_sum_assured
  FROM scbi_cdp_mart.cnf__fact_member_risk_cover f
  JOIN scbi_cdp_mart.cnf__dim_risk_product rp ON f.PRODUCT_HK = rp.PRODUCT_HK
  JOIN scbi_cdp_mart.cnf__dim_member m ON f.MEMBER_HK = m.MEMBER_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_client c ON f.CLIENT_HK = c.CLIENT_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_client_name IS NULL OR c.CLIENT_NAME = :selected_client_name)
  GROUP BY 1, 2
  ORDER BY 4 DESC
  LIMIT 10;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": ["MemberRiskCover.totalSumAssured", "MemberRiskCover.coveredMembers"],
    "dimensions": ["DimRiskProduct.productName", "DimMember.memberGender"],
    "filters": [
      { "member": "MemberRiskCover.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ],
    "order": { "MemberRiskCover.totalSumAssured": "desc" },
    "limit": 10
  }
  ```

---

## 7. Sprint 3: Fund Analytics - Investment Analysis — KPIs & 5 Sub-Pages

### User Story 3.1: Market Value & Risk Profile Headline KPIs
* **User Story**:
  > *As an Investment Portfolio Manager, I want to see Total Market Value, Total Funds, and Portfolio Count calculated from `InvestmentsFundamental` in `scbi-cube`, parameterized by the active slicers.*
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name, :selected_client_name, :selected_employer_name
  SELECT 
      ROUND(SUM(f.MARKET_VALUE), 2) as total_market_value,
      COUNT(DISTINCT f.FUND_HK) as fund_count,
      COUNT(DISTINCT f.PORTFOLIO_HK) as portfolio_count
  FROM scbi_cdp_mart.cnf__fact_inv_monthly_market_value f
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name);
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": ["InvestmentsFundamental.totalMarketValue"],
    "dimensions": ["DimFund.fundName"],
    "filters": [
      { "member": "InvestmentsFundamental.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ]
  }
  ```
* **Acceptance Test**: Total Market Value currency string matches ground truth SQL sum to 2 decimal places.

---

### User Story 3.2: Page 1 — Portfolio Allocation & Risk Category Breakdown
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name
  SELECT 
      f.RISK_METER as risk_category,
      f.PORTFOLIO_NAME,
      ROUND(SUM(f.AUA_AMOUNT), 2) as total_aua,
      COUNT(DISTINCT f.MEMBER_HK) as member_count
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
  GROUP BY 1, 2
  ORDER BY 3 DESC;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": ["MemberMonthlyInvestment.totalAua", "MemberMonthlyInvestment.distinctMembers"],
    "dimensions": ["MemberMonthlyInvestment.riskMeter", "MemberMonthlyInvestment.portfolioName"],
    "filters": [
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ],
    "order": { "MemberMonthlyInvestment.totalAua": "desc" }
  }
  ```

---

### User Story 3.3: Page 2 — Member Choice Exercised vs Default Allocation
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name, :selected_employer_name
  SELECT 
      COALESCE(f.INVESTMENT_CHOICE_INDICATOR, 'Default') as choice_indicator,
      COUNT(DISTINCT f.MEMBER_HK) as member_count,
      ROUND(SUM(f.AUA_AMOUNT), 2) as total_aua
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_employer_name IS NULL OR e.EMPLOYER_NAME = :selected_employer_name)
  GROUP BY 1;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": ["MemberMonthlyInvestment.distinctMembers", "MemberMonthlyInvestment.totalAua"],
    "dimensions": ["MemberMonthlyInvestment.investmentChoiceIndicator"],
    "filters": [
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ]
  }
  ```

---

### User Story 3.4: Page 3 — Risk Category Matrix by Age Band
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name
  SELECT 
      m.MEMBER_AGE_BAND,
      f.RISK_METER,
      COUNT(DISTINCT f.MEMBER_HK) as member_count,
      ROUND(SUM(f.AUA_AMOUNT), 2) as total_aua
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  JOIN scbi_cdp_mart.cnf__dim_member m ON f.MEMBER_HK = m.MEMBER_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
  GROUP BY 1, 2
  ORDER BY 1, 2;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": ["MemberMonthlyInvestment.totalAua", "MemberMonthlyInvestment.distinctMembers"],
    "dimensions": ["DimMember.memberAgeBand", "MemberMonthlyInvestment.riskMeter"],
    "filters": [
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ]
  }
  ```

---

### User Story 3.5: Page 4 — Live Portfolio Holdings Ledger
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name, :selected_employer_name
  SELECT 
      f.PORTFOLIO_NAME,
      f.RISK_METER,
      COUNT(DISTINCT f.MEMBER_HK) as active_members,
      ROUND(SUM(f.AUA_AMOUNT), 2) as total_aua,
      ROUND(AVG(f.AUA_AMOUNT), 2) as avg_aua
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  LEFT JOIN scbi_cdp_mart.cnf__dim_employer e ON f.EMPLOYER_HK = e.EMPLOYER_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
    AND (:selected_employer_name IS NULL OR e.EMPLOYER_NAME = :selected_employer_name)
  GROUP BY 1, 2
  ORDER BY 4 DESC;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": [
      "MemberMonthlyInvestment.totalAua",
      "MemberMonthlyInvestment.distinctMembers",
      "MemberMonthlyInvestment.avgAua"
    ],
    "dimensions": ["MemberMonthlyInvestment.portfolioName", "MemberMonthlyInvestment.riskMeter"],
    "filters": [
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ],
    "order": { "MemberMonthlyInvestment.totalAua": "desc" }
  }
  ```

---

### User Story 3.6: Page 5 — Pensionable Service Years Distribution
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters: :selected_date_sk, :selected_fund_name
  SELECT 
      f.PENSIONABLE_SERVICE_BAND,
      COUNT(DISTINCT f.MEMBER_HK) as member_count,
      ROUND(SUM(f.AUA_AMOUNT), 2) as total_aua
  FROM scbi_cdp_mart.cnf__fact_member_investment_aua f
  LEFT JOIN scbi_cdp_mart.cnf__dim_fund fd ON f.FUND_HK = fd.FUND_HK
  WHERE (:selected_date_sk IS NULL OR f.DATE_SK = :selected_date_sk)
    AND (:selected_fund_name IS NULL OR fd.FUND_NAME = :selected_fund_name)
  GROUP BY 1
  ORDER BY 1;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": ["MemberMonthlyInvestment.distinctMembers", "MemberMonthlyInvestment.totalAua"],
    "dimensions": ["MemberMonthlyInvestment.pensionableServiceBand"],
    "filters": [
      { "member": "MemberMonthly.dateSk", "operator": "equals", "values": [":selected_date_sk"] },
      { "member": "DimFund.fundName", "operator": "equals", "values": [":selected_fund_name"] }
    ]
  }
  ```

---

## 8. Sprint 4: Life Annuity Reporting (Quotes & Acceptances)

### User Story 4.1: Timeline & Conversion Rates (Page 1)
* **Ground Truth Recon SQL (Parameterized)**:
  ```sql
  -- Parameters fed from UI filter state:
  -- :selected_brokerage, :selected_consultant, :selected_date_from, :selected_date_to
  SELECT 
      f.DATE_NK,
      COUNT(DISTINCT f.QUOTATION_NUMBER) as quotation_count,
      COUNT(DISTINCT CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_NUMBER END) as accepted_count,
      ROUND(SUM(f.QUOTATION_PURCHASE_PRICE), 2) as quoted_price,
      ROUND(SUM(CASE WHEN LOWER(f.DERIVED_QUOTATION_STATUS) = 'quoted and accepted' THEN f.QUOTATION_PURCHASE_PRICE ELSE 0 END), 2) as accepted_price
  FROM scbi_cdp_mart.cnf__fact_annuity_quotations f
  LEFT JOIN scbi_cdp_mart.cnf__dim_broker_consultant bc ON f.QUOTED_BROKER_CONSULTANT_HK = bc.BROKER_CONSULTANT_HK
  WHERE f.DERIVED_QUOTATION_STATUS <> 'Accepted'
    AND NOT (f.DERIVED_QUOTATION_TYPE = 'Bulk' AND f.SOURCE = 'online')
    AND (:selected_brokerage IS NULL OR bc.BROKER_CONSULTANT_BROKERAGE = :selected_brokerage)
    AND (:selected_consultant IS NULL OR bc.BROKER_CONSULTANT_NAME = :selected_consultant)
    AND (:selected_date_from IS NULL OR f.DATE_NK >= :selected_date_from)
    AND (:selected_date_to IS NULL OR f.DATE_NK <= :selected_date_to)
  GROUP BY 1
  ORDER BY 1 DESC
  LIMIT 20;
  ```
* **Cube.js API Payload (Parameterized)**:
  ```json
  {
    "measures": [
      "AnnuityQuotation.quotationCount",
      "AnnuityQuotation.acceptedQuotations",
      "AnnuityQuotation.quotedPurchasePrice",
      "AnnuityQuotation.acceptedPurchasePrice",
      "AnnuityQuotation.memberConversionRate"
    ],
    "dimensions": ["AnnuityQuotation.dateNk"],
    "filters": [
      { "member": "DimBrokerConsultant.brokerConsultantBrokerage", "operator": "equals", "values": [":selected_brokerage"] },
      { "member": "AnnuityQuotation.dateNk", "operator": "gte", "values": [":selected_date_from"] },
      { "member": "AnnuityQuotation.dateNk", "operator": "lte", "values": [":selected_date_to"] }
    ],
    "order": { "AnnuityQuotation.dateNk": "desc" },
    "limit": 20
  }
  ```
* **Acceptance Test**: Verify timeline graph and KPI cards match the SQL result set under active date and brokerage filters.

### User Story 4.2: Pages 2–10 Migration
* All remaining Life Annuity sub-pages (YTD Figures, Top Consultants, Price Distribution, Consultant Details, Detailed Ledger, Alexforbes, Graviton, DC New Business, and Business Summary) consume the `AnnuityQuotation` cube with parameters dynamically bound from the UI slicer state.

---

## 9. Sprint 5: Automated Testing Suite & Enterprise APM

### User Story 5.1: Automated Parameterized Matrix Regression Suite (`test_cube_recon.py`)
* **User Story**:
  > *As a DevOps QA Engineer, I want an automated test harness that executes reconciliation tests across a matrix of filter parameter combinations (Unfiltered, Date Only, Date + Fund, Date + Fund + Client, Fully Qualified Slice), asserting 100% numerical match with Lakehouse Marts.*
* **Test Matrix Configuration**:
  ```python
  TEST_FILTER_COMBINATIONS = [
      {"name": "Unfiltered / Global"},
      {"name": "Date Snapshot Only", "dateSk": 20251231},
      {"name": "Date + Umbrella Classification", "dateSk": 20251231, "businessUnit": "Sanlam Umbrella Fund"},
      {"name": "Date + Specific Fund", "dateSk": 20251231, "fundName": "Sanlam Umbrella Pension Fund"},
      {"name": "Date + Fund + Client", "dateSk": 20251231, "fundName": "Sanlam Umbrella Pension Fund", "clientName": "Controlled Irrigation CC"},
  ]
  ```
* **Quality Gate**: Every combination executes against Lakehouse Marts in DuckDB and against `scbi-cube` REST API; maximum allowable numerical variance: `0.00%`.

### User Story 5.2: Thin Client APM & LLM Diagnostic Exporter
* Migrates the SysAdmin Cockpit into `thin-web-app`:
  * Displays Cloud Run container ping to `scbi-cube`.
  * Monitors API latency ($p50, p95, p99$) and cache hit ratios.
  * One-click LLM Diagnostic Bundle export directly formatting Cube.js operational metrics and query traces.

---

## 10. Quality Gate & Acceptance Checklist

Before any sprint is signed off, the following checklist must be satisfied:
- [x] No local DuckDB instances running inside the web application.
- [x] Zero GCS access keys or credentials located in client-side code.
- [x] **Zero Hardcoded WHERE Clauses**: Every query dynamically parameterized by the active UI filter state (`SlicerParams`).
- [x] All 8 slicers dynamically populated from Cube.js with debounced cascading sync.
- [x] Ground truth SQL test query passed for every KPI, card, and chart visual under active parameters.
- [x] Preserved identical visual look, feel, animations, and typography.
- [x] Automated parameterized regression suite passes with 0 failures.
