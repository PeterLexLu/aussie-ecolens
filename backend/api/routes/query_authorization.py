"""Owner-scoped query and file-modification guards for Day 5."""

from __future__ import annotations

from typing import Any

from backend.auth.middleware.auth_context import (
    UserContext,
    owner_scoped_request,
    require_auth,
    require_owner,
)


@require_auth
def handle_owner_scoped_query(
    event: dict[str, Any],
    context: Any = None,
    *,
    user_context: UserContext,
) -> dict[str, Any]:
    """Pass a trusted owner filter to query handlers owned by Member 3."""

    scoped_event = owner_scoped_request(event, user_context)
    return {
        "statusCode": 200,
        "body": {
            "authorized": True,
            "ownerId": scoped_event["ownerId"],
        },
    }


@require_auth
def handle_owner_scoped_tag_update(
    event: dict[str, Any],
    context: Any = None,
    *,
    user_context: UserContext,
) -> dict[str, Any]:
    """Reject manual tag changes when the target file belongs to another user."""

    require_owner(user_context, str(event.get("resourceOwnerId", "")))
    return {
        "statusCode": 200,
        "body": {
            "authorized": True,
            "ownerId": user_context.owner_id,
        },
    }


@require_auth
def handle_owner_scoped_delete(
    event: dict[str, Any],
    context: Any = None,
    *,
    user_context: UserContext,
) -> dict[str, Any]:
    """Reject file deletion when the target file belongs to another user."""

    require_owner(user_context, str(event.get("resourceOwnerId", "")))
    return {
        "statusCode": 200,
        "body": {
            "authorized": True,
            "ownerId": user_context.owner_id,
        },
    }
