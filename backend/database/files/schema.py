"""Files table item shape for Member C database work."""

FILES_TABLE_NAME = "Files"

FILE_STATUS_PENDING = "pending"
FILE_STATUS_READY = "ready"
FILE_STATUS_FAILED = "failed"

FILE_ITEM_FIELDS = (
    "fileId",
    "ownerId",
    "originalName",
    "objectKey",
    "fileType",
    "checksum",
    "status",
    "thumbnailKey",
    "tags",
    "modelVersion",
    "createdAt",
    "updatedAt",
)

OWNER_CHECKSUM_INDEX_NAME = "OwnerChecksumIndex"
OWNER_CHECKSUM_INDEX_PURPOSE = "Find duplicate uploads by checksum within one owner scope."
OWNER_CHECKSUM_INDEX_FIELDS = (
    "ownerId",
    "checksum",
)

OWNER_CREATED_AT_INDEX_NAME = "OwnerCreatedAtIndex"
OWNER_CREATED_AT_INDEX_PURPOSE = "List one owner's files in newest-first order."
OWNER_CREATED_AT_INDEX_FIELDS = (
    "ownerId",
    "createdAt",
)

FILE_ID_INDEX_NAME = "FileIdIndex"
FILE_ID_INDEX_PURPOSE = "Lookup shared/protected media records by fileId without scanning the Files table."
FILE_ID_INDEX_FIELDS = (
    "fileId",
)


def build_pending_file_item(
    *,
    file_id: str,
    owner_id: str,
    original_name: str,
    object_key: str,
    file_type: str,
    checksum: str,
    created_at: str,
) -> dict[str, object]:
    """Create the initial Files item before ML processing runs."""
    if not owner_id:
        raise ValueError("owner_id is required for Files records.")
    if not checksum:
        raise ValueError("checksum is required for duplicate lookup.")
    return {
        "fileId": file_id,
        "ownerId": owner_id,
        "originalName": original_name,
        "objectKey": object_key,
        "fileType": file_type,
        "checksum": checksum,
        "status": FILE_STATUS_PENDING,
        "thumbnailKey": None,
        "tags": {},
        "modelVersion": None,
        "createdAt": created_at,
        "updatedAt": created_at,
    }
