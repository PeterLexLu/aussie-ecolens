"""Upload authorization guards for Day 3 integration."""

from __future__ import annotations

from typing import Any

from backend.auth.middleware.auth_context import UserContext, require_auth


@require_auth
def handle_upload_init(
    event: dict[str, Any],
    context: Any = None,
    *,
    user_context: UserContext,
) -> dict[str, Any]:
    """Authorize upload initialisation before storage creates a presigned URL.

    Member B owns the storage implementation. This route skeleton makes the
    auth contract explicit: no Cognito identity means no upload-init request.
    """

    return {
        "statusCode": 200,
        "body": {
            "authorized": True,
            "ownerId": user_context.owner_id,
            "email": user_context.email,
        },
    }


@require_auth
def handle_upload_post(
    event: dict[str, Any],
    context: Any = None,
    *,
    user_context: UserContext,
) -> dict[str, Any]:
    """Authorize direct upload API fallback before file handling runs."""

    return {
        "statusCode": 200,
        "body": {
            "authorized": True,
            "ownerId": user_context.owner_id,
            "email": user_context.email,
        },
    }
