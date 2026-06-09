"""Day 5 owner scoping checks for query, tag update, and delete routes."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.api.routes.protected_routes import assert_route_is_protected
from backend.api.routes.query_authorization import (
    handle_owner_scoped_delete,
    handle_owner_scoped_query,
    handle_owner_scoped_tag_update,
)
from backend.auth.middleware.auth_context import UserContext


class OwnerScopingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_auth_mode = os.environ.get("AUTH_MODE")
        os.environ["AUTH_MODE"] = "cognito"
        self.user = UserContext(owner_id="owner-123", email="owner@example.com")

    def tearDown(self) -> None:
        if self.previous_auth_mode is None:
            os.environ.pop("AUTH_MODE", None)
        else:
            os.environ["AUTH_MODE"] = self.previous_auth_mode

    def test_query_routes_are_registered_as_protected(self) -> None:
        routes = [
            ("GET", "/api/files"),
            ("GET", "/api/files/{fileId}"),
            ("POST", "/api/query/tags"),
            ("POST", "/api/query/species"),
            ("POST", "/api/query/thumbnail"),
            ("POST", "/api/query/by-file"),
            ("POST", "/api/tags/bulk"),
            ("POST", "/api/files/delete"),
        ]
        for method, path in routes:
            with self.subTest(route=f"{method} {path}"):
                assert_route_is_protected(method, path)

    def test_query_without_token_returns_401(self) -> None:
        response = handle_owner_scoped_query({"headers": {}})
        self.assertEqual(response["statusCode"], 401)

    def test_query_receives_trusted_owner_scope(self) -> None:
        with patch(
            "backend.auth.middleware.auth_context.get_user_context",
            return_value=self.user,
        ):
            response = handle_owner_scoped_query({"headers": {"Authorization": "Bearer token"}})

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["ownerId"], "owner-123")

    def test_tag_update_for_another_owner_returns_403(self) -> None:
        with patch(
            "backend.auth.middleware.auth_context.get_user_context",
            return_value=self.user,
        ):
            response = handle_owner_scoped_tag_update(
                {
                    "headers": {"Authorization": "Bearer token"},
                    "resourceOwnerId": "other-owner",
                }
            )

        self.assertEqual(response["statusCode"], 403)

    def test_delete_for_another_owner_returns_403(self) -> None:
        with patch(
            "backend.auth.middleware.auth_context.get_user_context",
            return_value=self.user,
        ):
            response = handle_owner_scoped_delete(
                {
                    "headers": {"Authorization": "Bearer token"},
                    "resourceOwnerId": "other-owner",
                }
            )

        self.assertEqual(response["statusCode"], 403)

    def test_tag_update_for_current_owner_is_allowed(self) -> None:
        with patch(
            "backend.auth.middleware.auth_context.get_user_context",
            return_value=self.user,
        ):
            response = handle_owner_scoped_tag_update(
                {
                    "headers": {"Authorization": "Bearer token"},
                    "resourceOwnerId": "owner-123",
                }
            )

        self.assertEqual(response["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
