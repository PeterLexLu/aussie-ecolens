"""Integration contract checks for Member C final freeze."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_model_version_and_artifacts_are_env_configurable(monkeypatch):
    monkeypatch.setenv("MODEL_VERSION", "test-version")
    monkeypatch.setenv("MODEL_BUCKET", "test-model-bucket")
    monkeypatch.setenv("SPECIES_MODEL_KEY", "models/species.pt")
    monkeypatch.setenv("DETECTOR_MODEL_KEY", "models/detector.pt")
    monkeypatch.setenv("LABELS_KEY", "models/test-labels.txt")

    config = load_module("member_c_model_config", "backend/ml/model-config/config.py")

    assert config.MODEL_VERSION == "test-version"
    assert config.MODEL_BUCKET == "test-model-bucket"
    assert config.SPECIES_MODEL_KEY == "models/species.pt"
    assert config.DETECTOR_MODEL_KEY == "models/detector.pt"
    assert config.LABELS_KEY == "models/test-labels.txt"


def test_query_handler_keeps_files_and_tag_index_consistent_on_bulk_add():
    query_module = load_module("member_c_query_handlers", "backend/api/handlers/query.py")

    class Files:
        def __init__(self):
            self.updated = []

        def list_files(self, *, owner_id, limit=50):
            return []

        def get_file(self, *, owner_id, file_id):
            return None

        def find_by_url(self, *, owner_id, url):
            return {"fileId": "file-1", "originalUrl": url, "tags": {}}

        def query_by_tag_counts(self, *, owner_id, requested_tags, limit=100):
            return []

        def apply_bulk_tag_update(self, *, owner_id, file_id, tags, operation, updated_at):
            self.updated.append((owner_id, file_id, tags, operation, updated_at))
            return {"fileId": file_id, "tags": {tag: 1 for tag in tags}}

    class TagIndex:
        def __init__(self):
            self.saved = []
            self.deleted = []

        def save_manual_tags(self, *, owner_id, file_id, tags, updated_at):
            self.saved.append((owner_id, file_id, tags, updated_at))
            return []

        def delete_manual_tags(self, *, owner_id, file_id, tags):
            self.deleted.append((owner_id, file_id, tags))
            return len(tags)

    files = Files()
    tag_index = TagIndex()
    handlers = query_module.QueryHandlers(files=files, tag_index=tag_index)

    result = handlers.bulk_tags(
        owner_id="owner-1",
        urls=["/media/originals/example.jpg"],
        tags=["Alectura_lathami"],
        operation=1,
        updated_at="2026-06-01T00:00:00Z",
    )

    assert result == {"message": "Tags updated", "changes": 1}
    assert files.updated == [("owner-1", "file-1", ["Alectura_lathami"], 1, "2026-06-01T00:00:00Z")]
    assert tag_index.saved == [("owner-1", "file-1", ["Alectura_lathami"], "2026-06-01T00:00:00Z")]
    assert tag_index.deleted == []
