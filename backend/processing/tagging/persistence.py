"""Persist ML processing results to Files and TagIndex."""

from __future__ import annotations

from typing import Protocol


class FileStatusWriter(Protocol):
    def mark_processing_ready(
        self,
        *,
        owner_id: str,
        file_id: str,
        tags: dict[str, int],
        model_version: str,
        updated_at: str,
    ) -> dict[str, object]:
        """Mark a file as ready after inference."""


class TagWriter(Protocol):
    def save_inference_tags(
        self,
        *,
        owner_id: str,
        file_id: str,
        tags: dict[str, int],
        updated_at: str,
    ) -> list[dict[str, object]]:
        """Save tag index rows."""


def persist_processing_result(
    *,
    files: FileStatusWriter,
    tag_index: TagWriter,
    owner_id: str,
    file_id: str,
    tags: dict[str, int],
    model_version: str,
    updated_at: str,
) -> dict[str, object]:
    """Write inference tags to both Files and TagIndex."""
    tag_index.save_inference_tags(
        owner_id=owner_id,
        file_id=file_id,
        tags=tags,
        updated_at=updated_at,
    )
    return files.mark_processing_ready(
        owner_id=owner_id,
        file_id=file_id,
        tags=tags,
        model_version=model_version,
        updated_at=updated_at,
    )
