"""Checksum lookup design for owner-scoped duplicate detection."""

from __future__ import annotations


CHECKSUM_INDEX_NAME = "OwnerChecksumIndex"
CHECKSUM_INDEX_PARTITION_KEY = "ownerId"
CHECKSUM_INDEX_SORT_KEY = "checksum"


def build_checksum_lookup_key(*, owner_id: str, checksum: str) -> dict[str, str]:
    """Build the key used to find duplicates for the current user only."""
    if not owner_id:
        raise ValueError("owner_id is required for checksum lookup.")
    if not checksum:
        raise ValueError("checksum is required for checksum lookup.")
    return {
        CHECKSUM_INDEX_PARTITION_KEY: owner_id,
        CHECKSUM_INDEX_SORT_KEY: checksum,
    }
