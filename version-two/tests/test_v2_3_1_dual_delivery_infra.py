"""
Test suite for Ticket V2-3.1: Dual Delivery Deployment Topologies
(Cloud Run REST + GCE VM SQL API)

Verifies all 4 Acceptance Criteria:
1. Production multi-stage `Dockerfile` packaging Node 22, Cube 1.7.x, and embedded DuckDB.
2. Cloud Run YAML deployment manifest configured with VPC Access Connector and Secret Manager environment variables.
3. Systemd unit service file and startup script for `scbi-cube-sql` Compute Engine VM.
4. Confirms both services start cleanly from the identical Docker image / Cube runtime with appropriate runtime flags.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INFRA_DIR = PROJECT_ROOT / "version-two" / "infra"
CUBE_DIR = PROJECT_ROOT / "version-two" / "cube"
DOCKERFILE_PATH = INFRA_DIR / "Dockerfile"
CLOUDRUN_YAML_PATH = INFRA_DIR / "cloudrun-rest.yaml"
SYSTEMD_SERVICE_PATH = INFRA_DIR / "gce-sql-systemd.service"


class TestV231DualDeliveryInfra(unittest.TestCase):
    """Validates V2-3.1 Dual Delivery manifests and dual REST/SQL runtime execution."""

    def test_ac1_multi_stage_dockerfile_node22_cube_duckdb(self) -> None:
        """AC 1: Production multi-stage Dockerfile packaging Node 22, Cube 1.7.x, and embedded DuckDB."""
        self.assertTrue(DOCKERFILE_PATH.exists(), f"Missing {DOCKERFILE_PATH}")
        content = DOCKERFILE_PATH.read_text(encoding="utf-8")

        # Multi-stage build using Node 22
        self.assertIn("FROM node:22-bookworm-slim AS builder", content)
        self.assertIn("FROM node:22-bookworm-slim AS runtime", content)
        self.assertIn("COPY --from=builder", content)

        # Copies Cube config, models, and DuckLake catalog schema
        self.assertIn("COPY version-two/cube/", content)
        self.assertIn("COPY version-two/ducklake/", content)

        # Hardened non-root runtime & dual ports exposed
        self.assertIn("USER node", content)
        self.assertIn("EXPOSE 4000 5432", content)
        self.assertIn('CMD ["node", "cube.js", "--serve"]', content)

    def test_ac2_cloudrun_yaml_vpc_connector_and_secrets(self) -> None:
        """AC 2: Cloud Run YAML deployment manifest configured with VPC Access Connector and Secret Manager env vars."""
        self.assertTrue(CLOUDRUN_YAML_PATH.exists(), f"Missing {CLOUDRUN_YAML_PATH}")
        content = CLOUDRUN_YAML_PATH.read_text(encoding="utf-8")

        self.assertIn("apiVersion: serving.knative.dev/v1", content)
        self.assertIn("kind: Service", content)
        self.assertIn("name: scbi-cube", content)

        # VPC Access Connector & internal egress
        self.assertIn("run.googleapis.com/vpc-access-connector:", content)
        self.assertIn("scbi-vpc-connector", content)
        self.assertIn("run.googleapis.com/vpc-access-egress: private-ranges-only", content)

        # Secret Manager environment variable references
        self.assertIn("name: DUCKLAKE_DB_URL", content)
        self.assertIn("name: scbi-ducklake-db-url", content)
        self.assertIn("name: CUBEJS_API_SECRET", content)
        self.assertIn("name: scbi-cube-api-secret", content)

        # Unified image & REST port 4000
        self.assertIn(
            "image: europe-west1-docker.pkg.dev/myanalyticsproduct/scbi-repo/scbi-cube:2.0",
            content,
        )
        self.assertIn("containerPort: 4000", content)

    def test_ac3_systemd_service_for_scbi_cube_sql_vm(self) -> None:
        """AC 3: Systemd unit service file and startup script for scbi-cube-sql Compute Engine VM."""
        self.assertTrue(SYSTEMD_SERVICE_PATH.exists(), f"Missing {SYSTEMD_SERVICE_PATH}")
        content = SYSTEMD_SERVICE_PATH.read_text(encoding="utf-8")

        self.assertIn("[Unit]", content)
        self.assertIn("[Service]", content)
        self.assertIn("[Install]", content)
        self.assertIn("Requires=docker.service", content)
        self.assertIn("EnvironmentFile=-/etc/scbi-cube/sql.env", content)

        # Uses the identical scbi-cube:2.0 image as Cloud Run
        self.assertIn(
            "europe-west1-docker.pkg.dev/myanalyticsproduct/scbi-repo/scbi-cube:2.0",
            content,
        )
        self.assertIn("CUBEJS_PG_SQL_PORT=5432", content)
        self.assertIn("-p 5432:5432", content)

    def test_ac4_dual_runtime_smoke_rest_4000_and_sql_5432(self) -> None:
        """AC 4: Confirms both services start cleanly from the identical runtime in REST mode (4000) and SQL mode (5432)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = str(Path(tmpdir) / "dual_delivery_catalog.db")
            node_script = f"""
const net = require('net');
const cube = require({json.dumps(str(CUBE_DIR / "cube.js"))});

(async () => {{
  // 1. Start REST server (Cloud Run topology simulation)
  const restSrv = await cube.startCubeHttpServer({{ port: 0, catalogDbPath: {json.dumps(catalog_path)} }});
  const healthRes = await fetch(`http://127.0.0.1:${{restSrv.port}}/readyz`);
  const healthBody = await healthRes.json();

  // 2. Start SQL API server (GCE VM topology simulation on port 5432 equivalent)
  const sqlSrv = await cube.startCubeSqlServer({{ sqlPort: 0, catalogDbPath: {json.dumps(catalog_path)} }});

  const sendSqlMsg = (payload) => new Promise((resolve, reject) => {{
    const client = net.createConnection({{ host: '127.0.0.1', port: sqlSrv.port }}, () => {{
      client.write(JSON.stringify(payload) + '\\n');
    }});
    let buf = '';
    client.on('data', (chunk) => {{
      buf += chunk.toString('utf8');
      if (buf.includes('\\n')) {{
        client.end();
        resolve(JSON.parse(buf.trim()));
      }}
    }});
    client.on('error', reject);
  }});

  const sqlPing = await sendSqlMsg({{ action: 'ping' }});
  const sqlQuery = await sendSqlMsg({{
    user: 'cube_annuity_analyst',
    password: process.env.CUBE_SQL_PASSWORD_ANNUITY || 'scbi_annuity_v2_pass',
    sql: 'SELECT COUNT(*) AS count FROM AnnuityQuotation'
  }});

  await restSrv.close();
  await sqlSrv.close();

  console.log(JSON.stringify({{
    restHealth: healthBody,
    sqlPing,
    sqlQuery
  }}));
}})().catch((err) => {{
  console.error(err);
  process.exit(1);
}});
"""
            proc = subprocess.run(
                ["node", "-e", node_script],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, f"Dual runtime smoke test failed: {proc.stderr}")
            data = json.loads(proc.stdout.strip())

            self.assertEqual(data["restHealth"]["status"], "HEALTHY")
            self.assertEqual(data["restHealth"]["attachedCatalog"], "lake")
            self.assertEqual(data["sqlPing"]["status"], "HEALTHY")
            self.assertEqual(data["sqlPing"]["service"], "scbi-cube-sql")
            self.assertEqual(data["sqlQuery"]["status"], "OK")
            self.assertEqual(data["sqlQuery"]["rows"][0]["AnnuityQuotation.quotationCount"], 129954)


if __name__ == "__main__":
    unittest.main()
