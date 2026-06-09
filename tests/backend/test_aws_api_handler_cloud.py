"""Tests for the AWS HTTP API Lambda cloud contract."""

from __future__ import annotations

import base64
import importlib
import json
import sys
import types
import urllib.parse
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class FakeCondition:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def __and__(self, other: "FakeCondition") -> "FakeCondition":
        return FakeCondition({**self.values, **other.values})


class FakeKey:
    def __init__(self, name: str) -> None:
        self.name = name

    def eq(self, value: object) -> FakeCondition:
        return FakeCondition({self.name: value})


class FakeS3:
    def __init__(self) -> None:
        self.puts: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> None:
        self.puts.append(kwargs)

    def delete_object(self, **kwargs: object) -> None:
        self.deletes.append(kwargs)

    def get_object(self, **kwargs: object) -> dict[str, object]:
        key = str(kwargs["Key"])
        content_type = "image/jpeg" if key.endswith((".jpg", ".jpeg")) else "application/octet-stream"
        return {"Body": FakeBody(f"bytes:{key}".encode("utf-8")), "ContentType": content_type}

    def generate_presigned_url(self, _operation: str, Params: dict[str, str], ExpiresIn: int) -> str:
        return f"https://signed.example/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"


class FakeSns:
    def __init__(self) -> None:
        self.subscriptions: list[dict[str, object]] = []

    def subscribe(self, **kwargs: object) -> dict[str, object]:
        self.subscriptions.append(kwargs)
        return {"SubscriptionArn": "pending confirmation"}


class FakeBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class FakeTable:
    def __init__(self, items: list[dict[str, object]] | None = None) -> None:
        self.items = items or []
        self.queries: list[dict[str, object]] = []
        self.scans: list[dict[str, object]] = []
        self.puts: list[dict[str, object]] = []

    def query(self, **kwargs: object) -> dict[str, object]:
        self.queries.append(kwargs)
        condition = kwargs.get("KeyConditionExpression")
        values = getattr(condition, "values", {})
        items = [
            item
            for item in self.items
            if all(item.get(key) == value for key, value in values.items())
        ]
        return {"Items": items[: int(kwargs.get("Limit", len(items)))]}

    def scan(self, **kwargs: object) -> dict[str, object]:
        self.scans.append(kwargs)
        start = 0
        start_key = kwargs.get("ExclusiveStartKey")
        if isinstance(start_key, dict):
            for index, item in enumerate(self.items):
                if item.get("ownerId") == start_key.get("ownerId") and item.get("fileId") == start_key.get("fileId"):
                    start = index + 1
                    break
        limit = int(kwargs.get("Limit", len(self.items)))
        page = self.items[start:start + limit]
        result: dict[str, object] = {"Items": page}
        if start + limit < len(self.items) and page:
            last = page[-1]
            result["LastEvaluatedKey"] = {"ownerId": last.get("ownerId"), "fileId": last.get("fileId")}
        return result

    def get_item(self, Key: dict[str, object]) -> dict[str, object]:
        for item in self.items:
            if all(item.get(key) == value for key, value in Key.items()):
                return {"Item": item}
        return {}

    def put_item(self, **kwargs: object) -> None:
        self.puts.append(kwargs)
        item = kwargs.get("Item")
        if isinstance(item, dict):
            self.items.append(item)

    def update_item(self, **_kwargs: object) -> None:
        return None

    def delete_item(self, **_kwargs: object) -> None:
        return None


class FakeDynamoResource:
    def __init__(self, files: FakeTable, subscriptions: FakeTable | None = None) -> None:
        self.files = files
        self.subscriptions = subscriptions or FakeTable()
        self.tables: dict[str, FakeTable] = {
            "Files": self.files,
            "Subscriptions": self.subscriptions,
        }

    def Table(self, name: str) -> FakeTable:
        if name not in self.tables:
            self.tables[name] = FakeTable()
        return self.tables[name]


class FakeUrlOpenResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeUrlOpenResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def load_handler(monkeypatch, files: list[dict[str, object]] | None = None):
    fake_s3 = FakeS3()
    fake_sns = FakeSns()
    fake_files = FakeTable(files)
    fake_subscriptions = FakeTable()
    fake_s3.files_table = fake_files
    fake_s3.sns = fake_sns
    fake_s3.subscriptions_table = fake_subscriptions

    boto3_module = types.ModuleType("boto3")
    boto3_module.client = lambda service, **_kwargs: fake_s3 if service == "s3" else fake_sns
    boto3_module.resource = lambda service, **_kwargs: FakeDynamoResource(fake_files, fake_subscriptions)
    conditions_module = types.ModuleType("boto3.dynamodb.conditions")
    conditions_module.Key = FakeKey
    dynamodb_module = types.ModuleType("boto3.dynamodb")
    dynamodb_module.conditions = conditions_module
    monkeypatch.setitem(sys.modules, "boto3", boto3_module)
    monkeypatch.setitem(sys.modules, "boto3.dynamodb", dynamodb_module)
    monkeypatch.setitem(sys.modules, "boto3.dynamodb.conditions", conditions_module)

    monkeypatch.setenv("ORIGINALS_BUCKET", "originals")
    monkeypatch.setenv("THUMBNAILS_BUCKET", "thumbnails")
    monkeypatch.setenv("QUERY_TEMP_BUCKET", "query-temp")
    monkeypatch.setenv("GCP_INFER_URL", "https://gcp.example")
    monkeypatch.setenv("MODEL_VERSION", "2026-s1-v1")
    monkeypatch.setenv("COGNITO_REGION", "us-east-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_example")
    monkeypatch.setenv("COGNITO_APP_CLIENT_ID", "client123")
    monkeypatch.setenv("COGNITO_DOMAIN", "example.auth.us-east-1.amazoncognito.com")
    monkeypatch.setenv("COGNITO_REDIRECT_URI", "http://localhost:8000/")
    monkeypatch.setenv("API_BASE_URL", "https://api.example")
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:aussie-ecolens-notifications")

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    for name in ["backend.cloud.aws_api_handler", "backend.cloud.aws_common"]:
        sys.modules.pop(name, None)

    module = importlib.import_module("backend.cloud.aws_api_handler")
    return module, fake_s3


def event(
    method: str,
    path: str,
    body: dict[str, object] | None = None,
    claims: dict[str, str] | None = None,
    query: dict[str, object] | None = None,
):
    request_context: dict[str, object] = {"http": {"method": method}}
    if claims is not None:
        request_context["authorizer"] = {"jwt": {"claims": claims}}
    return {
        "requestContext": request_context,
        "rawPath": path,
        "rawQueryString": urllib.parse.urlencode(query or {}),
        "queryStringParameters": {str(key): str(value) for key, value in (query or {}).items()},
        "headers": {"content-type": "application/json", "origin": "http://localhost:8000"},
        "body": json.dumps(body or {}),
        "isBase64Encoded": False,
    }


def parse_body(result: dict[str, object]) -> dict[str, object]:
    return json.loads(str(result["body"]))


def test_options_preflight_does_not_require_claims(monkeypatch) -> None:
    handler, _fake_s3 = load_handler(monkeypatch)

    result = handler.lambda_handler(event("OPTIONS", "/api/query/by-file"), None)

    assert result["statusCode"] == 204
    assert result["headers"]["access-control-allow-methods"] == "GET,POST,OPTIONS"
    assert result["headers"]["access-control-allow-headers"] == "authorization,content-type"


def test_config_is_public_and_returns_cognito_hosted_ui(monkeypatch) -> None:
    handler, _fake_s3 = load_handler(monkeypatch)

    result = handler.lambda_handler(event("GET", "/api/config"), None)

    assert result["statusCode"] == 200
    body = parse_body(result)
    assert body["apiBaseUrl"] == "https://api.example"
    assert body["cognito"]["appClientId"] == "client123"
    assert "response_type=code" in body["cognito"]["loginUrl"]
    assert body["cognito"]["tokenUrl"] == "https://example.auth.us-east-1.amazoncognito.com/oauth2/token"


def test_file_response_serializes_dynamodb_decimal_tags(monkeypatch) -> None:
    files = [
        {
            "ownerId": "owner-1",
            "fileId": "ready-file",
            "objectKey": "users/owner-1/species/Alectura_lathami/ready-file/query.jpg",
            "thumbnailKey": "users/owner-1/thumbnails/ready-file.jpg",
            "status": "ready",
            "tags": {"Alectura_lathami": Decimal("1")},
        }
    ]
    handler, _fake_s3 = load_handler(monkeypatch, files)

    result = handler.lambda_handler(
        event("GET", "/api/files/ready-file", claims={"sub": "owner-1", "email": "yan@example.com"}),
        None,
    )

    assert result["statusCode"] == 200
    body = parse_body(result)
    assert body["file"]["tags"] == {"Alectura_lathami": 1}
    assert body["file"]["originalUrl"] == "/api/media/ready-file/original"
    assert body["file"]["thumbnailUrl"] == "/api/media/ready-file/thumbnail"


