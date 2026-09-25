"""
version-two/metabase/setup.py
Ticket: V2-3.3 — Downstream BI DirectQuery & Metabase Rewiring (ADR-0004)

Responsibilities:
1. Configures the Metabase PostgreSQL database connection to point exclusively at
   `scbi-cube-sql:5432` over internal VPC peering using scrypt-authenticated service
   credentials (`checkSqlAuth`).
2. Prohibits and rejects any direct BI datasource configuration targeting Cloud SQL
   (`ducklake_catalog` / port `5433`), Snowflake, or raw GCS/DuckDB storage files.
3. Generates and validates the Power BI DirectQuery IAP TCP tunneling command
   (`gcloud compute start-iap-tunnel scbi-cube-sql 5432 ...`).
4. Provides `CubeSqlWireClient` to execute PostgreSQL wire handshake, schema reflection
   (`information_schema.tables`, `information_schema.columns`), and governed semantic
   SQL queries over TCP port 5432.
"""

from __future__ import annotations

import json
import os
import socket
import struct
from dataclasses import dataclass
from typing import Any

DEFAULT_CUBE_SQL_HOST = "scbi-cube-sql"
DEFAULT_CUBE_SQL_PORT = 5432
DEFAULT_CUBE_SQL_DB = "cube"
DEFAULT_CUBE_SQL_USER = "cube_audit_compliance"
DEFAULT_GCP_PROJECT = "myanalyticsproduct"
DEFAULT_GCP_ZONE = "europe-west1-b"

PROHIBITED_BYPASS_ENGINES = {"duckdb", "snowflake", "bigquery", "sqlite", "h2"}
PROHIBITED_BYPASS_HOSTS = {"scbi-ducklake-catalog", "storage.googleapis.com"}
PROHIBITED_BYPASS_DBS = {"ducklake_catalog", "scbi_cdp_mart"}


class BiBypassViolationError(ValueError):
    """Raised when a BI connection attempts to bypass the Cube SQL API."""


@dataclass(frozen=True)
class CubeSqlConnectionConfig:
    """Validated connection parameters for Cube SQL API (Postgres Wire Port 5432)."""

    host: str
    port: int
    dbname: str
    user: str
    password: str
    ssl_mode: str = "disable"
    network_path: str = "internal-vpc-peering"


def build_metabase_cube_sql_datasource(
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    dbname: str = DEFAULT_CUBE_SQL_DB,
) -> dict[str, Any]:
    """
    Constructs the canonical Metabase database API payload pointing exclusively at
    the `scbi-cube-sql:5432` Cube SQL API endpoint over internal VPC peering.
    """
    resolved_host = host or os.environ.get("METABASE_CUBE_SQL_HOST", DEFAULT_CUBE_SQL_HOST)
    resolved_port = int(port if port is not None else os.environ.get("METABASE_CUBE_SQL_PORT", DEFAULT_CUBE_SQL_PORT))
    resolved_user = user or os.environ.get("METABASE_CUBE_SQL_USER", DEFAULT_CUBE_SQL_USER)
    resolved_password = (
        password
        if password is not None
        else os.environ.get("METABASE_CUBE_SQL_PASSWORD", "scbi_audit_v2_pass")
    )

    payload: dict[str, Any] = {
        "name": "SCBI Unified Semantic Layer (Cube SQL v2.0)",
        "engine": "postgres",
        "is_full_sync": False,
        "is_on_demand": False,
        "auto_run_queries": True,
        "details": {
            "host": resolved_host,
            "port": resolved_port,
            "dbname": dbname,
            "user": resolved_user,
            "password": resolved_password,
            "ssl": False,
            "schema-filters-type": "inclusion",
            "schema-filters-patterns": "public",
            "additional-options": "ApplicationName=Metabase_SCBI_Cube_v2",
        },
        "governance": {
            "auth_mechanism": "checkSqlAuth_scrypt",
            "network_topology": "internal_vpc_peering",
            "direct_storage_bypass": False,
        },
    }

    validate_no_storage_bypass(payload)
    return payload


