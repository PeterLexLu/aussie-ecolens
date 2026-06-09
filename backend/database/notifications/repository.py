"""Notification record creation for matched tag subscriptions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .schema import build_notification_item


class NotificationTable(Protocol):
    def put_item(self, *, Item: dict[str, object]) -> object:
        """Persist one notification."""


class SubscriptionMatcher(Protocol):
    def find_matching_subscriptions(
        self,
        *,
        owner_id: str,
        tags: dict[str, int] | list[str],
    ) -> list[dict[str, object]]:
        """Return subscriptions whose tag appears in the supplied tag set."""


class NotificationRepository:
    """Create Notifications table rows when tags match subscriptions."""

    def __init__(self, table: NotificationTable) -> None:
        self.table = table

    def save_notification(
        self,
        *,
        notification_id: str,
        owner_id: str,
        email: str,
        tag: str,
        file_id: str,
        file_url: str,
        created_at: str,
    ) -> dict[str, str]:
        item = build_notification_item(
            notification_id=notification_id,
            owner_id=owner_id,
            email=email,
            tag=tag,
            file_id=file_id,
            file_url=file_url,
            created_at=created_at,
        )
        self.table.put_item(Item=item)
        return item

    def create_for_matching_tags(
        self,
        *,
        subscriptions: SubscriptionMatcher,
        notification_id_factory: Callable[[], str],
        owner_id: str,
        file_id: str,
        file_url: str,
        tags: dict[str, int] | list[str],
        created_at: str,
    ) -> list[dict[str, str]]:
        created: list[dict[str, str]] = []
        for match in subscriptions.find_matching_subscriptions(owner_id=owner_id, tags=tags):
            tag = str(match["tag"])
            email = str(match["email"])
            created.append(
                self.save_notification(
                    notification_id=notification_id_factory(),
                    owner_id=owner_id,
                    email=email,
                    tag=tag,
                    file_id=file_id,
                    file_url=file_url,
                    created_at=created_at,
                )
            )
        return created
