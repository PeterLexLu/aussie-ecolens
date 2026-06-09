"""Current-user route for `/api/me`."""

from __future__ import annotations

from typing import Any

from backend.auth.middleware.auth_context import UserContext, require_auth


@require_auth
def handle_me(
    event: dict[str, Any],
    context: Any = None,
    *,
    user_context: UserContext,
) -> dict[str, Any]:
    """Return the authenticated Cognito user context."""

    return {
        "statusCode": 200,
        "body": {
            "authenticated": True,
            "user": {
                "ownerId": user_context.owner_id,
                "email": user_context.email,
            },
        },
    }
