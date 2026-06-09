"""S3-triggered Lambda for durable media processing handoff."""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
import uuid
from typing import Any

from boto3.dynamodb.conditions import Key

from .aws_common import (
    ORIGINALS_BUCKET,
    SNS_TOPIC_ARN,
    THUMBNAILS_BUCKET,
    files_table,
    notifications_table,
    owner_tag,
    s3,
    sns,
    subscriptions_table,
    tag_index_table,
    utc_now,
)

GCP_INFER_URL = os.getenv("GCP_INFER_URL", "").rstrip("/")
MODEL_VERSION = os.getenv("MODEL_VERSION", "2026-s1-v1")
INFER_TIMEOUT_SECONDS = int(os.getenv("INFER_TIMEOUT_SECONDS", "70"))
VIDEO_FRAME_RATE_SECONDS = int(os.getenv("VIDEO_FRAME_RATE_SECONDS", "1"))


def _parse_pending_key(key: str) -> tuple[str, str, str] | None:
    parts = key.split("/")
    if len(parts) < 5 or parts[0] != "users" or parts[2] != "pending":
        return None
    return parts[1], parts[3], "/".join(parts[4:])


def _s3_keys_from_records(records: list[dict[str, Any]]) -> list[str]:
    keys = []
    for record in records:
        if "s3" not in record:
            continue
        key = record.get("s3", {}).get("object", {}).get("key")
        if isinstance(key, str) and key:
            keys.append(urllib.parse.unquote_plus(key))
    return keys


def _source_keys_from_event(event: dict[str, Any]) -> list[str]:
    keys = []
    for record in event.get("Records", []):
        if "s3" in record:
            keys.extend(_s3_keys_from_records([record]))
            continue

        body = record.get("body")
        if not isinstance(body, str):
            continue
        try:
            parsed_body = json.loads(body)
        except json.JSONDecodeError:
            continue
        body_records = parsed_body.get("Records", [])
        if isinstance(body_records, list):
            keys.extend(_s3_keys_from_records(body_records))
    return keys


def _infer(source_key: str, filename: str, content_type: str) -> dict[str, Any]:
    if not GCP_INFER_URL:
        return {"tags": {}, "modelVersion": "gcp-not-configured"}
    source_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": ORIGINALS_BUCKET, "Key": source_key},
        ExpiresIn=900,
    )
    payload = json.dumps(
        {
            "mediaUrl": source_url,
            "fileName": filename,
            "mediaType": "video" if content_type.startswith("video/") else "image",
            "modelVersion": MODEL_VERSION,
            "frameRateSeconds": VIDEO_FRAME_RATE_SECONDS,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{GCP_INFER_URL}/infer",
        data=payload,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=INFER_TIMEOUT_SECONDS) as result:
        parsed = json.load(result)
    return parsed if isinstance(parsed, dict) else {}


def _publish_notifications(owner_id: str, file_id: str, file_key: str, tags: dict[str, int]) -> None:
    published_owner_tags: set[str] = set()
    for tag in tags:
        owner_tag_value = owner_tag(owner_id, tag)
        result = subscriptions_table.query(
            KeyConditionExpression=Key("ownerTag").eq(owner_tag_value)
        )
        for subscription in result.get("Items", []):
            item = {
                "ownerId": owner_id,
                "notificationId": str(uuid.uuid4()),
                "email": subscription.get("email", ""),
                "tag": tag,
                "fileId": file_id,
                "fileUrl": f"/api/media/{file_id}/original",
                "objectKey": file_key,
                "createdAt": utc_now(),
            }
            notifications_table.put_item(Item=item)
            if SNS_TOPIC_ARN and owner_tag_value not in published_owner_tags:
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject="Aussie EcoLens species match",
                    Message=json.dumps(item),
                    MessageAttributes={
                        "ownerTag": {"DataType": "String", "StringValue": owner_tag_value},
                        "ownerId": {"DataType": "String", "StringValue": owner_id},
                        "tag": {"DataType": "String", "StringValue": tag},
                    },
                )
                published_owner_tags.add(owner_tag_value)


def _process(source_key: str) -> None:
    parsed_key = _parse_pending_key(source_key)
    if parsed_key is None:
        return
    owner_id, file_id, filename = parsed_key
    existing = files_table.get_item(Key={"ownerId": owner_id, "fileId": file_id}).get("Item")
    if not isinstance(existing, dict):
        raise ValueError(f"Missing Files record for {owner_id}/{file_id}")

    metadata = s3.head_object(Bucket=ORIGINALS_BUCKET, Key=source_key)
    content_type = str(metadata.get("ContentType", "application/octet-stream"))
    inferred = _infer(source_key, filename, content_type)
    tags = {str(tag): int(count) for tag, count in inferred.get("tags", {}).items() if int(count) > 0}
    primary_species = next(iter(tags), "unclassified")
    destination_key = f"users/{owner_id}/species/{primary_species}/{file_id}/{filename}"
    s3.copy_object(
        Bucket=ORIGINALS_BUCKET,
        Key=destination_key,
        CopySource={"Bucket": ORIGINALS_BUCKET, "Key": source_key},
        ContentType=content_type,
        MetadataDirective="REPLACE",
    )
    s3.delete_object(Bucket=ORIGINALS_BUCKET, Key=source_key)

    thumbnail_key = ""
    thumbnail_base64 = str(inferred.get("thumbnailBase64", ""))
    if thumbnail_base64:
        thumbnail_key = f"users/{owner_id}/thumbnails/{file_id}.jpg"
        s3.put_object(
            Bucket=THUMBNAILS_BUCKET,
            Key=thumbnail_key,
            Body=base64.b64decode(thumbnail_base64),
            ContentType="image/jpeg",
        )

    updated_at = utc_now()
    for tag, count in tags.items():
        tag_index_table.put_item(
            Item={
                "ownerTag": owner_tag(owner_id, tag),
                "fileId": file_id,
                "tag": tag,
                "ownerId": owner_id,
                "count": count,
                "source": "auto",
                "updatedAt": updated_at,
            }
        )

    status = "ready" if tags and thumbnail_key else "awaiting-gcp"
    files_table.update_item(
        Key={"ownerId": owner_id, "fileId": file_id},
        UpdateExpression=(
            "SET #status = :status, objectKey = :objectKey, thumbnailKey = :thumbnailKey, "
            "tags = :tags, modelVersion = :modelVersion, updatedAt = :updatedAt"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": status,
            ":objectKey": destination_key,
            ":thumbnailKey": thumbnail_key,
            ":tags": tags,
            ":modelVersion": str(inferred.get("modelVersion", MODEL_VERSION)),
            ":updatedAt": updated_at,
        },
    )
    _publish_notifications(owner_id, file_id, destination_key, tags)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    processed = 0
    for source_key in _source_keys_from_event(event):
        _process(source_key)
        processed += 1
    return {"processed": processed}
