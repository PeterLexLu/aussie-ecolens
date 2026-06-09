"""Subscriptions table item shape for tag notification matching."""

SUBSCRIPTIONS_TABLE_NAME = "Subscriptions"

SUBSCRIPTION_ITEM_FIELDS = (
    "ownerTag",
    "subscriptionId",
    "ownerId",
    "email",
    "tag",
    "createdAt",
)


def build_subscription_item(
    *,
    subscription_id: str,
    owner_id: str,
    email: str,
    tag: str,
    created_at: str,
) -> dict[str, str]:
    """Create a tag subscription record."""
    if not owner_id:
        raise ValueError("owner_id is required for Subscriptions records.")
    if not tag:
        raise ValueError("tag is required for Subscriptions records.")
    return {
        "ownerTag": f"{owner_id}#{tag}",
        "subscriptionId": subscription_id,
        "ownerId": owner_id,
        "email": email,
        "tag": tag,
        "createdAt": created_at,
    }
