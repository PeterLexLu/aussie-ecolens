"""HTTP API Lambda for authenticated Aussie EcoLens cloud operations."""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
import urllib.request
import uuid
from email import policy
from email.parser import BytesParser
from pathlib import PurePath
from typing import Any

from boto3.dynamodb.conditions import Key

from .aws_common import (
    FILES_TABLE_NAME,
    NOTIFICATIONS_TABLE_NAME,
    ORIGINALS_BUCKET,
    QUERY_TEMP_BUCKET,
    SNS_TOPIC_ARN,
    SUBSCRIPTIONS_TABLE_NAME,
    TAG_INDEX_TABLE_NAME,
    THUMBNAILS_BUCKET,
    claims,
    file_view,
    files_table,
    jsonable,
    json_body,
    notifications_table,
    object_path,
    owner_tag,
    response,
    s3,
    sns,
    subscriptions_table,
    tag_index_table,
    upload_url,
    utc_now,
)

CHECKSUM = re.compile(r"^[a-fA-F0-9]{64}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_PAGE_LIMIT = int(os.getenv("DEFAULT_PAGE_LIMIT", "50"))
MAX_PAGE_LIMIT = int(os.getenv("MAX_PAGE_LIMIT", "100"))
FILE_ID_INDEX_NAME = os.getenv("FILE_ID_INDEX_NAME", "FileIdIndex")
CHECKSUM_INDEX_NAME = os.getenv("CHECKSUM_INDEX_NAME", "ChecksumIndex")
GCP_INFER_URL = os.getenv("GCP_INFER_URL", "").rstrip("/")
MODEL_VERSION = os.getenv("MODEL_VERSION", "2026-s1-v1")
VIDEO_FRAME_RATE_SECONDS = int(os.getenv("VIDEO_FRAME_RATE_SECONDS", "1"))
QUERY_INFER_TIMEOUT_SECONDS = int(os.getenv("QUERY_INFER_TIMEOUT_SECONDS", "90"))
COGNITO_REGION = os.getenv("COGNITO_REGION", "us-east-1")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
COGNITO_APP_CLIENT_ID = os.getenv("COGNITO_APP_CLIENT_ID", "")
COGNITO_DOMAIN = os.getenv("COGNITO_DOMAIN", "")
COGNITO_REDIRECT_URI = os.getenv("COGNITO_REDIRECT_URI", "")


def _headers(event: dict[str, Any]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in event.get("headers", {}).items()}


def _query_params(event: dict[str, Any]) -> dict[str, str]:
    params = event.get("queryStringParameters") or {}
    if isinstance(params, dict) and params:
        return {str(key): str(value) for key, value in params.items() if value is not None}
    return {key: values[-1] for key, values in urllib.parse.parse_qs(str(event.get("rawQueryString", ""))).items() if values}


def _page_limit(value: Any, default: int = DEFAULT_PAGE_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, MAX_PAGE_LIMIT))


