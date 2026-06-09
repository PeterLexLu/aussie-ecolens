"""Owner permission checks for file delete and manual tag mutations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.auth.cognito.jwt_validator import AuthError
from backend.auth.middleware.auth_context import UserContext, require_owner


@dataclass(frozen=True)
class OwnedFileResource:
    """File metadata resolved from the database before a mutation."""

    file_id: str
    owner_id: str
    original_key: str = ""
    thumbnail_key: str = ""


def parse_owned_resources(items: Any) -> list[OwnedFileResource]:
    """Parse database-resolved file metadata supplied by the handler layer."""

    if not isinstance(items, list) or not items:
        raise AuthError("At least one resolved file resource is required", 400)

    resources: list[OwnedFileResource] = []
    for item in items:
        if not isinstance(item, dict):
            raise AuthError("Invalid resolved file resource", 400)
        file_id = str(item.get("fileId", "")).strip()
        owner_id = str(item.get("ownerId", "")).strip()
        if not file_id or not owner_id:
            raise AuthError("Resolved file resource is missing ownership metadata", 403)
        resources.append(
            OwnedFileResource(
                file_id=file_id,
                owner_id=owner_id,
                original_key=str(item.get("originalKey", "")).strip(),
                thumbnail_key=str(item.get("thumbnailKey", "")).strip(),
            )
        )
    return resources


def require_owned_resources(
    user_context: UserContext,
    resources: list[OwnedFileResource],
) -> list[OwnedFileResource]:
    """Return resources only when every file belongs to the current user."""

    for resource in resources:
        require_owner(user_context, resource.owner_id)
    return resources
