"""Subscriptions lookup helpers for notification matching."""

from __future__ import annotations

from typing import Protocol

from .schema import build_subscription_item


class SubscriptionTable(Protocol):
    def put_item(self, *, Item: dict[str, object]) -> object:
        """Persist one subscription."""

    def query(self, **kwargs: object) -> dict[str, object]:
        """Query subscription items."""


class SubscriptionRepository:
    """Owner-scoped tag subscription records."""

    def __init__(self, table: SubscriptionTable) -> None:
        self.table = table

    def save_subscription(
        self,
        *,
        subscription_id: str,
        owner_id: str,
        email: str,
        tag: str,
        created_at: str,
    ) -> dict[str, str]:
        item = build_subscription_item(
            subscription_id=subscription_id,
            owner_id=owner_id,
            email=email,
            tag=tag,
            created_at=created_at,
        )
        self.table.put_item(Item=item)
        return item

    def find_matching_subscriptions(
        self,
        *,
        owner_id: str,
        tags: dict[str, int] | list[str],
    ) -> list[dict[str, object]]:
        matches: list[dict[str, object]] = []
        tag_names = tags.keys() if isinstance(tags, dict) else tags
        for tag in tag_names:
            result = self.table.query(
                KeyConditionExpression="ownerTag = :ownerTag",
                ExpressionAttributeValues={
                    ":ownerTag": f"{owner_id}#{tag}",
                },
            )
            items = result.get("Items", [])
            if isinstance(items, list):
                matches.extend(item for item in items if isinstance(item, dict))
        return matches
