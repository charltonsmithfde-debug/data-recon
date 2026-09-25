# ADR 0004 — Dual Delivery Topologies from a Single Container Image

| | |
|---|---|
| **Status** | **Accepted** |
| **Date** | 2026-09-25 |
| **Deciders** | Platform Architecture, Data Engineering, DevOps |
| **Story** | US-8.1, US-8.3 (PRD Epic 3) |
| **Supersedes** | None |
| **Affects** | `version-two/cube/`, `version-two/infra/`, Cloud Run deployment, GCE VM deployment |

---

## 1. Context

Downstream consumers of business metrics have fundamentally different interface and networking requirements:
1. **The Custom Thin Web Portal** is a web application that interacts natively via HTTP/JSON REST or GraphQL APIs, requiring serverless autoscaling, rapid scale-from-zero, and simple integration with Google Identity-Aware Proxy (IAP).
2. **Business Intelligence Tools (Power BI DirectQuery and Metabase)** communicate strictly over the PostgreSQL wire protocol (TCP port 5432). Power BI DirectQuery maintains persistent TCP connections and issues high-frequency metadata discovery queries (`pg_catalog`, `information_schema`) that cannot be handled by standard HTTP request/response lifecycles.

Google Cloud Run is an ideal runtime for HTTP workloads, but has severe limitations for raw TCP services:
- Cloud Run cannot bind arbitrary TCP ports without an HTTP/h2c handshake or WebSocket encapsulation.
- Serverless request timeouts and container autoscaling disrupt long-lived BI analyst sessions and DirectQuery connections.
- Cloud Run does not support native direct TCP forwarding through Google Cloud IAP without third-party proxies.

Conversely, running the entire platform on a single monolithic VM forfeits the horizontal autoscaling, managed zero-downtime rollouts, and zero-maintenance benefits of Cloud Run for the web portal.

---

## 2. Decision

We adopt a **Dual Delivery Architecture powered by a Single Container Image**:

1. **Single Artifact Principle**:
   - We author and build a single Docker image: `scbi-cube:2.0`.
   - This container encapsulates Cube.js 1.7.x, the embedded DuckDB analytics engine (`@duckdb/node-api`), the DuckLake catalog connector, and the complete semantic schema definitions (`model/*.js`).
   - Guarantee: Both delivery runtimes run the exact same commit, the exact same metric logic, and the exact same security models.

2. **Cloud Run Deployment (REST Interface)**:
   - Deployed as `scbi-cube` on Google Cloud Run listening on port 4000 (HTTP).
   - Mode: `CUBEJS_REST_API=true`, `CUBEJS_PG_SQL_PORT=false`.
   - Scaled automatically between min-instances: 1 and max-instances: 10.
   - Consumed exclusively by the Thin Web Portal backend.

3. **Compute Engine VM Deployment (SQL API Interface)**:
   - Deployed on a dedicated Google Compute Engine VM (`scbi-cube-sql`, `e2-standard-4`, Debian 12) running the same container via `systemd`.
   - Mode: `CUBEJS_PG_SQL_PORT=5432`.
   - Network Boundary: No external public IP. Bound to the internal VPC.
   - Access: Metabase connects via internal VPC peering. Power BI analysts connect through Google Cloud IAP TCP tunneling (`gcloud compute start-iap-tunnel scbi-cube-sql 5432`).

---

## 3. Consequences

### Positive
- **Guaranteed Metric Parity**: Because both endpoints execute against the identical semantic model repository and in-process DuckDB logic, calculation divergence between the Web App and Power BI is eliminated by construction.
- **Optimized Compute Economics**: The web portal benefits from cheap, autoscaled serverless execution, while BI tools receive uninterrupted, predictable TCP connections on a dedicated VM without idle connection drops.
- **Maintainability**: A single codebase and CI/CD build pipeline produces one image deployed to two targets via environmental flags.

### Negative / Trade-Offs
- **Two Deployment Targets**: CI/CD must trigger both a Cloud Run update and a VM container restart.
- **VM Maintenance**: The GCE VM requires standard OS maintenance (managed via automated patching or Google OS Config).

---

## 4. Alternatives Considered

1. **Monolithic GCE VM for All Workloads**:
   - *Rejected*: Gives up Cloud Run auto-scaling and serverless reliability for the public portal; web spikes could starve analyst BI queries.
2. **Cloud Run with WebSocket/TCP Proxy Wrappers for Power BI**:
   - *Rejected*: Power BI DirectQuery does not support custom WebSocket tunneling without intrusive client-side proxy software installed on corporate analyst machines. Standard IAP TCP forwarding requires a GCE VM target.
3. **Separate Microservices (One for REST, One for SQL)**:
   - *Rejected*: Diverges schemas over time, recreating the very metric drift this architecture was designed to eliminate.
