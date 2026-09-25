"""Local Development Environment & GCS Application Default Credentials (ADC) Harness.

Validates the local development environment contract (`docker-compose.dev.yml`,
`.env.example`, DuckLake schema seeding) and verifies Google Cloud Application
Default Credentials (ADC) without leaking secret material or committing service
account keys to the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

INFRA_DIR = Path(__file__).resolve().parent
COMPOSE_DEV_PATH = INFRA_DIR / "docker-compose.dev.yml"
ENV_EXAMPLE_PATH = INFRA_DIR / ".env.example"
DUCKLAKE_SCHEMA_PATH = INFRA_DIR.parent / "ducklake" / "schema.sql"

VALID_ADC_TYPES = frozenset(
    {
        "authorized_user",
        "service_account",
        "external_account",
        "impersonated_service_account",
    }
)

REQUIRED_ENV_KEYS = (
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DUCKLAKE_DB_URL",
    "GCS_BUCKET_NAME",
    "GCP_PROJECT_ID",
    "CUBEJS_API_SECRET",
    "CUBEJS_DEV_MODE",
    "CUBE_REST_PORT",
    "CUBE_SQL_PORT",
    "PORTAL_PORT",
)

# Patterns that must never appear in committed .env.example or infra manifests
SECRET_LEAK_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"ya29\.[0-9A-Za-z\-_]+"),
)


def locate_adc_file(env: dict[str, str] | None = None) -> Path | None:
    """Locate the Google Cloud Application Default Credentials file on disk."""
    environ = env if env is not None else os.environ
    explicit = environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return candidate
        return None

    # Standard gcloud ADC path on Linux/macOS
    xdg_config = environ.get("CLOUDSDK_CONFIG", "").strip()
    if xdg_config:
        candidate = Path(xdg_config).expanduser() / "application_default_credentials.json"
    else:
        candidate = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"

    return candidate if candidate.is_file() else None


def verify_adc_credentials(adc_path: Path | str | None = None) -> dict[str, Any]:
    """Validate an ADC JSON file structure without exposing sensitive credentials."""
    resolved = Path(adc_path) if adc_path is not None else locate_adc_file()
    if resolved is None or not resolved.is_file():
        return {
            "valid": False,
            "reason": "ADC file not found. Run `gcloud auth application-default login`.",
            "credential_type": None,
            "path": str(resolved) if resolved else None,
        }

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "valid": False,
            "reason": f"Invalid JSON in ADC file: {exc}",
            "credential_type": None,
            "path": str(resolved),
        }

    if not isinstance(payload, dict):
        return {
            "valid": False,
            "reason": "ADC JSON root must be an object",
            "credential_type": None,
            "path": str(resolved),
        }

    cred_type = payload.get("type")
    if cred_type not in VALID_ADC_TYPES:
        return {
            "valid": False,
            "reason": f"Unsupported or missing credential type: {cred_type!r}",
            "credential_type": cred_type,
            "path": str(resolved),
        }

    if cred_type == "authorized_user":
        missing = [k for k in ("client_id", "client_secret", "refresh_token") if not payload.get(k)]
        if missing:
            return {
                "valid": False,
                "reason": f"Missing required authorized_user fields: {', '.join(missing)}",
                "credential_type": cred_type,
                "path": str(resolved),
            }
    elif cred_type == "service_account":
        missing = [k for k in ("client_email", "private_key", "token_uri") if not payload.get(k)]
        if missing:
            return {
                "valid": False,
                "reason": f"Missing required service_account fields: {', '.join(missing)}",
                "credential_type": cred_type,
                "path": str(resolved),
            }

    return {
        "valid": True,
        "reason": "ok",
        "credential_type": cred_type,
        "quota_project_id": payload.get("quota_project_id") or payload.get("project_id"),
        "path": str(resolved),
    }


def parse_env_keys(env_file: Path = ENV_EXAMPLE_PATH) -> dict[str, str]:
    """Parse key-value pairs from a dotenv file."""
    result: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        result[key.strip()] = val.strip()
    return result


def verify_dev_environment(
    compose_path: Path = COMPOSE_DEV_PATH,
    env_example_path: Path = ENV_EXAMPLE_PATH,
    schema_path: Path = DUCKLAKE_SCHEMA_PATH,
) -> dict[str, Any]:
    """Verify the local development harness files and security constraints."""
    errors: list[str] = []

    if not compose_path.is_file():
        errors.append(f"Missing compose manifest: {compose_path}")
    else:
        compose_text = compose_path.read_text(encoding="utf-8")
        if "postgres:16-alpine" not in compose_text:
            errors.append("docker-compose.dev.yml must use postgres:16-alpine")
        if "5433:5432" not in compose_text:
            errors.append("docker-compose.dev.yml must map host port 5433 to container port 5432")
        if "../ducklake/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql:ro" not in compose_text:
            errors.append("docker-compose.dev.yml must mount ../ducklake/schema.sql as read-only init script")

    if not schema_path.is_file():
        errors.append(f"Missing DuckLake schema SQL: {schema_path}")

    env_vars: dict[str, str] = {}
    if not env_example_path.is_file():
        errors.append(f"Missing .env.example: {env_example_path}")
    else:
        raw_env = env_example_path.read_text(encoding="utf-8")
        for pattern in SECRET_LEAK_PATTERNS:
            if pattern.search(raw_env):
                errors.append(f"Secret leak pattern detected in {env_example_path.name}")
        env_vars = parse_env_keys(env_example_path)
        for req_key in REQUIRED_ENV_KEYS:
            if req_key not in env_vars:
                errors.append(f"Missing required key in .env.example: {req_key}")

    adc_status = verify_adc_credentials()

    return {
        "harness_valid": len(errors) == 0,
        "errors": errors,
        "compose_path": str(compose_path),
        "env_example_path": str(env_example_path),
        "schema_path": str(schema_path),
        "env_keys_defined": sorted(env_vars.keys()),
        "adc_status": adc_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify local dev harness & GCS ADC setup.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args()

    report = verify_dev_environment()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status_label = "PASS" if report["harness_valid"] else "FAIL"
        print(f"[adc_harness] Local Dev Harness Status: {status_label}")
        print(f"  Compose Manifest : {report['compose_path']}")
        print(f"  Env Template     : {report['env_example_path']} ({len(report['env_keys_defined'])} keys)")
        print(f"  ADC Credentials  : valid={report['adc_status']['valid']} ({report['adc_status']['credential_type']})")


if __name__ == "__main__":
    main()
