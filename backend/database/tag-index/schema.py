"""TagIndex item shape for tag-based media lookup."""

TAG_INDEX_TABLE_NAME = "TagIndex"

TAG_INDEX_ITEM_FIELDS = (
    "ownerTag",
    "tag",
    "ownerId",
    "fileId",
    "count",
    "source",
    "updatedAt",
)

TAG_SOURCE_AUTO = "auto"
TAG_SOURCE_MANUAL = "manual"


def build_tag_index_item(
    *,
    tag: str,
    owner_id: str,
    file_id: str,
    count: int,
    source: str,
    updated_at: str,
) -> dict[str, object]:
    """Create one TagIndex entry for a file/tag pair."""
    return {
        "ownerTag": f"{owner_id}#{tag}",
        "tag": tag,
        "ownerId": owner_id,
        "fileId": file_id,
        "count": count,
        "source": source,
        "updatedAt": updated_at,
    }
