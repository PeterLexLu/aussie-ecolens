"""Notifications table item shape for matched tag alerts."""

NOTIFICATIONS_TABLE_NAME = "Notifications"

NOTIFICATION_ITEM_FIELDS = (
    "notificationId",
    "ownerId",
    "email",
    "tag",
    "fileId",
    "fileUrl",
    "createdAt",
)


def build_notification_item(
    *,
    notification_id: str,
    owner_id: str,
    email: str,
    tag: str,
    file_id: str,
    file_url: str,
    created_at: str,
) -> dict[str, str]:
    """Create a notification record after a tag match."""
    if not owner_id:
        raise ValueError("owner_id is required for Notifications records.")
    if not tag:
        raise ValueError("tag is required for Notifications records.")
    return {
        "notificationId": notification_id,
        "ownerId": owner_id,
        "email": email,
        "tag": tag,
        "fileId": file_id,
        "fileUrl": file_url,
        "createdAt": created_at,
    }
