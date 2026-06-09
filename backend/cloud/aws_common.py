"""Shared helpers for AWS Lambda handlers."""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3

REGION = os.getenv("AWS_REGION", "us-east-1")
ORIGINALS_BUCKET = os.environ["ORIGINALS_BUCKET"]
THUMBNAILS_BUCKET = os.environ["THUMBNAILS_BUCKET"]
QUERY_TEMP_BUCKET = os.environ["QUERY_TEMP_BUCKET"]
FILES_TABLE_NAME = os.getenv("FILES_TABLE_NAME", "Files")
TAG_INDEX_TABLE_NAME = os.getenv("TAG_INDEX_TABLE_NAME", "TagIndex")
SUBSCRIPTIONS_TABLE_NAME = os.getenv("SUBSCRIPTIONS_TABLE_NAME", "Subscriptions")
NOTIFICATIONS_TABLE_NAME = os.getenv("NOTIFICATIONS_TABLE_NAME", "Notifications")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN", "")
DOWNLOAD_URL_SECONDS = int(os.getenv("DOWNLOAD_URL_SECONDS", "900"))
UPLOAD_URL_SECONDS = int(os.getenv("UPLOAD_URL_SECONDS", "900"))

s3 = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
files_table = dynamodb.Table(FILES_TABLE_NAME)
tag_index_table = dynamodb.Table(TAG_INDEX_TABLE_NAME)
subscriptions_table = dynamodb.Table(SUBSCRIPTIONS_TABLE_NAME)
notifications_table = dynamodb.Table(NOTIFICATIONS_TABLE_NAME)
sns = boto3.client("sns", region_name=REGION)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def owner_tag(owner_id: str, tag: str) -> str:
    return f"{owner_id}#{tag.strip()}"


def json_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": os.getenv("CORS_ORIGIN", "*"),
            "access-control-allow-headers": "authorization,content-type",
            "access-control-allow-methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(jsonable(body), separators=(",", ":")),
    }


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def claims(event: dict[str, Any]) -> dict[str, str]:
    authorizer = event.get("requestContext", {}).get("authorizer", {})
    values = authorizer.get("jwt", {}).get("claims", {})
    if not isinstance(values, dict) or not values.get("sub"):
        raise PermissionError("Missing authenticated Cognito subject.")
    return {str(key): str(value) for key, value in values.items()}


def download_url(bucket: str, key: str) -> str:
    if not key:
        return ""
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=DOWNLOAD_URL_SECONDS,
    )


def upload_url(bucket: str, key: str, content_type: str) -> str:
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=UPLOAD_URL_SECONDS,
    )


def object_path(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlparse(url).path).lstrip("/")


def file_view(item: dict[str, Any]) -> dict[str, Any]:
    result = jsonable(dict(item))
    file_id = urllib.parse.quote(str(item.get("fileId", "")), safe="")
    result["originalUrl"] = f"/api/media/{file_id}/original" if item.get("objectKey") else ""
    result["thumbnailUrl"] = f"/api/media/{file_id}/thumbnail" if item.get("thumbnailKey") else ""
    return result
