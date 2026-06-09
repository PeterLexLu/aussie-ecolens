"""Day 3 upload authorization checks for Member 1."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.api.routes.protected_routes import assert_route_is_protected
from backend.api.routes.upload_authorization import handle_upload_init, handle_upload_post
from backend.auth.cognito.jwt_validator import AuthError
from backend.auth.middleware.auth_context import UserContext, require_owner


class UploadAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_auth_mode = os.environ.get("AUTH_MODE")
        os.environ["AUTH_MODE"] = "cognito"

    def tearDown(self) -> None:
        if self.previous_auth_mode is None:
            os.environ.pop("AUTH_MODE", None)
        else:
            os.environ["AUTH_MODE"] = self.previous_auth_mode

    def test_upload_init_route_is_registered_as_protected(self) -> None:
        assert_route_is_protected("POST", "/api/uploads/init")

    def test_upload_fallback_route_is_registered_as_protected(self) -> None:
        assert_route_is_protected("POST", "/api/upload")

    def test_upload_init_without_token_returns_401(self) -> None:
        response = handle_upload_init({"headers": {}})
        self.assertEqual(response["statusCode"], 401)
        self.assertEqual(response["body"]["error"], "Authentication required")

    def test_upload_without_token_returns_401(self) -> None:
        response = handle_upload_post({"headers": {}})
        self.assertEqual(response["statusCode"], 401)
        self.assertEqual(response["body"]["error"], "Authentication required")

    def test_upload_init_accepts_valid_user_context(self) -> None:
        context = UserContext(owner_id="owner-123", email="owner@example.com")
        with patch(
            "backend.auth.middleware.auth_context.get_user_context",
            return_value=context,
        ):
            response = handle_upload_init({"headers": {"Authorization": "Bearer token"}})

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(response["body"]["authorized"])
        self.assertEqual(response["body"]["ownerId"], "owner-123")

    def test_owner_mismatch_raises_403(self) -> None:
        context = UserContext(owner_id="owner-123", email="owner@example.com")
        with self.assertRaises(AuthError) as raised:
            require_owner(context, "other-owner")

        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