def test_protected_media_requires_cognito_claims(monkeypatch) -> None:
    handler, _fake_s3 = load_handler(monkeypatch, [])

    result = handler.lambda_handler(event("GET", "/api/media/ready-file/thumbnail"), None)

    assert result["statusCode"] == 401


def test_protected_media_returns_file_bytes_for_authenticated_users(monkeypatch) -> None:
    files = [
        {
            "ownerId": "owner-1",
            "fileId": "ready-file",
            "objectKey": "users/owner-1/species/Alectura_lathami/ready-file/query.jpg",
            "thumbnailKey": "users/owner-1/thumbnails/ready-file.jpg",
            "status": "ready",
            "tags": {"Alectura_lathami": 1},
        }
    ]
    handler, _fake_s3 = load_handler(monkeypatch, files)

    result = handler.lambda_handler(
        event("GET", "/api/media/ready-file/thumbnail", claims={"sub": "owner-2", "email": "viewer@example.com"}),
        None,
    )

    assert result["statusCode"] == 200
    assert result["isBase64Encoded"] is True
    assert result["headers"]["content-type"] == "image/jpeg"
    assert base64.b64decode(str(result["body"])) == b"bytes:users/owner-1/thumbnails/ready-file.jpg"
    assert _fake_s3.files_table.scans == []
    assert _fake_s3.files_table.queries[0]["IndexName"] == "FileIdIndex"


def test_get_file_by_id_uses_file_id_index_without_scan(monkeypatch) -> None:
    files = [
        {
            "ownerId": "owner-1",
            "fileId": "ready-file",
            "objectKey": "users/owner-1/species/Alectura_lathami/ready-file/query.jpg",
            "thumbnailKey": "users/owner-1/thumbnails/ready-file.jpg",
            "status": "ready",
            "tags": {"Alectura_lathami": 1},
        }
    ]
    handler, fake_s3 = load_handler(monkeypatch, files)

    result = handler.lambda_handler(
        event("GET", "/api/files/ready-file", claims={"sub": "owner-2", "email": "viewer@example.com"}),
        None,
    )

    assert result["statusCode"] == 200
    assert parse_body(result)["file"]["fileId"] == "ready-file"
    assert fake_s3.files_table.scans == []
    assert fake_s3.files_table.queries[0]["IndexName"] == "FileIdIndex"


def test_files_list_is_shared_but_marks_current_owner_permissions(monkeypatch) -> None:
    files = [
        {
            "ownerId": "owner-1",
            "fileId": "mine",
            "objectKey": "users/owner-1/species/Alectura_lathami/mine/query.jpg",
            "thumbnailKey": "users/owner-1/thumbnails/mine.jpg",
            "status": "ready",
            "tags": {"Alectura_lathami": 1},
        },
        {
            "ownerId": "owner-2",
            "fileId": "shared",
            "objectKey": "users/owner-2/species/Bos_taurus/shared/cow.jpg",
            "thumbnailKey": "users/owner-2/thumbnails/shared.jpg",
            "status": "ready",
            "tags": {"Bos_taurus": 8},
        },
    ]
    handler, _fake_s3 = load_handler(monkeypatch, files)

    result = handler.lambda_handler(
        event("GET", "/api/files", claims={"sub": "owner-1", "email": "yan@example.com"}),
        None,
    )

    assert result["statusCode"] == 200
    body = parse_body(result)
    assert [item["fileId"] for item in body["files"]] == ["mine", "shared"]
    assert body["files"][0]["canDelete"] is True
    assert body["files"][1]["canDelete"] is False
    assert body["limit"] == 50
    assert body["nextToken"] == ""


