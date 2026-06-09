"""Cloud Run /infer service using MegaDetector and the SpeciesNet model."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import urllib.parse
import urllib.request
import base64
from io import BytesIO
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torchvision.transforms as transforms
from flask import Flask, jsonify, request
from google.cloud import storage
from megadetector.detection import run_detector_batch
from PIL import Image, ImageOps


def _int_env(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _float_env(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


MODEL_VERSION = os.environ.get("MODEL_VERSION", "2026-s1-v1")
MODEL_BUCKET = os.environ.get("MODEL_BUCKET", "aussie-ecolens-infer-models-group82")
SPECIES_MODEL_KEY = os.environ.get("SPECIES_MODEL_KEY", "model.pt")
DETECTOR_MODEL_KEY = os.environ.get("DETECTOR_MODEL_KEY", "mdv5a.pt")
LABELS_KEY = os.environ.get("LABELS_KEY", "labels.txt")
VIDEO_FRAME_RATE_SECONDS = _int_env("VIDEO_FRAME_RATE_SECONDS", 1, minimum=1)
VIDEO_MAX_SAMPLED_FRAMES = _int_env("VIDEO_MAX_SAMPLED_FRAMES", 0, minimum=0)
VIDEO_FRAME_MAX_EDGE = _int_env("VIDEO_FRAME_MAX_EDGE", 960, minimum=0)
DETECTOR_CONFIDENCE_THRESHOLD = _float_env("DETECTOR_CONFIDENCE_THRESHOLD", 0.15, minimum=0.0, maximum=1.0)
THUMBNAIL_MAX_EDGE = _int_env("THUMBNAIL_MAX_EDGE", 360, minimum=64)
THUMBNAIL_JPEG_QUALITY = _int_env("THUMBNAIL_JPEG_QUALITY", 72, minimum=30, maximum=95)
THUMBNAIL_MIN_JPEG_QUALITY = _int_env("THUMBNAIL_MIN_JPEG_QUALITY", 52, minimum=25, maximum=95)
THUMBNAIL_MAX_BYTES = _int_env("THUMBNAIL_MAX_BYTES", 85_000, minimum=0)
TORCH_CPU_THREADS = _int_env("TORCH_CPU_THREADS", 2, minimum=0)

WORK_DIR = Path(os.environ.get("MODEL_WORK_DIR", "/tmp/aussie-ecolens"))
MODEL_PATH = WORK_DIR / "model.pt"
DETECTOR_PATH = WORK_DIR / "mdv5a.pt"
LABELS_PATH = WORK_DIR / "labels.txt"
REQUESTS_DIR = WORK_DIR / "requests"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

app = Flask(__name__)
_state: dict[str, Any] = {}
_state_lock = threading.Lock()
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
    RESAMPLE_BILINEAR = Image.Resampling.BILINEAR
except AttributeError:
    RESAMPLE_LANCZOS = Image.LANCZOS
    RESAMPLE_BILINEAR = Image.BILINEAR


def ensure_model_files() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    client = storage.Client()
    bucket = client.bucket(MODEL_BUCKET)
    for key, target in (
        (SPECIES_MODEL_KEY, MODEL_PATH),
        (DETECTOR_MODEL_KEY, DETECTOR_PATH),
        (LABELS_KEY, LABELS_PATH),
    ):
        if not target.exists():
            bucket.blob(key).download_to_filename(str(target))


def load_labels() -> list[str]:
    labels: list[str] = []
    for line in LABELS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split(";")
        if len(parts) >= 6:
            labels.append(f"{parts[4].strip().capitalize()}_{parts[5].strip().lower()}".strip("_"))
    return labels


def get_runtime() -> dict[str, Any]:
    if _state:
        return _state

    with _state_lock:
        if _state:
            return _state

        ensure_model_files()
        if TORCH_CPU_THREADS > 0:
            torch.set_num_threads(TORCH_CPU_THREADS)
            try:
                torch.set_num_interop_threads(TORCH_CPU_THREADS)
            except RuntimeError:
                pass
        device = "cuda" if torch.cuda.is_available() else "cpu"
        species_model = torch.load(MODEL_PATH, map_location=device, weights_only=False)
        species_model.eval()
        species_model.to(device)

        detector = run_detector_batch.load_detector(str(DETECTOR_PATH))
        transform = transforms.Compose(
            [
                transforms.Resize((480, 480)),
                transforms.ToTensor(),
            ]
        )
        _state.update(
            {
                "device": device,
                "speciesModel": species_model,
                "detector": detector,
                "labels": load_labels(),
                "transform": transform,
            }
        )
    return _state


def normalize_media_type(raw_media_type: str | None, media_url: str = "") -> str:
    media_type = str(raw_media_type or "").split(";", 1)[0].strip().lower()
    if media_type in {"image", "video"}:
        return media_type
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("video/"):
        return "video"

    suffix = Path(urllib.parse.unquote(urllib.parse.urlparse(media_url).path)).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return ""


def _media_suffix(media_url: str, media_type: str) -> str:
    suffix = Path(urllib.parse.unquote(urllib.parse.urlparse(media_url).path)).suffix.lower()
    if media_type == "image":
        return suffix if suffix in IMAGE_EXTENSIONS else ".jpg"
    if media_type == "video":
        return suffix if suffix in VIDEO_EXTENSIONS else ".mp4"
    return suffix or ".bin"


def _frame_rate_seconds(value: Any) -> int:
    try:
        parsed = int(value or VIDEO_FRAME_RATE_SECONDS)
    except (TypeError, ValueError):
        parsed = VIDEO_FRAME_RATE_SECONDS
    return max(parsed, 1)


def open_rgb_image(image_path: Path) -> Image.Image:
    with Image.open(image_path) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def download_media(media_url: str, request_dir: Path, media_type: str) -> Path:
    request_dir.mkdir(parents=True, exist_ok=True)
    suffix = _media_suffix(media_url, media_type)
    target = request_dir / f"media-{next(tempfile._get_candidate_names())}{suffix}"
    if media_url.startswith("gs://"):
        bucket_name, blob_name = media_url.removeprefix("gs://").split("/", 1)
        storage.Client().bucket(bucket_name).blob(blob_name).download_to_filename(str(target))
    else:
        urllib.request.urlretrieve(media_url, target)
    return target


def classify_crop(crop_path: Path, runtime: dict[str, Any]) -> tuple[str, float]:
    with open_rgb_image(crop_path) as img:
        tensor = runtime["transform"](img).unsqueeze(0).permute(0, 2, 3, 1).to(runtime["device"])
    with torch.no_grad():
        logits = runtime["speciesModel"](tensor)
        probs = torch.softmax(logits, dim=1)[0].cpu().numpy()
    best_idx = int(np.argsort(probs)[::-1][0])
    labels = runtime["labels"]
    tag = labels[best_idx] if best_idx < len(labels) else f"class_{best_idx}"
    return tag, float(probs[best_idx])


def crop_detections(image_path: Path, runtime: dict[str, Any], crop_dir: Path) -> list[Path]:
    crop_dir.mkdir(parents=True, exist_ok=True)
    crops: list[Path] = []
    with open_rgb_image(image_path) as img:
        result = runtime["detector"].generate_detections_one_image(
            img,
            image_id=str(image_path),
            detection_threshold=DETECTOR_CONFIDENCE_THRESHOLD,
            verbose=False,
        )
        detections = result.get("detections", [])
        width, height = img.size
        for index, detection in enumerate(detections):
            if detection.get("category") != "1" or float(detection.get("conf", 0)) < DETECTOR_CONFIDENCE_THRESHOLD:
                continue
            x, y, w, h = detection["bbox"]
            left = max(0, int(x * width))
            top = max(0, int(y * height))
            right = min(width, int((x + w) * width))
            bottom = min(height, int((y + h) * height))
            if right <= left or bottom <= top:
                continue
            crop = img.crop((left, top, right, bottom))
            crop_path = crop_dir / f"{image_path.stem}-{index}.jpg"
            crop.resize((600, 600), RESAMPLE_BILINEAR).save(crop_path, format="JPEG", quality=90, optimize=True)
            crops.append(crop_path)
    return crops


def build_thumbnail_base64(image_path: Path) -> str:
    with open_rgb_image(image_path) as img:
        img.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), RESAMPLE_LANCZOS)
        quality = max(THUMBNAIL_MIN_JPEG_QUALITY, min(THUMBNAIL_JPEG_QUALITY, 95))
        min_quality = min(quality, THUMBNAIL_MIN_JPEG_QUALITY)
        payload = b""

        while True:
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
            payload = buffer.getvalue()
            if not THUMBNAIL_MAX_BYTES or len(payload) <= THUMBNAIL_MAX_BYTES or quality <= min_quality:
                break
            quality = max(min_quality, quality - 8)
    return base64.b64encode(payload).decode("ascii")


def infer_image(image_path: Path, runtime: dict[str, Any], request_dir: Path, include_thumbnail: bool = True) -> dict[str, Any]:
    crops = crop_detections(image_path, runtime, request_dir / "crops")
    thumbnail_base64 = build_thumbnail_base64(image_path) if include_thumbnail else ""
    if not crops:
        return {"tags": {}, "detections": [], "thumbnailBase64": thumbnail_base64}

    counts: Counter[str] = Counter()
    best_confidence: dict[str, float] = {}
    for crop_path in crops:
        tag, confidence = classify_crop(crop_path, runtime)
        counts[tag] += 1
        best_confidence[tag] = max(best_confidence.get(tag, 0.0), confidence)

    detections = [
        {"tag": tag, "count": count, "confidence": round(best_confidence[tag], 4)}
        for tag, count in counts.items()
    ]
    return {"tags": dict(counts), "detections": detections, "thumbnailBase64": thumbnail_base64}


def resize_video_frame_for_inference(frame: Any, cv2_module: Any) -> Any:
    if VIDEO_FRAME_MAX_EDGE <= 0 or not hasattr(frame, "shape") or len(frame.shape) < 2:
        return frame
    height, width = int(frame.shape[0]), int(frame.shape[1])
    max_edge = max(width, height)
    if max_edge <= VIDEO_FRAME_MAX_EDGE:
        return frame
    scale = VIDEO_FRAME_MAX_EDGE / max_edge
    target_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    interpolation = getattr(cv2_module, "INTER_AREA", 3)
    return cv2_module.resize(frame, target_size, interpolation=interpolation)


def infer_video(video_path: Path, runtime: dict[str, Any], request_dir: Path, frame_rate_seconds: int) -> dict[str, Any]:
    import cv2

    frame_dir = request_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
    except (TypeError, ValueError):
        fps = 1.0
    if not math.isfinite(fps) or fps <= 0:
        fps = 1.0
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    except (TypeError, ValueError):
        frame_count = 0
    frame_count = max(frame_count, 0)
    frame_rate_seconds = max(int(frame_rate_seconds or VIDEO_FRAME_RATE_SECONDS), 1)
    counts: Counter[str] = Counter()
    confidence: dict[str, float] = {}
    thumbnail_base64 = ""
    saved_index = 0
    sample_positions: list[int] = []

    if frame_count > 0:
        duration_seconds = frame_count / max(fps, 1)
        sample_count = max(1, int(math.ceil(duration_seconds / frame_rate_seconds)))
        sample_positions = [
            min(frame_count - 1, int(round(index * frame_rate_seconds * fps)))
            for index in range(sample_count)
        ]
        sample_positions = list(dict.fromkeys(sample_positions))
        if VIDEO_MAX_SAMPLED_FRAMES:
            sample_positions = sample_positions[:VIDEO_MAX_SAMPLED_FRAMES]

    try:
        if sample_positions:
            for frame_index in sample_positions:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok:
                    continue
                frame = resize_video_frame_for_inference(frame, cv2)
                frame_path = frame_dir / f"{video_path.stem}-frame-{saved_index:04d}.jpg"
                cv2.imwrite(str(frame_path), frame)
                if not thumbnail_base64:
                    thumbnail_base64 = build_thumbnail_base64(frame_path)
                result = infer_image(frame_path, runtime, request_dir / f"frame-{saved_index:04d}", include_thumbnail=False)
                for tag, count in result["tags"].items():
                    counts[tag] += count
                for item in result["detections"]:
                    tag = item["tag"]
                    confidence[tag] = max(confidence.get(tag, 0.0), float(item["confidence"]))
                saved_index += 1
        else:
            step = max(int(round(fps * frame_rate_seconds)), 1)
            frame_index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % step == 0:
                    frame = resize_video_frame_for_inference(frame, cv2)
                    frame_path = frame_dir / f"{video_path.stem}-frame-{saved_index:04d}.jpg"
                    cv2.imwrite(str(frame_path), frame)
                    if not thumbnail_base64:
                        thumbnail_base64 = build_thumbnail_base64(frame_path)
                    result = infer_image(frame_path, runtime, request_dir / f"frame-{saved_index:04d}", include_thumbnail=False)
                    for tag, count in result["tags"].items():
                        counts[tag] += count
                    for item in result["detections"]:
                        tag = item["tag"]
                        confidence[tag] = max(confidence.get(tag, 0.0), float(item["confidence"]))
                    saved_index += 1
                    if VIDEO_MAX_SAMPLED_FRAMES and saved_index >= VIDEO_MAX_SAMPLED_FRAMES:
                        break
                frame_index += 1
    finally:
        capture.release()

    detections = [
        {"tag": tag, "count": count, "confidence": round(confidence.get(tag, 0.0), 4)}
        for tag, count in counts.items()
    ]
    return {"tags": dict(counts), "detections": detections, "thumbnailBase64": thumbnail_base64}


@app.get("/health")
def health():
    return jsonify({"status": "ok", "modelVersion": MODEL_VERSION})


@app.post("/infer")
def infer_endpoint():
    data = request.get_json(force=True, silent=True) or {}
    media_url = data.get("mediaUrl")
    media_type = normalize_media_type(data.get("mediaType"), str(media_url or ""))
    model_version = str(data.get("modelVersion") or MODEL_VERSION)
    frame_rate_seconds = _frame_rate_seconds(data.get("frameRateSeconds"))
    if not media_url:
        return jsonify({"error": "mediaUrl is required"}), 400
    if media_type not in {"image", "video"}:
        return jsonify({"error": "mediaType must be image or video"}), 400

    runtime = get_runtime()
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="infer-", dir=REQUESTS_DIR) as temp_dir:
        request_dir = Path(temp_dir)
        media_path = download_media(str(media_url), request_dir, media_type)
        result = (
            infer_image(media_path, runtime, request_dir)
            if media_type == "image"
            else infer_video(media_path, runtime, request_dir, frame_rate_seconds)
        )
    return jsonify(
        {
            "modelVersion": model_version,
            "mediaType": media_type,
            "frameRateSeconds": frame_rate_seconds,
            "tags": result["tags"],
            "detections": result["detections"],
            "thumbnailBase64": result["thumbnailBase64"],
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
