"""
version-two/portal/server.py
Ticket: V2-3.2 — Thin Web Portal Decoupled API Gateway (ADR-0003 & ADR-0004)

Responsibilities:
1. Replaces the monolithic legacy `thin-web-app/server.py` with a modular FastAPI
   router architecture (`APIRouter` + `PortalGatewayApp`).
2. Extracts verified user identity from `X-Goog-Authenticated-User-Email`, rejecting
   unauthenticated requests with HTTP 401.
3. Mints a signed HS256 Cube JWT containing verified `role` and `canViewPii` permissions
   from `role_assignments.json` (ignoring any client-supplied role parameters).
4. Replaces synthetic data endpoints (`handle_member_analysis_query`) with live Cube
   REST API queries (`/cubejs-api/v1/load`).
"""

from __future__ import annotations

import http.server
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from fastapi import APIRouter as FastAPIRouter, FastAPI  # type: ignore
except ImportError:
    FastAPIRouter = None
    FastAPI = None

try:
    from .auth import (
        PortalAuthError,
        VerifiedIdentity,
        mint_cube_jwt,
        resolve_verified_identity,
    )
except ImportError:
    from auth import (  # type: ignore
        PortalAuthError,
        VerifiedIdentity,
        mint_cube_jwt,
        resolve_verified_identity,
    )

DEFAULT_CUBE_URL = "http://127.0.0.1:4000"


@dataclass
class PortalResponse:
    """Normalized HTTP response returned by `PortalGatewayApp` and `PortalTestClient`."""

    status_code: int
    body: dict[str, Any]
    headers: dict[str, str]

    def json(self) -> dict[str, Any]:
        return self.body


