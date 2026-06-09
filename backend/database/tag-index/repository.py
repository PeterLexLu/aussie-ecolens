"""TagIndex persistence for inference results."""

from __future__ import annotations

from typing import Protocol

from .schema import TAG_SOURCE_AUTO, TAG_SOURCE_MANUAL, build_tag_index_item


class TagIndexTable(Protocol):
    def put_item(self, *, Item: dict[str, object]) -> object:
        """Persist one tag index item."""

    def delete_item(self, **kwargs: object) -> object:
        """Delete one tag index item."""

    def query(self, **kwargs: object) -> dict[str, object]:
        """Query tag index items."""


class TagIndexRepository:
    """Write owner-scoped tag counts for processed files."""

    def __init__(self, table: TagIndexTable) -> None:
        self.table = table

    def save_inference_tags(
        self,
        *,
        owner_id: str,
        file_id: str,
        tags: dict[str, int],
        updated_at: str,
    ) -> list[dict[str, object]]:
        saved: list[dict[str, object]] = []
        for tag, count in tags.items():
            item = build_tag_index_item(
                tag=tag,
                owner_id=owner_id,
                file_id=file_id,
                count=count,
                source=TAG_SOURCE_AUTO,
                updated_at=updated_at,
            )
            self.table.put_item(Item=item)
            saved.append(item)
        return saved

    def save_manual_tags(
        self,
        *,
        owner_id: str,
        file_id: str,
        tags: list[str],
        updated_at: str,
    ) -> list[dict[str, object]]:
        saved: list[dict[str, object]] = []
        for tag in tags:
            item = build_tag_index_item(
                tag=tag,
                owner_id=owner_id,
                file_id=file_id,
                count=1,
                source=TAG_SOURCE_MANUAL,
                updated_at=updated_at,
            )
            self.table.put_item(Item=item)
            saved.append(item)
        return saved

    def delete_manual_tags(self, *, owner_id: str, file_id: str, tags: list[str]) -> int:
        deleted = 0
        for tag in tags:
            self.table.delete_item(Key={"ownerTag": f"{owner_id}#{tag}", "fileId": file_id})
            deleted += 1
        return deleted

    def delete_file_tags(self, *, owner_id: str, file_id: str, tags: dict[str, int] | list[str]) -> int:
        """Delete TagIndex rows for one removed file."""
        tag_names = tags.keys() if isinstance(tags, dict) else tags
        deleted = 0
        for tag in tag_names:
            self.table.delete_item(Key={"ownerTag": f"{owner_id}#{tag}", "fileId": file_id})
            deleted += 1
        return deleted

    def find_file_ids_by_tag_counts(
        self,
        *,
        owner_id: str,
        requested_tags: dict[str, int],
    ) -> set[str]:
        matching_sets: list[set[str]] = []
        for tag, minimum_count in requested_tags.items():
            result = self.table.query(
                KeyConditionExpression="ownerTag = :ownerTag",
                FilterExpression="#count >= :count",
                ExpressionAttributeNames={"#count": "count"},
                ExpressionAttributeValues={
                    ":ownerTag": f"{owner_id}#{tag}",
                    ":count": minimum_count,
                },
            )
            items = result.get("Items", [])
            file_ids = {
                str(item["fileId"])
                for item in items
                if isinstance(item, dict) and "fileId" in item
            } if isinstance(items, list) else set()
            matching_sets.append(file_ids)

        if not matching_sets:
            return set()
        return set.intersection(*matching_sets)
