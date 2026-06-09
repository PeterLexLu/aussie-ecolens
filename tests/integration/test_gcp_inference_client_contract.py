"""Contract tests for the AWS-to-GCP inference client."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_client_module():
    path = ROOT / "backend" / "ml" / "gcp-inference" / "client.py"
    spec = importlib.util.spec_from_file_location("gcp_inference_client_contract", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CapturingInferHandler(BaseHTTPRequestHandler):
    captured_payload: dict[str, object] = {}

    def do_POST(self) -> None:
        assert self.path == "/infer"
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.__class__.captured_payload = json.loads(body.decode("utf-8"))
        response = {
            "modelVersion": "2026-s1-v1",
            "mediaType": self.__class__.captured_payload["mediaType"],
            "frameRateSeconds": self.__class__.captured_payload["frameRateSeconds"],
            "tags": {"Alectura_lathami": 1},
            "detections": [
                {
                    "tag": "Alectura_lathami",
                    "count": 1,
                    "confidence": 0.93,
                }
            ],
            "thumbnailBase64": base64.b64encode(b"jpeg-thumbnail").decode("ascii"),
        }
        payload = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def run_test_server():
    server = HTTPServer(("127.0.0.1", 0), CapturingInferHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_gcp_client_sends_qingwen_media_url_contract() -> None:
    module = load_client_module()
    server = run_test_server()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        client = module.GcpInferenceClient(endpoint, "2026-s1-v1")

        result = client.infer_video(
            "https://signed.example/originals/Bos_taurus_2.JPG?sig=test",
            frame_rate=1,
        )
    finally:
        server.shutdown()
        server.server_close()

    request_payload = CapturingInferHandler.captured_payload
    assert request_payload == {
        "mediaUrl": "https://signed.example/originals/Bos_taurus_2.JPG?sig=test",
        "mediaType": "video",
        "modelVersion": "2026-s1-v1",
        "frameRateSeconds": 1,
    }
    assert "mediaPath" not in request_payload
    assert "objectUrl" not in request_payload

    assert result.model_version == "2026-s1-v1"
    assert result.media_type == "video"
    assert result.frame_rate_seconds == 1
    assert result.tags == {"Alectura_lathami": 1}
    assert result.detections == [{"tag": "Alectura_lathami", "count": 1, "confidence": 0.93}]
    assert result.thumbnail_base64
    assert result.thumbnail_bytes == b"jpeg-thumbnail"


def test_gcp_client_rejects_empty_media_url() -> None:
    module = load_client_module()
    client = module.GcpInferenceClient("https://example.invalid", "2026-s1-v1")

    try:
        client.infer_image("")
    except ValueError as exc:
        assert "media_url is required" in str(exc)
    else:
        raise AssertionError("Expected empty media_url to be rejected")