def test_upload_init_deduplicates_against_shared_checksum(monkeypatch) -> None:
    checksum = "a" * 64
    files = [
        {
            "ownerId": "owner-2",
            "fileId": "shared-duplicate",
            "objectKey": "users/owner-2/species/Alectura_lathami/shared-duplicate/query.jpg",
            "thumbnailKey": "users/owner-2/thumbnails/shared-duplicate.jpg",
            "status": "ready",
            "checksum": checksum,
            "tags": {"Alectura_lathami": 1},
        }
    ]
    handler, fake_s3 = load_handler(monkeypatch, files)

    result = handler.lambda_handler(
        event(
            "POST",
            "/api/uploads/init",
            {"filename": "same.jpg", "contentType": "image/jpeg", "checksum": checksum},
            {"sub": "owner-1", "email": "yan@example.com"},
        ),
        None,
    )

    assert result["statusCode"] == 200
    body = parse_body(result)
    assert body["duplicate"] is True
    assert body["message"] == "Duplicate file already exists in the platform. Showing the existing media record."
    assert body["file"]["fileId"] == "shared-duplicate"
    assert body["file"]["isOwner"] is False
    assert body["file"]["canDelete"] is False
    assert "upload" not in body
    assert fake_s3.files_table.queries[0]["IndexName"] == "ChecksumIndex"
    assert fake_s3.files_table.puts == []


def test_files_list_uses_limit_and_next_token_pagination(monkeypatch) -> None:
    files = [
        {
            "ownerId": "owner-1",
            "fileId": "first",
            "objectKey": "users/owner-1/originals/first.jpg",
            "thumbnailKey": "users/owner-1/thumbnails/first.jpg",
            "status": "ready",
            "tags": {"Alectura_lathami": 1},
        },
        {
            "ownerId": "owner-2",
            "fileId": "second",
            "objectKey": "users/owner-2/originals/second.jpg",
            "thumbnailKey": "users/owner-2/thumbnails/second.jpg",
            "status": "ready",
            "tags": {"Bos_taurus": 1},
        },
    ]
    handler, fake_s3 = load_handler(monkeypatch, files)

    first_page = handler.lambda_handler(
        event("GET", "/api/files", claims={"sub": "owner-1", "email": "yan@example.com"}, query={"limit": 1}),
        None,
    )
    first_body = parse_body(first_page)
    second_page = handler.lambda_handler(
        event(
            "GET",
            "/api/files",
            claims={"sub": "owner-1", "email": "yan@example.com"},
            query={"limit": 1, "nextToken": first_body["nextToken"]},
        ),
        None,
    )

    assert first_body["limit"] == 1
    assert [item["fileId"] for item in first_body["files"]] == ["first"]
    assert first_body["nextToken"]
    assert [item["fileId"] for item in parse_body(second_page)["files"]] == ["second"]
    assert fake_s3.files_table.scans[0]["Limit"] == 1
    assert "ExclusiveStartKey" in fake_s3.files_table.scans[1]


def test_species_query_limits_scan_page_and_returns_next_token(monkeypatch) -> None:
    files = [
        {
            "ownerId": "owner-1",
            "fileId": "match",
            "objectKey": "users/owner-1/originals/match.jpg",
            "thumbnailKey": "users/owner-1/thumbnails/match.jpg",
            "status": "ready",
            "tags": {"Alectura_lathami": 1},
        },
        {
            "ownerId": "owner-2",
            "fileId": "later",
            "objectKey": "users/owner-2/originals/later.jpg",
            "thumbnailKey": "users/owner-2/thumbnails/later.jpg",
            "status": "ready",
            "tags": {"Alectura_lathami": 2},
        },
    ]
    handler, fake_s3 = load_handler(monkeypatch, files)

    result = handler.lambda_handler(
        event(
            "POST",
            "/api/query/species",
            {"species": "Alectura_lathami", "limit": 1},
            {"sub": "owner-1", "email": "yan@example.com"},
        ),
        None,
    )

    body = parse_body(result)
    assert result["statusCode"] == 200
    assert body["limit"] == 1
    assert [item["fileId"] for item in body["files"]] == ["match"]
    assert body["nextToken"]
    assert fake_s3.files_table.scans[0]["Limit"] == 1