def _encode_page_key(key: dict[str, Any] | None) -> str:
    if not key:
        return ""
    payload = json.dumps(jsonable(key), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_page_key(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        parsed = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _public_config(event: dict[str, Any]) -> dict[str, Any]:
    origin = _headers(event).get("origin", "")
    redirect_uri = COGNITO_REDIRECT_URI or origin or "http://localhost:8000/"
    login_url = ""
    token_url = ""
    if COGNITO_DOMAIN and COGNITO_APP_CLIENT_ID:
        query = urllib.parse.urlencode(
            {
                "client_id": COGNITO_APP_CLIENT_ID,
                "response_type": "code",
                "scope": "openid email",
                "redirect_uri": redirect_uri,
            }
        )
        login_url = f"https://{COGNITO_DOMAIN}/login?{query}"
        token_url = f"https://{COGNITO_DOMAIN}/oauth2/token"
    return {
        "authMode": "cognito",
        "apiBaseUrl": os.getenv("API_BASE_URL", ""),
        "cognito": {
            "region": COGNITO_REGION,
            "userPoolId": COGNITO_USER_POOL_ID,
            "appClientId": COGNITO_APP_CLIENT_ID,
            "domain": COGNITO_DOMAIN,
            "redirectUri": redirect_uri,
            "loginUrl": login_url,
            "tokenUrl": token_url,
        },
    }


def _body_bytes(event: dict[str, Any]) -> bytes:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(raw)
    return str(raw).encode("utf-8")


def _multipart_file(event: dict[str, Any]) -> tuple[str, str, bytes] | None:
    content_type = _headers(event).get("content-type", "")
    if "multipart/form-data" not in content_type:
        return None
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode("utf-8") + _body_bytes(event)
    )
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        if part.get_param("name", header="content-disposition") != "file":
            continue
        filename = PurePath(part.get_filename() or "query.bin").name
        file_type = part.get_content_type() or "application/octet-stream"
        return filename, file_type, part.get_payload(decode=True) or b""
    return None


def _media_type(content_type: str, filename: str = "") -> str:
    lowered = f"{content_type} {filename}".lower()
    return "video" if "video/" in lowered or lowered.endswith((".mp4", ".mov", ".avi")) else "image"


def _infer(media_url: str, media_type: str) -> dict[str, Any]:
    if not GCP_INFER_URL:
        raise RuntimeError("GCP inference endpoint is not configured.")
    payload = json.dumps(
        {
            "mediaUrl": media_url,
            "mediaType": media_type,
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
    with urllib.request.urlopen(request, timeout=QUERY_INFER_TIMEOUT_SECONDS) as result:
        parsed = json.load(result)
    return parsed if isinstance(parsed, dict) else {}


def _list_files(owner_id: str, limit: int = 100) -> list[dict[str, Any]]:
    result = files_table.query(
        IndexName="OwnerCreatedAtIndex",
        KeyConditionExpression=Key("ownerId").eq(owner_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [item for item in result.get("Items", []) if isinstance(item, dict)]


def _list_visible_files(limit: int = 500) -> list[dict[str, Any]]:
    result = files_table.scan(Limit=limit)
    return [item for item in result.get("Items", []) if isinstance(item, dict)]


def _scan_visible_files_page(limit: int, next_token: str | None = None) -> tuple[list[dict[str, Any]], str]:
    kwargs: dict[str, Any] = {"Limit": limit}
    start_key = _decode_page_key(next_token)
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    result = files_table.scan(**kwargs)
    items = [item for item in result.get("Items", []) if isinstance(item, dict)]
    return items, _encode_page_key(result.get("LastEvaluatedKey"))


def _find_file(owner_id: str, file_id: str) -> dict[str, Any] | None:
    result = files_table.get_item(Key={"ownerId": owner_id, "fileId": file_id})
    item = result.get("Item")
    return item if isinstance(item, dict) else None


def _find_visible_file(file_id: str) -> dict[str, Any] | None:
    try:
        result = files_table.query(
            IndexName=FILE_ID_INDEX_NAME,
            KeyConditionExpression=Key("fileId").eq(file_id),
            Limit=1,
        )
        items = result.get("Items", [])
        if items:
            item = items[0]
            return item if isinstance(item, dict) else None
    except Exception as error:
        print(f"FileIdIndex lookup unavailable, falling back: {error!r}")

    try:
        result = files_table.get_item(Key={"fileId": file_id})
        item = result.get("Item")
        if isinstance(item, dict):
            return item
    except Exception as error:
        print(f"fileId primary-key lookup unavailable, falling back: {error!r}")

    for item in _list_visible_files(limit=500):
        if str(item.get("fileId", "")) == file_id:
            return item
    return None


def _best_duplicate_match(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    ready = [item for item in items if str(item.get("status", "")) == "ready"]
    return (ready or items)[0]


def _find_by_checksum(checksum: str) -> dict[str, Any] | None:
    try:
        result = files_table.query(
            IndexName=CHECKSUM_INDEX_NAME,
            KeyConditionExpression=Key("checksum").eq(checksum),
            Limit=10,
        )
        return _best_duplicate_match([item for item in result.get("Items", []) if isinstance(item, dict)])
    except Exception as error:
        print(f"ChecksumIndex lookup unavailable, falling back: {error!r}")

    result = files_table.scan(Limit=500)
    items = [
        item
        for item in result.get("Items", [])
        if isinstance(item, dict) and str(item.get("checksum", "")).lower() == checksum
    ]
    return _best_duplicate_match(items)


def _find_by_url(owner_id: str, url: str) -> dict[str, Any] | None:
    protected = _protected_media_reference(url)
    if protected is not None:
        file_id, _kind = protected
        return _find_file(owner_id, file_id)
    path = object_path(url)
    for item in _list_files(owner_id, limit=500):
        if path in {str(item.get("objectKey", "")), str(item.get("thumbnailKey", ""))}:
            return item
    return None


def _find_visible_by_url(url: str) -> dict[str, Any] | None:
    protected = _protected_media_reference(url)
    if protected is not None:
        file_id, _kind = protected
        return _find_visible_file(file_id)
    path = object_path(url)
    for item in _list_visible_files(limit=500):
        if path in {str(item.get("objectKey", "")), str(item.get("thumbnailKey", ""))}:
            return item
    return None


def _protected_media_reference(url: str) -> tuple[str, str] | None:
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    parts = [part for part in path.split("/") if part]
    if len(parts) == 4 and parts[:2] == ["api", "media"] and parts[3] in {"original", "thumbnail"}:
        return parts[2], parts[3]
    return None


def _visible_file_view(item: dict[str, Any], current_owner_id: str) -> dict[str, Any]:
    view = file_view(item)
    is_owner = str(item.get("ownerId", "")) == current_owner_id
    view["isOwner"] = is_owner
    view["canDelete"] = is_owner
    return view


def _media_response(item: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == "thumbnail":
        bucket = THUMBNAILS_BUCKET
        key = str(item.get("thumbnailKey", ""))
    else:
        bucket = ORIGINALS_BUCKET
        key = str(item.get("objectKey", ""))
    if not key:
        return response(404, {"message": "Media object is not available"})

    result = s3.get_object(Bucket=bucket, Key=key)
    body = result["Body"].read()
    content_type = str(result.get("ContentType") or ("image/jpeg" if kind == "thumbnail" else "application/octet-stream"))
    return {
        "statusCode": 200,
        "headers": {
            "content-type": content_type,
            "cache-control": "private, max-age=60",
            "access-control-allow-origin": os.getenv("CORS_ORIGIN", "*"),
            "access-control-allow-headers": "authorization,content-type",
            "access-control-allow-methods": "GET,POST,OPTIONS",
        },
        "isBase64Encoded": True,
        "body": base64.b64encode(body).decode("ascii"),
    }


def _delete_file(owner_id: str, item: dict[str, Any]) -> None:
    for bucket, key_name in (
        (ORIGINALS_BUCKET, "objectKey"),
        (ORIGINALS_BUCKET, "pendingKey"),
        (THUMBNAILS_BUCKET, "thumbnailKey"),
    ):
        key = str(item.get(key_name, ""))
        if key:
            s3.delete_object(Bucket=bucket, Key=key)
    tags = item.get("tags", {})
    if isinstance(tags, dict):
        for tag in tags:
            tag_index_table.delete_item(Key={"ownerTag": owner_tag(owner_id, tag), "fileId": item["fileId"]})
    files_table.delete_item(Key={"ownerId": owner_id, "fileId": item["fileId"]})


def _upload_init(owner_id: str, body: dict[str, Any]) -> dict[str, Any]:
    filename = PurePath(str(body.get("filename", "upload.bin"))).name
    checksum = str(body.get("checksum", "")).lower()
    content_type = str(body.get("contentType", "application/octet-stream"))
    if not filename or not CHECKSUM.match(checksum):
        return response(400, {"message": "filename and SHA-256 checksum are required"})

    existing = _find_by_checksum(checksum)
    if existing is not None:
        return response(
            200,
            {
                "duplicate": True,
                "message": "Duplicate file already exists in the platform. Showing the existing media record.",
                "file": _visible_file_view(existing, owner_id),
            },
        )

    file_id = str(uuid.uuid4())
    pending_key = f"users/{owner_id}/pending/{file_id}/{filename}"
    created_at = utc_now()
    item = {
        "ownerId": owner_id,
        "fileId": file_id,
        "originalName": filename,
        "pendingKey": pending_key,
        "objectKey": "",
        "thumbnailKey": "",
        "fileType": content_type,
        "checksum": checksum,
        "status": "pending",
        "tags": {},
        "modelVersion": "",
        "createdAt": created_at,
        "updatedAt": created_at,
    }
    files_table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(ownerId) AND attribute_not_exists(fileId)",
    )
    return response(
        201,
        {
            "duplicate": False,
            "file": file_view(item),
            "upload": {
                "method": "PUT",
                "url": upload_url(ORIGINALS_BUCKET, pending_key, content_type),
                "headers": {"content-type": content_type},
            },
        },
    )


def _query_tags(owner_id: str, body: dict[str, Any]) -> dict[str, Any]:
    requested = body.get("tags", body)
    normalized = {str(tag): int(count) for tag, count in requested.items() if int(count) > 0}
    limit = _page_limit(body.get("limit"), default=DEFAULT_PAGE_LIMIT)
    files, next_token = _matching_visible_files(owner_id, normalized, limit=limit, next_token=body.get("nextToken"))
    return response(200, {"files": files, "results": files, "nextToken": next_token, "limit": limit})


def _matching_visible_files(
    current_owner_id: str,
    requested: dict[str, int],
    limit: int = DEFAULT_PAGE_LIMIT,
    next_token: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    files = []
    items, next_token = _scan_visible_files_page(limit=limit, next_token=next_token)
    for item in items:
        tags = item.get("tags", {})
        if isinstance(tags, dict) and all(int(tags.get(tag, 0)) >= count for tag, count in requested.items()):
            files.append(_visible_file_view(item, current_owner_id))
    return files, next_token


def _query_by_file(owner_id: str, event: dict[str, Any]) -> dict[str, Any]:
    temp_key = ""
    try:
        body = {}
        if "application/json" in _headers(event).get("content-type", ""):
            body = json_body(event)

        filename = PurePath(str(body.get("filename", "query.bin"))).name
        content_type = str(body.get("contentType", "application/octet-stream"))
        media_url = str(body.get("mediaUrl", "")).strip()
        if not media_url and body.get("fileBase64"):
            data = base64.b64decode(str(body["fileBase64"]))
            temp_key = f"users/{owner_id}/query/{uuid.uuid4()}/{filename}"
            s3.put_object(Bucket=QUERY_TEMP_BUCKET, Key=temp_key, Body=data, ContentType=content_type)
            media_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": QUERY_TEMP_BUCKET, "Key": temp_key},
                ExpiresIn=300,
            )
        if not media_url:
            multipart = _multipart_file(event)
            if multipart is None:
                return response(400, {"message": "Query file or mediaUrl is required"})
            filename, content_type, data = multipart
            if not data:
                return response(400, {"message": "Query file is empty"})
            temp_key = f"users/{owner_id}/query/{uuid.uuid4()}/{filename}"
            s3.put_object(Bucket=QUERY_TEMP_BUCKET, Key=temp_key, Body=data, ContentType=content_type)
            media_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": QUERY_TEMP_BUCKET, "Key": temp_key},
                ExpiresIn=300,
            )

        inferred = _infer(media_url, _media_type(content_type, filename))
        detected_tags = {
            str(tag): int(count)
            for tag, count in inferred.get("tags", {}).items()
            if int(count) > 0
        }
        files, next_token = _matching_visible_files(owner_id, detected_tags)
        return response(
            200,
            {
                "detectedTags": detected_tags,
                "tags": detected_tags,
                "detections": inferred.get("detections", []),
                "modelVersion": str(inferred.get("modelVersion", MODEL_VERSION)),
                "mediaType": str(inferred.get("mediaType", _media_type(content_type, filename))),
                "files": files,
                "results": files,
                "nextToken": next_token,
                "limit": DEFAULT_PAGE_LIMIT,
            },
        )
    finally:
        if temp_key:
            s3.delete_object(Bucket=QUERY_TEMP_BUCKET, Key=temp_key)


def _bulk_tags(owner_id: str, body: dict[str, Any]) -> dict[str, Any]:
    operation = int(body.get("operation", 1))
    tags = [str(tag).strip() for tag in body.get("tags", []) if str(tag).strip()]
    urls = [str(url) for url in body.get("urls", [])]
    changed = 0
    for url in urls:
        item = _find_by_url(owner_id, url)
        if item is None:
            continue
        current = dict(item.get("tags", {}))
        for tag in tags:
            if operation == 1:
                current[tag] = int(current.get(tag, 0)) + 1
                tag_index_table.put_item(
                    Item={
                        "ownerTag": owner_tag(owner_id, tag),
                        "fileId": item["fileId"],
                        "tag": tag,
                        "ownerId": owner_id,
                        "count": current[tag],
                        "source": "manual",
                        "updatedAt": utc_now(),
                    }
                )
            else:
                current.pop(tag, None)
                tag_index_table.delete_item(Key={"ownerTag": owner_tag(owner_id, tag), "fileId": item["fileId"]})
        files_table.update_item(
            Key={"ownerId": owner_id, "fileId": item["fileId"]},
            UpdateExpression="SET tags = :tags, updatedAt = :updated",
            ExpressionAttributeValues={":tags": current, ":updated": utc_now()},
        )
        changed += 1
    return response(200, {"message": "Tags updated", "changed": changed, "changes": changed})


def _subscribe_to_notifications(owner_id: str, cognito_email: str, body: dict[str, Any]) -> dict[str, Any]:
    tag = str(body.get("tag", "")).strip()
    email = str(body.get("email") or cognito_email).strip()
    if not tag or not email:
        return response(400, {"message": "Email and tag are required"})
    if not EMAIL.match(email):
        return response(400, {"message": "A valid email address is required"})

    owner_tag_value = owner_tag(owner_id, tag)
    item = {
        "ownerTag": owner_tag_value,
        "subscriptionId": str(uuid.uuid4()),
        "ownerId": owner_id,
        "email": email,
        "tag": tag,
        "createdAt": utc_now(),
    }
    sns_status = "not-configured"
    if SNS_TOPIC_ARN:
        result = sns.subscribe(
            TopicArn=SNS_TOPIC_ARN,
            Protocol="email",
            Endpoint=email,
            ReturnSubscriptionArn=True,
            Attributes={"FilterPolicy": json.dumps({"ownerTag": [owner_tag_value]})},
        )
        sns_subscription_arn = str(result.get("SubscriptionArn", ""))
        item["snsSubscriptionArn"] = sns_subscription_arn
        sns_status = "pending-confirmation"

    subscriptions_table.put_item(Item=item)
    return response(
        201,
        {
            "subscription": item,
            "snsStatus": sns_status,
            "message": "Subscription saved. Confirm the AWS SNS email before notification emails can be delivered.",
        },
    )


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method", "")
        path = event.get("rawPath", "")
        if method == "OPTIONS":
            return response(204, {})
        if method == "GET" and path == "/api/config":
            return response(200, _public_config(event))

        user_claims = claims(event)
        owner_id = user_claims["sub"]

        if method == "GET" and path == "/api/me":
            return response(
                200,
                {
                    "authenticated": True,
                    "user": {
                        "ownerId": owner_id,
                        "email": user_claims.get("email", ""),
                    },
                },
            )
        if method == "POST" and path == "/api/uploads/init":
            return _upload_init(owner_id, json_body(event))
        if method == "GET" and path == "/api/files":
            params = _query_params(event)
            limit = _page_limit(params.get("limit"), default=DEFAULT_PAGE_LIMIT)
            items, next_token = _scan_visible_files_page(limit=limit, next_token=params.get("nextToken"))
            return response(
                200,
                {
                    "files": [_visible_file_view(item, owner_id) for item in items],
                    "nextToken": next_token,
                    "limit": limit,
                },
            )
        if method == "GET" and path.startswith("/api/files/"):
            item = _find_visible_file(path.rsplit("/", 1)[-1])
            return response(200, {"file": _visible_file_view(item, owner_id)}) if item else response(404, {"message": "File not found"})
        if method == "GET" and path.startswith("/api/media/"):
            protected = _protected_media_reference(path)
            if protected is None:
                return response(404, {"message": "Media route not found"})
            file_id, kind = protected
            item = _find_visible_file(file_id)
            return _media_response(item, kind) if item else response(404, {"message": "File not found"})
        if method == "POST" and path == "/api/query/tags":
            return _query_tags(owner_id, json_body(event))
        if method == "POST" and path == "/api/query/species":
            body = json_body(event)
            species = str(body.get("species", "")).strip()
            query_body = {**body, "tags": {species: 1} if species else {}}
            return _query_tags(owner_id, query_body)
        if method == "POST" and path == "/api/query/thumbnail":
            item = _find_visible_by_url(str(json_body(event).get("thumbnailUrl", "")))
            files = [_visible_file_view(item, owner_id)] if item else []
            return response(200, {"file": files[0] if files else None, "files": files, "results": files})
        if method == "POST" and path == "/api/query/by-file":
            return _query_by_file(owner_id, event)
        if method == "POST" and path == "/api/tags/bulk":
            return _bulk_tags(owner_id, json_body(event))
        if method == "POST" and path == "/api/files/delete":
            deleted = 0
            for url in json_body(event).get("urls", []):
                item = _find_by_url(owner_id, str(url))
                if item is not None:
                    _delete_file(owner_id, item)
                    deleted += 1
            return response(200, {"message": "Files deleted", "deleted": deleted})
        if method == "POST" and path == "/api/subscribe":
            return _subscribe_to_notifications(owner_id, user_claims.get("email", "").strip(), json_body(event))
        if method == "GET" and path == "/api/notifications":
            result = notifications_table.query(KeyConditionExpression=Key("ownerId").eq(owner_id), Limit=50)
            return response(200, {"notifications": result.get("Items", [])})
        return response(404, {"message": f"Unsupported route: {method} {path}"})
    except PermissionError as error:
        return response(401, {"message": str(error)})
    except Exception as error:  # Lambda logs retain the traceback for diagnosis.
        print(f"API handler error: {error!r}")
        return response(500, {"message": "Internal server error"})
