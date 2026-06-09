"""Shared database identity shape supplied by auth middleware."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated user context expected by Member C database wrappers."""

    owner_id: str
    email: str

    def require_owner_id(self) -> str:
        if not self.owner_id:
            raise ValueError("Authenticated owner_id is required.")
        return self.owner_id