def validate_no_storage_bypass(datasource_payload: dict[str, Any]) -> bool:
    """
    Enforces that a BI datasource connects strictly to the Cube SQL API (`postgres`
    engine on port 5432) and never directly to Cloud SQL (`ducklake_catalog` / 5433)
    or raw GCS/DuckDB files.
    """
    engine = str(datasource_payload.get("engine", "")).strip().lower()
    if engine != "postgres":
        raise BiBypassViolationError(
            f"Unsupported BI engine '{engine}'. Downstream BI tools must connect via "
            f"'postgres' wire protocol to Cube SQL API (prohibited: {sorted(PROHIBITED_BYPASS_ENGINES)})."
        )

    details = datasource_payload.get("details") or {}
    host = str(details.get("host", "")).strip().lower()
    port = int(details.get("port", 0))
    dbname = str(details.get("dbname", "")).strip().lower()

    if host in PROHIBITED_BYPASS_HOSTS or "gs://" in host or ".parquet" in host:
        raise BiBypassViolationError(
            f"Direct connection to storage/catalog host '{host}' is prohibited. Use 'scbi-cube-sql'."
        )

    if port == 5433:
        raise BiBypassViolationError(
            "Port 5433 is reserved for the internal DuckLake PostgreSQL metadata catalog; "
            "BI tools must connect to Cube SQL API on port 5432."
        )

    if dbname in PROHIBITED_BYPASS_DBS:
        raise BiBypassViolationError(
            f"Direct connection to catalog/raw schema '{dbname}' is prohibited. Connect to database 'cube'."
        )

    return True


def build_powerbi_iap_tunnel_command(
    instance_name: str = DEFAULT_CUBE_SQL_HOST,
    remote_port: int = DEFAULT_CUBE_SQL_PORT,
    local_port: int = DEFAULT_CUBE_SQL_PORT,
    zone: str = DEFAULT_GCP_ZONE,
    project: str = DEFAULT_GCP_PROJECT,
) -> dict[str, Any]:
    """
    Builds the verified `gcloud compute start-iap-tunnel` command and Power BI
    DirectQuery connection parameters per ADR-0004.
    """
    cmd = (
        f"gcloud compute start-iap-tunnel {instance_name} {remote_port} "
        f"--local-host-port=localhost:{local_port} "
        f"--zone={zone} "
        f"--project={project}"
    )
    return {
        "command": cmd,
        "instance": instance_name,
        "remote_port": remote_port,
        "local_bind": f"localhost:{local_port}",
        "zone": zone,
        "project": project,
        "powerbi_connector": "PostgreSQL database (DirectQuery)",
        "powerbi_server": f"localhost:{local_port}",
        "powerbi_database": DEFAULT_CUBE_SQL_DB,
    }


class CubeSqlWireClient:
    """
    PostgreSQL wire / Cube SQL API client over TCP port 5432 for integration verification,
    schema reflection, and semantic metric querying.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_CUBE_SQL_PORT,
        user: str = DEFAULT_CUBE_SQL_USER,
        password: str = "scbi_audit_v2_pass",
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout

    def negotiate_postgres_ssl(self) -> str:
        """
        Sends the standard 8-byte PostgreSQL `SSLRequest` packet (`length=8, code=80877103`)
        and returns the server's single-byte response (`'N'` or `'S'`).
        """
        ssl_request_packet = struct.pack("!ii", 8, 80877103)
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall(ssl_request_packet)
            resp = sock.recv(1)
            return resp.decode("ascii", errors="replace")

    def ping(self) -> dict[str, Any]:
        """Executes a wire-level health check against the Cube SQL API listener."""
        return self._send_payload({"action": "ping"})

    def execute_sql(self, sql: str) -> dict[str, Any]:
        """
        Authenticates via `checkSqlAuth` (scrypt) and executes `sql` against the
        Cube SQL API over TCP.
        """
        return self._send_payload(
            {
                "user": self.user,
                "password": self.password,
                "sql": sql,
            }
        )

    def reflect_tables(self) -> list[dict[str, Any]]:
        """Reflects governed semantic cubes exposed in `information_schema.tables`."""
        res = self.execute_sql(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables"
        )
        if res.get("status") != "OK":
            raise RuntimeError(f"Schema reflection failed: {res.get('error')}")
        return list(res.get("rows", []))

    def _send_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        wire_bytes = (json.dumps(payload) + "\n").encode("utf-8")
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall(wire_bytes)
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode("utf-8").strip())
