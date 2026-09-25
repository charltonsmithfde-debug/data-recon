# Downstream BI DirectQuery & Metabase Connection Guide (Cube SQL API v2.0)

| | |
|---|---|
| **Ticket** | [V2-3.3](tickets/V2-3.3-downstream-bi-rewire.md) |
| **Architecture Reference** | [ADR-0004: Dual Delivery Topologies](adr/0004-dual-delivery-topologies.md) |
| **Security Reference** | [ADR-0003: JWT RBAC & POPIA Masking](adr/0003-jwt-rbac-popia-masking.md) |
| **Target Endpoint** | `scbi-cube-sql:5432` (PostgreSQL v3 Wire Protocol) |

---

## 1. Architectural Invariant: Zero Storage Bypass

In Version 2.0, **Metabase** and **Power BI DirectQuery** are strictly prohibited from connecting directly to:
- Cloud SQL (`scbi-ducklake-catalog` on port `5433` / database `ducklake_catalog`)
- Raw Google Cloud Storage Parquet files (`gs://scbi-ducklake-myanalyticsproduct/...`)
- Legacy Snowflake or local embedded DuckDB files

All downstream BI queries must traverse the **Cube.js 1.7.x SQL API** (`CUBEJS_PG_SQL_PORT=5432`) running on the internal GCE VM `scbi-cube-sql`. This guarantees 100% metric calculation parity with the Thin Web Portal and enforces server-side RBAC + POPIA SHA-256 PII masking on every query.

---

## 2. Metabase Connection Procedure (Internal VPC Peering)

Metabase connects to `scbi-cube-sql` over internal Google Cloud VPC peering without traversing the public internet.

### Connection Parameters
| Setting | Value |
|---|---|
| **Display Name** | `SCBI Unified Semantic Layer (Cube SQL v2.0)` |
| **Database Type** | `PostgreSQL` (`postgres`) |
| **Host** | `scbi-cube-sql` (internal VPC DNS / internal IP) |
| **Port** | `5432` |
| **Database Name** | `cube` |
| **Username** | Role-mapped service user (e.g., `cube_audit_compliance`, `cube_annuity_analyst`, `cube_finance_member`) |
| **Password** | Provisioned in Secret Manager and verified via `scrypt` (`checkSqlAuth`) |
| **Schemas** | `public` |

### Automated Provisioning & Validation
Use [`version-two/metabase/setup.py`](../version-two/metabase/setup.py) to generate and validate the Metabase datasource configuration:

```bash
python3 -c "from version_two.metabase.setup import build_metabase_cube_sql_datasource; print(build_metabase_cube_sql_datasource())"
```

---

## 3. Power BI DirectQuery Procedure (Google Cloud IAP TCP Tunnel)

Because `scbi-cube-sql` has **no external public IP**, corporate analysts authoring Power BI DirectQuery reports connect through an encrypted Identity-Aware Proxy (IAP) TCP tunnel.

### Step 1: Authenticate with Google Cloud SDK
```bash
gcloud auth login
gcloud config set project myanalyticsproduct
```

### Step 2: Start the Encrypted IAP TCP Tunnel to Port 5432
```bash
gcloud compute start-iap-tunnel scbi-cube-sql 5432 \
  --local-host-port=localhost:5432 \
  --zone=europe-west1-b \
  --project=myanalyticsproduct
```

### Step 3: Connect Power BI Desktop (DirectQuery Mode)
1. Open **Power BI Desktop** -> **Get Data** -> **PostgreSQL database**.
2. Set **Server** to `localhost:5432` and **Database** to `cube`.
3. Select **Data Connectivity mode**: **DirectQuery**.
4. Enter your role-assigned Cube SQL username and password (`cube_annuity_analyst`, `cube_finance_member`, etc.).
5. Select from the governed semantic Cubes exposed under the `public` schema:
   - `AnnuityQuotation`
   - `InvestmentAnalysis`
   - `MemberAnalysis`
   - `SharedDimensions` (`DimDate`, `DimMember`, `DimScheme`, `DimFund`)

---

## 4. Governed SQL Query Examples

```sql
-- 1. Reflect governed semantic Cubes
SELECT table_schema, table_name, table_type
FROM information_schema.tables;

-- 2. Query Annuity Quotation Count via Cube SQL API
SELECT COUNT(*) AS count
FROM AnnuityQuotation;

-- 3. Query Member Analysis AUA & Active Member Count (PII automatically masked for non-PII roles)
SELECT activeMemberCount, totalAua, id_number
FROM MemberAnalysis;
```
