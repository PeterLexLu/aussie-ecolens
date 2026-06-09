"""Owner-aware Files table wrapper skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .checksum_index import build_checksum_lookup_key
from .schema import OWNER_CHECKSUM_INDEX_NAME, OWNER_CREATED_AT_INDEX_NAME, build_pending_file_item


class FileTable(Protocol):
    """Minimal DynamoDB-like table contract used by the repository."""

    def put_item(self, *, Item: dict[str, object]) -> object:
        """Persist an item."""

    def query(self, **kwargs: object) -> dict[str, object]:
        """Query table or index records."""

    def update_item(self, **kwargs: object) -> dict[str, object]:
        """Update an existing item."""

    def get_item(self, **kwargs: object) -> dict[str, object]:
        """Fetch one item by primary key."""

    def delete_item(self, **kwargs: object) -> dict[str, object]:
        """Delete one item."""


@dataclass(frozen=True)
class PendingFileResult:
    """Result returned when initialising a file metadata record."""

    duplicate: bool
    file: dict[str, object]


class FileRepository:
    """Files metadata operations scoped by the authenticated owner."""

    def __init__(self, table: FileTable) -> None:
        self.table = table

    def create_pending_file_record(
        self,
        *,
        owner_id: str,
        file_id: str,
        original_name: str,
        object_key: str,
        file_type: str,
        checksum: str,
        created_at: str,
    ) -> dict[str, object]:
        """Create a pending Files record for the current authenticated user."""
        item = build_pending_file_item(
            file_id=file_id,
            owner_id=owner_id,
            original_name=original_name,
            object_key=object_key,
            file_type=file_type,
            checksum=checksum,
            created_at=created_at,
        )
        self.table.put_item(Item=item)
        return item

    def create_pending_or_return_duplicate(
        self,
        *,
        owner_id: str,
        file_id: str,
        original_name: str,
        object_key: str,
        file_type: str,
        checksum: str,
        created_at: str,
    ) -> PendingFileResult:
        """Create a pending record unless the same owner already uploaded it."""
        existing = self.find_duplicate_by_checksum(owner_id=owner_id, checksum=checksum)
        if existing is not None:
            return PendingFileResult(duplicate=True, file=existing)

        created = self.create_pending_file_record(
            owner_id=owner_id,
            file_id=file_id,
            original_name=original_name,
            object_key=object_key,
            file_type=file_type,
            checksum=checksum,
            created_at=created_at,
        )
        return PendingFileResult(duplicate=False, file=created)

    def find_duplicate_by_checksum(
        self,
        *,
        owner_id: str,
        checksum: str,
    ) -> dict[str, object] | None:
        """Look up an existing file by checksum within the same owner scope."""
        key = build_checksum_lookup_key(owner_id=owner_id, checksum=checksum)
        result = self.table.query(
            IndexName=OWNER_CHECKSUM_INDEX_NAME,
            KeyConditionExpression="ownerId = :ownerId AND checksum = :checksum",
            ExpressionAttributeValues={
                ":ownerId": key["ownerId"],
                ":checksum": key["checksum"],
            },
            Limit=1,
        )
        items = result.get("Items", [])
        if not isinstance(items, list) or not items:
            return None
        first = items[0]
        return first if isinstance(first, dict) else None

    def list_files(self, *, owner_id: str, limit: int = 50) -> list[dict[str, object]]:
        """Return media records for one owner."""
        result = self.table.query(
            IndexName=OWNER_CREATED_AT_INDEX_NAME,
            KeyConditionExpression="ownerId = :ownerId",
            ExpressionAttributeValues={":ownerId": owner_id},
            ScanIndexForward=False,
            Limit=limit,
        )
        items = result.get("Items", [])
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def get_file(self, *, owner_id: str, file_id: str) -> dict[str, object] | None:
        """Fetch one owner-scoped file record."""
        result = self.table.get_item(Key={"ownerId": owner_id, "fileId": file_id})
        item = result.get("Item")
        return item if isinstance(item, dict) else None

    def find_by_url(self, *, owner_id: str, url: str) -> dict[str, object] | None:
        """Find an owned file by original or thumbnail URL."""
        for item in self.list_files(owner_id=owner_id, limit=500):
            if item.get("originalUrl") == url or item.get("thumbnailUrl") == url:
                return item
        return None

    def query_by_tag_counts(
        self,
        *,
        owner_id: str,
        requested_tags: dict[str, int],
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Match owned files whose Files.tags satisfy all requested counts."""
        matches: list[dict[str, object]] = []
        for item in self.list_files(owner_id=owner_id, limit=limit):
            tags = item.get("tags", {})
            if not isinstance(tags, dict):
                continue
            if all(int(tags.get(tag, 0)) >= count for tag, count in requested_tags.items()):
                matches.append(item)
        return matches

    def apply_bulk_tag_update(
        self,
        *,
        owner_id: str,
        file_id: str,
        tags: list[str],
        operation: int,
        updated_at: str,
    ) -> dict[str, object]:
        """Update Files.tags for manual add/remove tag operations."""
        expression_names = {"#tags": "tags", "#updatedAt": "updatedAt"}
        expression_values: dict[str, object] = {":updatedAt": updated_at}
        update_parts = ["#updatedAt = :updatedAt"]

        if operation == 1:
            for index, tag in enumerate(tags):
                name_key = f"#tag{index}"
                zero_key = f":zero{index}"
                one_key = f":one{index}"
                expression_names[name_key] = tag
                expression_values[zero_key] = 0
                expression_values[one_key] = 1
                update_parts.append(f"#tags.{name_key} = if_not_exists(#tags.{name_key}, {zero_key}) + {one_key}")
            update_expression = "SET " + ", ".join(update_parts)
        else:
            remove_parts = [f"#tags.#tag{index}" for index, tag in enumerate(tags)]
            for index, tag in enumerate(tags):
                expression_names[f"#tag{index}"] = tag
            update_expression = "SET " + ", ".join(update_parts)
            if remove_parts:
                update_expression += " REMOVE " + ", ".join(remove_parts)

        result = self.table.update_item(
            Key={"ownerId": owner_id, "fileId": file_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values,
            ReturnValues="ALL_NEW",
        )
        attributes = result.get("Attributes", {})
        return attributes if isinstance(attributes, dict) else {}

    def delete_file(self, *, owner_id: str, file_id: str) -> dict[str, object] | None:
        """Delete one owner-scoped Files record and return its previous item."""
        result = self.table.delete_item(
            Key={"ownerId": owner_id, "fileId": file_id},
            ReturnValues="ALL_OLD",
        )
        attributes = result.get("Attributes", {})
        return attributes if isinstance(attributes, dict) else None

    def delete_files_by_urls(self, *, owner_id: str, urls: list[str]) -> list[dict[str, object]]:
        """Delete owned Files records selected by original or thumbnail URLs."""
        deleted: list[dict[str, object]] = []
        for url in urls:
            item = self.find_by_url(owner_id=owner_id, url=url)
            if item is None or "fileId" not in item:
                continue
            previous = self.delete_file(owner_id=owner_id, file_id=str(item["fileId"]))
            if previous is not None:
                deleted.append(previous)
        return deleted

    def mark_processing_ready(
        self,
        *,
        owner_id: str,
        file_id: str,
        tags: dict[str, int],
        model_version: str,
        updated_at: str,
    ) -> dict[str, object]:
        """Mark a file ready after ML inference and store its tag counts."""
        result = self.table.update_item(
            Key={
                "ownerId": owner_id,
                "fileId": file_id,
            },
            UpdateExpression=(
                "SET #status = :status, tags = :tags, "
                "modelVersion = :modelVersion, updatedAt = :updatedAt"
            ),
            ExpressionAttributeNames={
                "#status": "status",
            },
            ExpressionAttributeValues={
                ":status": "ready",
                ":tags": tags,
                ":modelVersion": model_version,
                ":updatedAt": updated_at,
            },
            ReturnValues="ALL_NEW",
        )
        attributes = result.get("Attributes", {})
        return attributes if isinstance(attributes, dict) else {}
