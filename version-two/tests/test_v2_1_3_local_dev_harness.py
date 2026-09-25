"""Tests for Ticket V2-1.3: Local Development Environment & GCS ADC Harness."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

VERSION_TWO_DIR = Path(__file__).resolve().parents[1]
if str(VERSION_TWO_DIR) not in sys.path:
    sys.path.insert(0, str(VERSION_TWO_DIR))

from infra.adc_harness import (
    COMPOSE_DEV_PATH,
    DUCKLAKE_SCHEMA_PATH,
    ENV_EXAMPLE_PATH,
    REQUIRED_ENV_KEYS,
    locate_adc_file,
    parse_env_keys,
    verify_adc_credentials,
    verify_dev_environment,
)


class TestV213LocalDevHarness(unittest.TestCase):
    def test_docker_compose_dev_contract(self) -> None:
        """Verify docker-compose.dev.yml uses postgres:16-alpine, port 5433:5432, and mounts schema.sql."""
        self.assertTrue(COMPOSE_DEV_PATH.is_file())
        content = COMPOSE_DEV_PATH.read_text(encoding="utf-8")
        self.assertIn("postgres:16-alpine", content)
        self.assertIn("5433:5432", content)
        self.assertIn("ducklake_catalog", content)
        self.assertIn("../ducklake/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql:ro", content)
        self.assertIn("pg_isready", content)

    def test_env_example_completeness_and_zero_secrets(self) -> None:
        """Verify .env.example contains all required keys and zero hardcoded secrets."""
        self.assertTrue(ENV_EXAMPLE_PATH.is_file())
        env_map = parse_env_keys(ENV_EXAMPLE_PATH)
        for req_key in REQUIRED_ENV_KEYS:
            self.assertIn(req_key, env_map, f"Missing required key {req_key}")

        self.assertEqual(env_map["CUBE_REST_PORT"], "4000")
        self.assertEqual(env_map["CUBE_SQL_PORT"], "5432")
        self.assertEqual(env_map["PORTAL_PORT"], "8000")
        self.assertIn("5433/ducklake_catalog", env_map["DUCKLAKE_DB_URL"])

        report = verify_dev_environment()
        self.assertTrue(report["harness_valid"], f"Harness validation failed: {report['errors']}")
        self.assertEqual(report["errors"], [])

    def test_adc_credential_validator(self) -> None:
        """Verify ADC JSON validation accepts valid structures and rejects malformed/missing ones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # 1. Valid authorized_user ADC
            valid_user_adc = tmp / "valid_user_adc.json"
            valid_user_adc.write_text(
                json.dumps(
                    {
                        "type": "authorized_user",
                        "client_id": "mock-client-id.apps.googleusercontent.com",
                        "client_secret": "mock-client-secret",
                        "refresh_token": "mock-refresh-token",
                        "quota_project_id": "data-recon-dev",
                    }
                ),
                encoding="utf-8",
            )
            res_valid = verify_adc_credentials(valid_user_adc)
            self.assertTrue(res_valid["valid"])
            self.assertEqual(res_valid["credential_type"], "authorized_user")
            self.assertEqual(res_valid["quota_project_id"], "data-recon-dev")

            # 2. Missing refresh_token in authorized_user
            incomplete_adc = tmp / "incomplete_adc.json"
            incomplete_adc.write_text(
                json.dumps(
                    {
                        "type": "authorized_user",
                        "client_id": "mock-client-id",
                    }
                ),
                encoding="utf-8",
            )
            res_incomplete = verify_adc_credentials(incomplete_adc)
            self.assertFalse(res_incomplete["valid"])
            self.assertIn("Missing required authorized_user fields", res_incomplete["reason"])

            # 3. Unsupported type
            invalid_type_adc = tmp / "invalid_type.json"
            invalid_type_adc.write_text(json.dumps({"type": "api_key_literal"}), encoding="utf-8")
            res_type = verify_adc_credentials(invalid_type_adc)
            self.assertFalse(res_type["valid"])

            # 4. Non-existent file
            res_missing = verify_adc_credentials(tmp / "nonexistent.json")
            self.assertFalse(res_missing["valid"])

            # 5. locate_adc_file via explicit env
            located = locate_adc_file({"GOOGLE_APPLICATION_CREDENTIALS": str(valid_user_adc)})
            self.assertEqual(located, valid_user_adc)


if __name__ == "__main__":
    unittest.main()
