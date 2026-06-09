"""Day 7 final-freeze integration checks for Member 1 auth/security work."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from backend.api.routes.current_user import handle_me
from backend.api.routes.protected_routes import PROTECTED_ROUTES, PUBLIC_ROUTES
from backend.auth.middleware.auth_context import get_user_context


ROOT = Path(__file__).resolve().parents[2]


class FinalAuthFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_auth_mode = os.environ.get("AUTH_MODE")
        os.environ["AUTH_MODE"] = "cognito"

    def tearDown(self) -> None:
        if self.previous_auth_mode is None:
            os.environ.pop("AUTH_MODE", None)
        else:
            os.environ["AUTH_MODE"] = self.previous_auth_mode

    def test_all_core_apis_are_registered_as_protected(self) -> None:
        expected = {
            "GET /api/me",
            "POST /api/uploads/init",
            "POST /api/upload",
            "GET /api/files",
            "GET /api/files/{fileId}",
            "POST /api/query/tags",
            "POST /api/query/species",
            "POST /api/query/thumbnail",
            "POST /api/query/by-file",
            "POST /api/tags/bulk",
            "POST /api/files/delete",
            "POST /api/subscribe",
            "GET /api/notifications",
        }
        self.assertEqual(PROTECTED_ROUTES, expected)
        self.assertTrue(PROTECTED_ROUTES.isdisjoint(PUBLIC_ROUTES))

    def test_http_api_authorizer_claims_map_to_user_context(self) -> None:
        context = get_user_context(
            {
                "requestContext": {
                    "authorizer": {
                        "jwt": {
                            "claims": {
                                "sub": "owner-http-api",
                                "email": "http@example.com",
                            }
                        }
                    }
                }
            }
        )
        self.assertEqual(context.owner_id, "owner-http-api")
        self.assertEqual(context.email, "http@example.com")

    def test_rest_api_authorizer_claims_map_to_user_context(self) -> None:
        context = get_user_context(
            {
                "requestContext": {
                    "authorizer": {
                        "claims": {
                            "sub": "owner-rest-api",
                            "email": "rest@example.com",
                        }
                    }
                }
            }
        )
        self.assertEqual(context.owner_id, "owner-rest-api")
        self.assertEqual(context.email, "rest@example.com")

    def test_current_user_route_returns_verified_owner_context(self) -> None:
        response = handle_me(
            {
                "requestContext": {
                    "authorizer": {
                        "jwt": {
                            "claims": {
                                "sub": "owner-123",
                                "email": "owner@example.com",
                            }
                        }
                    }
                }
            }
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["user"]["ownerId"], "owner-123")

    def test_iam_policy_wildcards_are_limited_to_log_statements(self) -> None:
        policies = [
            ROOT / "infra/aws/iam/processing-lambda-policy.json",
            ROOT / "infra/aws/iam/delete-tag-handler-policy.json",
        ]
        for path in policies:
            policy = json.loads(path.read_text(encoding="utf-8"))
            for statement in policy["Statement"]:
                if statement["Resource"] == "*":
                    self.assertIn("Logs", statement["Sid"])

    def test_s3_policy_resources_use_owner_scoped_paths(self) -> None:
        policy = json.loads(
            (ROOT / "infra/aws/iam/delete-tag-handler-policy.json").read_text(encoding="utf-8")
        )
        s3_statement = next(
            statement
            for statement in policy["Statement"]
            if statement["Sid"] == "DeleteOwnerScopedMediaObjects"
        )
        for resource in s3_statement["Resource"]:
            self.assertIn("/users/*/", resource)


if __name__ == "__main__":
    unittest.main()