def test_delete_remains_owner_only_when_files_are_shared(monkeypatch) -> None:
    files = [
        {
            "ownerId": "owner-1",
            "fileId": "mine",
            "objectKey": "users/owner-1/species/Alectura_lathami/mine/query.jpg",
            "thumbnailKey": "users/owner-1/thumbnails/mine.jpg",
            "status": "ready",
            "tags": {"Alectura_lathami": 1},
        },
        {
            "ownerId": "owner-2",
            "fileId": "shared",
            "objectKey": "users/owner-2/species/Bos_taurus/shared/cow.jpg",
            "thumbnailKey": "users/owner-2/thumbnails/shared.jpg",
            "status": "ready",
            "tags": {"Bos_taurus": 8},
        },
    ]
    handler, fake_s3 = load_handler(monkeypatch, files)

    other_delete = handler.lambda_handler(
        event(
            "POST",
            "/api/files/delete",
            {"urls": ["https://originals.s3.amazonaws.com/users/owner-2/species/Bos_taurus/shared/cow.jpg"]},
            {"sub": "owner-1", "email": "yan@example.com"},
        ),
        None,
    )
    own_delete = handler.lambda_handler(
        event(
            "POST",
            "/api/files/delete",
            {"urls": ["https://originals.s3.amazonaws.com/users/owner-1/species/Alectura_lathami/mine/query.jpg"]},
            {"sub": "owner-1", "email": "yan@example.com"},
        ),
        None,
    )

    assert parse_body(other_delete)["deleted"] == 0
    assert parse_body(own_delete)["deleted"] == 1
    assert {"Bucket": "originals", "Key": "users/owner-1/species/Alectura_lathami/mine/query.jpg"} in fake_s3.deletes
    assert {"Bucket": "originals", "Key": "users/owner-2/species/Bos_taurus/shared/cow.jpg"} not in fake_s3.deletes


def test_query_by_file_uses_media_url_contract_and_shared_results(monkeypatch) -> None:
    files = [
        {
            "ownerId": "owner-1",
            "fileId": "match",
            "objectKey": "users/owner-1/originals/match.jpg",
            "thumbnailKey": "users/owner-1/thumbnails/match.jpg",
            "tags": {"Alectura_lathami": 2},
        },
        {
            "ownerId": "owner-2",
            "fileId": "other-owner",
            "objectKey": "users/owner-2/originals/other.jpg",
            "thumbnailKey": "",
            "tags": {"Alectura_lathami": 2},
        },
    ]
    handler, fake_s3 = load_handler(monkeypatch, files)
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeUrlOpenResponse(
            {
                "modelVersion": "2026-s1-v1",
                "mediaType": "image",
                "frameRateSeconds": 1,
                "tags": {"Alectura_lathami": 1},
                "detections": [{"tag": "Alectura_lathami", "count": 1, "confidence": 0.93}],
                "thumbnailBase64": base64.b64encode(b"jpeg").decode("ascii"),
            }
        )

    monkeypatch.setattr(handler.urllib.request, "urlopen", fake_urlopen)

    result = handler.lambda_handler(
        event(
            "POST",
            "/api/query/by-file",
            {
                "filename": "query.jpg",
                "contentType": "image/jpeg",
                "fileBase64": base64.b64encode(b"query-image").decode("ascii"),
            },
            {"sub": "owner-1", "email": "yan@example.com"},
        ),
        None,
    )

    assert result["statusCode"] == 200
    body = parse_body(result)
    assert body["detectedTags"] == {"Alectura_lathami": 1}
    assert [item["fileId"] for item in body["files"]] == ["match", "other-owner"]
    assert body["files"][0]["canDelete"] is True
    assert body["files"][1]["canDelete"] is False
    assert captured["url"] == "https://gcp.example/infer"
    assert captured["timeout"] == 90
    assert captured["body"]["mediaUrl"].startswith("https://signed.example/query-temp/users/owner-1/query/")
    assert "objectUrl" not in captured["body"]
    assert "mediaPath" not in captured["body"]
    assert fake_s3.puts[0]["Bucket"] == "query-temp"
    assert fake_s3.deletes[0]["Bucket"] == "query-temp"


def test_subscribe_creates_filtered_sns_email_subscription(monkeypatch) -> None:
    handler, fake_s3 = load_handler(monkeypatch)

    result = handler.lambda_handler(
        event(
            "POST",
            "/api/subscribe",
            {"tag": "Alectura_lathami", "email": "notify@example.com"},
            {"sub": "owner-1", "email": "cognito@example.com"},
        ),
        None,
    )

    assert result["statusCode"] == 201
    body = parse_body(result)
    assert body["snsStatus"] == "pending-confirmation"
    assert body["subscription"]["email"] == "notify@example.com"
    assert body["subscription"]["ownerTag"] == "owner-1#Alectura_lathami"
    assert fake_s3.subscriptions_table.puts[0]["Item"]["email"] == "notify@example.com"
    assert fake_s3.sns.subscriptions[0]["Protocol"] == "email"
    assert fake_s3.sns.subscriptions[0]["Endpoint"] == "notify@example.com"
    assert json.loads(fake_s3.sns.subscriptions[0]["Attributes"]["FilterPolicy"]) == {
        "ownerTag": ["owner-1#Alectura_lathami"]
    }
