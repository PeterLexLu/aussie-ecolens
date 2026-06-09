"""Tests for the AWS processing Lambda queue handoff contract."""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class FakeKey:
    def __init__(self, _name: str) -> None:
        return None


class FakeTable:
    def query(self, **_kwargs: object) -> dict[str, object]:
        return {"Items": []}


class FakeDynamoResource:
    def Table(self, _name: str) -> FakeTable:
        return FakeTable()


def load_handler(monkeypatch):
    boto3_module = types.ModuleType("boto3")
    boto3_module.client = lambda _service, **_kwargs: object()
    boto3_module.resource = lambda _service, **_kwargs: FakeDynamoResource()
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

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    for name in ["backend.cloud.aws_processing_handler", "backend.cloud.aws_common"]:
        sys.modules.pop(name, None)

    return importlib.import_module("backend.cloud.aws_processing_handler")


def s3_record(key: str) -> dict[str, object]:
    return {"s3": {"object": {"key": key}}}


def test_processing_handler_accepts_direct_s3_events(monkeypatch) -> None:
    handler = load_handler(monkeypatch)
    processed: list[str] = []
    monkeypatch.setattr(handler, "_process", processed.append)

    result = handler.lambda_handler(
        {"Records": [s3_record("users/owner-1/pending/file-1/bird+photo.jpg")]},
        None,
    )

    assert result == {"processed": 1}
    assert processed == ["users/owner-1/pending/file-1/bird photo.jpg"]


def test_processing_handler_accepts_sqs_wrapped_s3_events(monkeypatch) -> None:
    handler = load_handler(monkeypatch)
    processed: list[str] = []
    monkeypatch.setattr(handler, "_process", processed.append)
    body = json.dumps(
        {
            "Records": [
                s3_record("users/owner-1/pending/file-1/bird.jpg"),
                s3_record("users/owner-2/pending/file-2/wombat.jpg"),
            ]
        }
    )

    result = handler.lambda_handler({"Records": [{"eventSource": "aws:sqs", "body": body}]}, None)

    assert result == {"processed": 2}
    assert processed == [
        "users/owner-1/pending/file-1/bird.jpg",
        "users/owner-2/pending/file-2/wombat.jpg",
    ]