class APIRouter:
    """Modular route table compatible with FastAPI's APIRouter decorator interface."""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix.rstrip("/")
        self.routes: dict[tuple[str, str], Callable[..., tuple[int, dict[str, Any]]]] = {}
        self._fastapi_router = FastAPIRouter(prefix=prefix) if FastAPIRouter else None

    def get(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        full_path = f"{self.prefix}{path}" if path != "/" else (self.prefix or "/")

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.routes[("GET", full_path)] = fn
            return fn

        return decorator

    def post(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        full_path = f"{self.prefix}{path}" if path != "/" else (self.prefix or "/")

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.routes[("POST", full_path)] = fn
            return fn

        return decorator


def proxy_cube_load(
    cube_query: dict[str, Any],
    identity: VerifiedIdentity,
    cube_base_url: str | None = None,
    api_secret: str | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, Any], str]:
    """
    Mints a server-signed HS256 JWT for `identity` and proxies `cube_query` to
    Cube REST API (`POST /cubejs-api/v1/load`).
    Returns `(http_status, response_json, minted_jwt)`.
    """
    base_url = (
        cube_base_url
        or os.environ.get("CUBEJS_BASE_URL")
        or os.environ.get("CUBE_API_URL")
        or DEFAULT_CUBE_URL
    ).rstrip("/")

    jwt_token = mint_cube_jwt(identity, secret=api_secret)
    target_url = f"{base_url}/cubejs-api/v1/load"
    payload_bytes = json.dumps({"query": cube_query}).encode("utf-8")

    req = urllib.request.Request(
        target_url,
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {jwt_token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return resp.status, parsed, jwt_token
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_err = json.loads(err_body)
        except json.JSONDecodeError:
            parsed_err = {"error": err_body}
        return exc.code, parsed_err, jwt_token


def handle_member_analysis_query(
    headers: Mapping[str, str],
    query_params: Mapping[str, Any] | None = None,
    cube_base_url: str | None = None,
    roster_path: Path | str | None = None,
    api_secret: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """
    Live replacement for legacy `thin-web-app/server.py:handle_member_analysis_query`.
    1. Authenticates caller strictly via `X-Goog-Authenticated-User-Email` (HTTP 401 on missing).
    2. Resolves role + PII flag from `role_assignments.json` (ignoring any `role` in `query_params`).
    3. Mints signed HS256 JWT and executes live query against `MemberAnalysis` on Cube REST API.
    4. Never fabricates synthetic numbers (`data_source="cube_rest_live"`, `demo_data=False`).
    """
    identity = resolve_verified_identity(headers, roster_path=roster_path)

    cube_query: dict[str, Any] = {
        "measures": [
            "MemberAnalysis.activeMemberCount",
            "MemberAnalysis.totalAua",
            "MemberAnalysis.avgAua",
        ],
        "dimensions": [
            "MemberAnalysis.memberGender",
            "MemberAnalysis.member_age",
            "MemberAnalysis.id_number",
        ],
    }

    status_code, cube_payload, minted_jwt = proxy_cube_load(
        cube_query=cube_query,
        identity=identity,
        cube_base_url=cube_base_url,
        api_secret=api_secret,
    )

    if status_code != 200:
        return status_code, {
            "status": "ERROR",
            "role": identity.role,
            "can_view_pii": identity.can_view_pii,
            "error": cube_payload.get("error", "Upstream Cube REST API error"),
        }

    rows = cube_payload.get("data", [])
    first_row = rows[0] if rows else {}
    active_members = int(first_row.get("MemberAnalysis.activeMemberCount", 0))
    total_aua = float(first_row.get("MemberAnalysis.totalAua", 0.0))
    avg_aua = float(first_row.get("MemberAnalysis.avgAua", 0.0))

    return 200, {
        "status": "OK",
        "data_source": "cube_rest_live",
        "demo_data": False,
        "email": identity.email,
        "role": identity.role,
        "can_view_pii": identity.can_view_pii,
        "minted_jwt_Header": "Bearer",
        "jwt_token": minted_jwt,
        "metrics": {
            "active_member_count": active_members,
            "total_aua": total_aua,
            "avg_aua": avg_aua,
        },
        "compiled_dimension_sql": cube_payload.get("compiledDimensionSql", {}),
        "cube_data": rows,
    }


class PortalGatewayApp:
    """
    Modular FastAPI-style Gateway Application for the Version 2.0 Thin Web Portal.
    Decouples IAP authentication, RBAC JWT minting, and Cube REST API proxying.
    """

    def __init__(
        self,
        cube_base_url: str | None = None,
        roster_path: Path | str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.cube_base_url = cube_base_url
        self.roster_path = roster_path
        self.api_secret = api_secret
        self.routers: list[APIRouter] = []
        self.fastapi_app = FastAPI(title="SCBI Portal API Gateway v2.0") if FastAPI else None

    def include_router(self, router: APIRouter) -> None:
        self.routers.append(router)

    def dispatch(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str] | None = None,
        query_params: Mapping[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> PortalResponse:
        req_headers = dict(headers or {})
        parsed_url = urllib.parse.urlsplit(path)
        clean_path = parsed_url.path or "/"
        merged_query: dict[str, Any] = dict(query_params or {})
        for k, v in urllib.parse.parse_qsl(parsed_url.query):
            merged_query.setdefault(k, v)

        handler: Callable[..., tuple[int, dict[str, Any]]] | None = None
        for router in self.routers:
            if (method.upper(), clean_path) in router.routes:
                handler = router.routes[(method.upper(), clean_path)]
                break

        if handler is None:
            return PortalResponse(
                status_code=404,
                body={"error": f"Route {method.upper()} {clean_path} not found."},
                headers={"Content-Type": "application/json"},
            )

        try:
            status_code, payload = handler(
                headers=req_headers,
                query_params=merged_query,
                json_body=json_body or {},
            )
            return PortalResponse(
                status_code=status_code,
                body=payload,
                headers={"Content-Type": "application/json"},
            )
        except PortalAuthError as auth_err:
            return PortalResponse(
                status_code=auth_err.status_code,
                body={"error": auth_err.message, "status": auth_err.status_code},
                headers={"Content-Type": "application/json"},
            )
        except Exception as exc:
            return PortalResponse(
                status_code=500,
                body={"error": str(exc), "status": 500},
                headers={"Content-Type": "application/json"},
            )


class PortalTestClient:
    """Synchronous test client matching FastAPI/Starlette `TestClient` semantics."""

    def __init__(self, app: PortalGatewayApp) -> None:
        self.app = app

    def get(
        self,
        path: str,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> PortalResponse:
        return self.app.dispatch("GET", path, headers=headers, query_params=params)

    def post(
        self,
        path: str,
        headers: Mapping[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> PortalResponse:
        return self.app.dispatch("POST", path, headers=headers, json_body=json)


def create_portal_app(
    cube_base_url: str | None = None,
    roster_path: Path | str | None = None,
    api_secret: str | None = None,
) -> PortalGatewayApp:
    """Factory constructing the modular Version 2.0 Portal API Gateway."""
    app = PortalGatewayApp(
        cube_base_url=cube_base_url,
        roster_path=roster_path,
        api_secret=api_secret,
    )

    health_router = APIRouter(prefix="")
    api_router = APIRouter(prefix="/api")

    @health_router.get("/health")
    def get_health(**_kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "status": "HEALTHY",
            "service": "scbi-portal-gateway-v2",
            "synthetic_endpoints_enabled": False,
        }

    @api_router.get("/whoami")
    def get_whoami(
        headers: Mapping[str, str],
        **_kwargs: Any,
    ) -> tuple[int, dict[str, Any]]:
        identity = resolve_verified_identity(headers, roster_path=app.roster_path)
        token = mint_cube_jwt(identity, secret=app.api_secret)
        return 200, {
            **identity.to_dict(),
            "jwt_token": token,
        }

    @api_router.get("/member_analysis_query")
    def get_member_analysis(
        headers: Mapping[str, str],
        query_params: Mapping[str, Any],
        **_kwargs: Any,
    ) -> tuple[int, dict[str, Any]]:
        return handle_member_analysis_query(
            headers=headers,
            query_params=query_params,
            cube_base_url=app.cube_base_url,
            roster_path=app.roster_path,
            api_secret=app.api_secret,
        )

    @api_router.post("/cube/load")
    def post_cube_load(
        headers: Mapping[str, str],
        json_body: dict[str, Any],
        **_kwargs: Any,
    ) -> tuple[int, dict[str, Any]]:
        identity = resolve_verified_identity(headers, roster_path=app.roster_path)
        raw_query = json_body.get("query", json_body)
        status_code, cube_resp, jwt_token = proxy_cube_load(
            cube_query=raw_query,
            identity=identity,
            cube_base_url=app.cube_base_url,
            api_secret=app.api_secret,
        )
        return status_code, {
            "email": identity.email,
            "role": identity.role,
            "can_view_pii": identity.can_view_pii,
            "jwt_token": jwt_token,
            "cube_response": cube_resp,
        }

    app.include_router(health_router)
    app.include_router(api_router)
    return app


def start_portal_http_server(
    app: PortalGatewayApp,
    host: str = "127.0.0.1",
    port: int = 0,
) -> http.server.ThreadingHTTPServer:
    """Starts a live ThreadingHTTPServer backed by the modular `PortalGatewayApp`."""

    class GatewayHTTPHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            resp = app.dispatch("GET", self.path, headers=dict(self.headers))
            self._write_response(resp)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                parsed_body = json.loads(raw_body) if raw_body else {}
            except json.JSONDecodeError:
                parsed_body = {}
            resp = app.dispatch(
                "POST",
                self.path,
                headers=dict(self.headers),
                json_body=parsed_body,
            )
            self._write_response(resp)

        def _write_response(self, resp: PortalResponse) -> None:
            payload = json.dumps(resp.body).encode("utf-8")
            self.send_response(resp.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return http.server.ThreadingHTTPServer((host, port), GatewayHTTPHandler)
