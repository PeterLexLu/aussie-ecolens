"""Delete and manual tag mutation authorization guards for Day 6."""

from __future__ import annotations

from typing import Any

from backend.auth.middleware.auth_context import UserContext, require_auth
from backend.auth.middleware.resource_permissions import (
    parse_owned_resources,
    require_owned_resources,
)


def _authorize_resources(event: dict[str, Any], user_context: UserContext):
    """Authorize resources resolved from the database by the handler layer."""

    resources = parse_owned_resources(event.get("resolvedResources"))
    return require_owned_resources(user_context, resources)


@require_auth
def handle_authorize_delete(
    event: dict[str, Any],
    context: Any = None,
    *,
    user_context: UserContext,
) -> dict[str, Any]:
    """Authorize deletion and return trusted object keys to the storage layer."""

    resources = _authorize_resources(event, user_context)
    return {
        "statusCode": 200,
        "body": {
            "authorized": True,
            "ownerId": user_context.owner_id,
            "fileIds": [resource.file_id for resource in resources],
            "objectKeys": [
                key
                for resource in resources
                for key in (resource.original_key, resource.thumbnail_key)
                if key
            ],
        },
    }


@require_auth
def handle_authorize_tag_update(
    event: dict[str, Any],
    context: Any = None,
    *,
    user_context: UserContext,
) -> dict[str, Any]:
    """Authorize manual tag modifications for database-resolved file records."""

    resources = _authorize_resources(event, user_context)
    return {
        "statusCode": 200,
        "body": {
            "authorized": True,
            "ownerId": user_context.owner_id,
            "fileIds": [resource.file_id for resource in resources],
        },
    }
