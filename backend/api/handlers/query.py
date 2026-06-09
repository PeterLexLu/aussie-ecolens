"""Member C query and bulk tag API handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class FileQueryRepository(Protocol):
    def list_files(self, *, owner_id: str, limit: int = 50) -> list[dict[str, object]]:
        """List files for one owner."""

    def get_file(self, *, owner_id: str, file_id: str) -> dict[str, object] | None:
        """Fetch one owner-scoped file."""

    def find_by_url(self, *, owner_id: str, url: str) -> dict[str, object] | None:
        """Find one owner-scoped file by original or thumbnail URL."""

    def query_by_tag_counts(
        self,
        *,
        owner_id: str,
        requested_tags: dict[str, int],
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Find files whose tags satisfy all requested counts."""

    def apply_bulk_tag_update(
        self,
        *,
        owner_id: str,
        file_id: str,
        tags: list[str],
        operation: int,
        updated_at: str,
    ) -> dict[str, object]:
        """Update Files.tags for a manual tag operation."""


class TagIndexQueryRepository(Protocol):
    def save_manual_tags(
        self,
        *,
        owner_id: str,
        file_id: str,
        tags: list[str],
        updated_at: str,
    ) -> list[dict[str, object]]:
        """Write manual tags to TagIndex."""

    def delete_manual_tags(self, *, owner_id: str, file_id: str, tags: list[str]) -> int:
        """Delete manual tags from TagIndex."""


class QueryFileDetector(Protocol):
    def detect_tags(self, *, filename: str, content: bytes) -> dict[str, int]:
        """Detect tags for a temporary query file."""


@dataclass(frozen=True)
class QueryHandlers:
    """Owner-scoped query operations used by API routes."""

    files: FileQueryRepository
    tag_index: TagIndexQueryRepository
    detector: QueryFileDetector | None = None

    def list_files(self, *, owner_id: str, limit: int = 50) -> dict[str, object]:
        return {"files": self.files.list_files(owner_id=owner_id, limit=limit)}

    def get_file(self, *, owner_id: str, file_id: str) -> dict[str, object]:
        file_item = self.files.get_file(owner_id=owner_id, file_id=file_id)
        if file_item is None:
            return {"error": "File not found"}
        return {"file": file_item}

    def query_tags(self, *, owner_id: str, tags: dict[str, int]) -> dict[str, object]:
        requested = _normalise_tag_counts(tags)
        return {
            "results": self.files.query_by_tag_counts(
                owner_id=owner_id,
                requested_tags=requested,
            )
        }

    def query_species(self, *, owner_id: str, species: str) -> dict[str, object]:
        if not species:
            return {"error": "species is required"}
        return self.query_tags(owner_id=owner_id, tags={species: 1})

    def query_thumbnail(self, *, owner_id: str, thumbnail_url: str) -> dict[str, object]:
        file_item = self.files.find_by_url(owner_id=owner_id, url=thumbnail_url)
        if file_item is None:
            return {"error": "Thumbnail not found"}
        return {"file": file_item}

    def query_by_file(self, *, owner_id: str, filename: str, content: bytes) -> dict[str, object]:
        if self.detector is None:
            return {"error": "Query file detector is not configured"}
        detected = self.detector.detect_tags(filename=filename, content=content)
        requested = {tag: 1 for tag in detected}
        return {
            "detectedTags": detected,
            "results": self.files.query_by_tag_counts(
                owner_id=owner_id,
                requested_tags=requested,
            ),
        }

    def bulk_tags(
        self,
        *,
        owner_id: str,
        urls: list[str],
        tags: list[str],
        operation: int,
        updated_at: str,
    ) -> dict[str, object]:
        changed = 0
        for url in urls:
            file_item = self.files.find_by_url(owner_id=owner_id, url=url)
            if file_item is None:
                continue
            file_id = str(file_item["fileId"])
            self.files.apply_bulk_tag_update(
                owner_id=owner_id,
                file_id=file_id,
                tags=tags,
                operation=operation,
                updated_at=updated_at,
            )
            if operation == 1:
                self.tag_index.save_manual_tags(
                    owner_id=owner_id,
                    file_id=file_id,
                    tags=tags,
                    updated_at=updated_at,
                )
            else:
                self.tag_index.delete_manual_tags(
                    owner_id=owner_id,
                    file_id=file_id,
                    tags=tags,
                )
            changed += len(tags)
        return {"message": "Tags updated", "changes": changed}


def _normalise_tag_counts(tags: dict[str, object]) -> dict[str, int]:
    return {str(tag): int(count) for tag, count in tags.items()}
