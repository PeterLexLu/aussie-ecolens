"""Day 6 delete and manual tag mutation permission checks."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.api.routes.file_mutation_authorization import (
    handle_authorize_delete,
    handle_authorize_tag_update,
)
from backend.auth.middleware.auth_context import UserContext


class FileMutationPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_auth_mode = os.environ.get("AUTH_MODE")
        os.environ["AUTH_MODE"] = "cognito"
        self.user = UserContext(owner_id="owner-123", email="owner@example.com")
        self.owned_resource = {
            "fileId": "file-1",
            "ownerId": "owner-123",
            "originalKey": "users/owner-123/species/koala/file-1/original.jpg",
            "thumbnailKey": "users/owner-123/file-1.jpg",
        }

    def tearDown(self) -> None:
        if self.previous_auth_mode is None:
            os.environ.pop("AUTH_MODE", None)
        else:
            os.environ["AUTH_MODE"] = self.previous_auth_mode

    def _call_as_user(self, handler, resources):
        with patch(
            "backend.auth.middleware.auth_context.get_user_context",
            return_value=self.user,
        ):
            return handler(
                {
                    "headers": {"Authorization": "Bearer token"},
                    "resolvedResources": resources,
                }
            )

    def test_delete_without_token_returns_401(self) -> None:
        response = handle_authorize_delete({"headers": {}, "resolvedResources": [self.owned_resource]})
        self.assertEqual(response["statusCode"], 401)

    def test_delete_current_owner_returns_trusted_object_keys(self) -> None:
        response = self._call_as_user(handle_authorize_delete, [self.owned_resource])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["fileIds"], ["file-1"])
        self.assertEqual(len(response["body"]["objectKeys"]), 2)

    def test_delete_rejects_mixed_owner_batch(self) -> None:
        other_resource = {"fileId": "file-2", "ownerId": "other-owner"}
        response = self._call_as_user(
            handle_authorize_delete,
            [self.owned_resource, other_resource],
        )
        self.assertEqual(response["statusCode"], 403)

    def test_tag_update_rejects_other_owner(self) -> None:
        response = self._call_as_user(
            handle_authorize_tag_update,
            [{"fileId": "file-2", "ownerId": "other-owner"}],
        )
        self.assertEqual(response["statusCode"], 403)

    def test_tag_update_allows_current_owner(self) -> None:
        response = self._call_as_user(handle_authorize_tag_update, [self.owned_resource])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["fileIds"], ["file-1"])

    def test_missing_database_owner_metadata_returns_403(self) -> None:
        response = self._call_as_user(
            handle_authorize_delete,
            [{"fileId": "file-1"}],
        )
        self.assertEqual(response["statusCode"], 403)


if __name__ == "__main__":
    unittest.main()
