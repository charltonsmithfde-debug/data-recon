# ==============================================================================
# version-two/infra/Dockerfile
# Ticket: V2-3.1 — Dual Delivery Deployment Topologies (ADR-0004)
#
# Single Artifact Principle (scbi-cube:2.0):
# Multi-stage production Dockerfile packaging Node 22, Cube.js 1.7.x, and
# embedded DuckDB (@duckdb/node-api) to serve:
#   1. Google Cloud Run REST API (Port 4000)
#   2. Google Compute Engine VM SQL API (Postgres Wire Protocol Port 5432)
# ==============================================================================

# Stage 1: Dependency Builder
FROM node:22-bookworm-slim AS builder

WORKDIR /build/version-two/cube

COPY version-two/cube/package.json ./
RUN npm install --omit=dev --no-audit --no-fund

# Stage 2: Hardened Production Runtime
FROM node:22-bookworm-slim AS runtime

LABEL org.opencontainers.image.title="scbi-cube" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.description="Unified Cube.js 1.7.x Semantic Layer with Embedded DuckDB & DuckLake"

WORKDIR /app/version-two/cube

# Copy production node_modules from builder
COPY --from=builder /build/version-two/cube/node_modules ./node_modules

# Copy semantic engine, models, DuckLake catalog schema, and migration metadata
COPY version-two/cube/ /app/version-two/cube/
COPY version-two/ducklake/ /app/version-two/ducklake/
COPY scripts/migration_state.json /app/scripts/migration_state.json
COPY thin-web-app/role_assignments.json /app/thin-web-app/role_assignments.json

ENV NODE_ENV=production \
    CUBEJS_DB_TYPE=duckdb \
    CUBEJS_DEV_MODE=false \
    CUBE_REST_PORT=4000 \
    CUBEJS_PG_SQL_PORT=5432 \
    DUCKDB_MEMORY_LIMIT=3.5GB

# Drop root privileges
USER node

# Port 4000: Cube REST API (Cloud Run)
# Port 5432: Cube SQL API (Postgres Wire Protocol on GCE VM)
EXPOSE 4000 5432

CMD ["node", "cube.js", "--serve"]
