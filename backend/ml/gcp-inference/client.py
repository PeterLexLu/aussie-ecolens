"""GCP inference client for image and video tagging."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Protocol
from urllib import request


@dataclass(frozen=True)
class InferenceResult:
    """Full response returned by Qingwen's Cloud Run /infer endpoint."""

    model_version: str
    media_type: str
    frame_rate_seconds: int
    tags: dict[str, int]
    detections: list[dict[str, object]]
    thumbnail_base64: str

    @property
    def thumbnail_bytes(self) -> bytes:
        if not self.thumbnail_base64:
            return b""
        return base64.b64decode(self.thumbnail_base64, validate=True)

    @classmethod
    def from_json(
        cls,
        body: dict[str, object],
        *,
        fallback_media_type: str,
        fallback_frame_rate: int,
    ) -> "InferenceResult":
        tags = body.get("tags", {})
        if not isinstance(tags, dict):
            raise ValueError("Inference response must include a tags object.")

        detections = body.get("detections", [])
        if not isinstance(detections, list):
            raise ValueError("Inference response detections must be a list.")

        return cls(
            model_version=str(body.get("modelVersion", "")),
            media_type=str(body.get("mediaType", fallback_media_type)),
            frame_rate_seconds=int(body.get("frameRateSeconds", fallback_frame_rate)),
            tags={str(tag): int(count) for tag, count in tags.items()},
            detections=[item for item in detections if isinstance(item, dict)],
            thumbnail_base64=str(body.get("thumbnailBase64", "")),
        )


class InferenceClient(Protocol):
    """Contract used by processing code to call the deployed model."""

    def infer_image(self, media_url: str) -> InferenceResult:
        """Return species tags and thumbnail data detected in one image."""

    def infer_video(self, media_url: str, frame_rate: int = 1) -> InferenceResult:
        """Return aggregated species tags and thumbnail data from sampled video frames."""


class GcpInferenceClient:
    """HTTP client for the GCP Cloud Run inference service."""

    def __init__(self, endpoint_url: str, model_version: str) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.model_version = model_version

    def infer_image(self, media_url: str) -> InferenceResult:
        return self.infer_media(media_url=media_url, media_type="image", frame_rate=1)

    def infer_video(self, media_url: str, frame_rate: int = 1) -> InferenceResult:
        return self.infer_media(media_url=media_url, media_type="video", frame_rate=frame_rate)

    def infer_media(self, *, media_url: str, media_type: str, frame_rate: int = 1) -> InferenceResult:
        if media_type not in {"image", "video"}:
            raise ValueError("media_type must be image or video.")
        return self._post_infer(media_type=media_type, media_url=media_url, frame_rate=frame_rate)

    def _post_infer(self, *, media_type: str, media_url: str, frame_rate: int) -> InferenceResult:
        if not self.endpoint_url:
            raise ValueError("GCP inference endpoint is not configured.")
        if not media_url:
            raise ValueError("media_url is required.")

        payload = json.dumps(
            {
                "mediaUrl": media_url,
                "mediaType": media_type,
                "modelVersion": self.model_version,
                "frameRateSeconds": frame_rate,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{self.endpoint_url}/infer",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("Inference response must be a JSON object.")
        return InferenceResult.from_json(
            body,
            fallback_media_type=media_type,
            fallback_frame_rate=frame_rate,
        )
