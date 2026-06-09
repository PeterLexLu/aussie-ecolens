"""Tests for the GCP inference media-processing stability helpers."""

from __future__ import annotations

import base64
import importlib.util
import sys
import types
from io import BytesIO
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "backend" / "ml" / "gcp-inference" / "service.py"


class FakeFlask:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        return None

    def get(self, *_args: object, **_kwargs: object):
        return lambda func: func

    def post(self, *_args: object, **_kwargs: object):
        return lambda func: func


def _install_service_stubs(monkeypatch) -> None:
    flask_module = types.ModuleType("flask")
    flask_module.Flask = FakeFlask
    flask_module.jsonify = lambda payload: payload
    flask_module.request = types.SimpleNamespace(get_json=lambda **_kwargs: {})
    monkeypatch.setitem(sys.modules, "flask", flask_module)

    storage_module = types.ModuleType("google.cloud.storage")
    storage_module.Client = object
    cloud_module = types.ModuleType("google.cloud")
    cloud_module.storage = storage_module
    google_module = types.ModuleType("google")
    google_module.cloud = cloud_module
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage_module)

    run_detector_batch = types.ModuleType("megadetector.detection.run_detector_batch")
    run_detector_batch.load_detector = lambda _path: object()
    detection_module = types.ModuleType("megadetector.detection")
    detection_module.run_detector_batch = run_detector_batch
    megadetector_module = types.ModuleType("megadetector")
    megadetector_module.detection = detection_module
    monkeypatch.setitem(sys.modules, "megadetector", megadetector_module)
    monkeypatch.setitem(sys.modules, "megadetector.detection", detection_module)
    monkeypatch.setitem(sys.modules, "megadetector.detection.run_detector_batch", run_detector_batch)

    torch_module = types.ModuleType("torch")
    torch_module.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch_module.set_num_threads = lambda _value: None
    torch_module.set_num_interop_threads = lambda _value: None
    torch_module.load = lambda *_args, **_kwargs: object()
    torch_module.no_grad = lambda: types.SimpleNamespace(__enter__=lambda: None, __exit__=lambda *_args: None)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    transforms_module = types.ModuleType("torchvision.transforms")
    transforms_module.Compose = lambda steps: steps
    transforms_module.Resize = lambda size: ("resize", size)
    transforms_module.ToTensor = lambda: "to-tensor"
    torchvision_module = types.ModuleType("torchvision")
    torchvision_module.transforms = transforms_module
    monkeypatch.setitem(sys.modules, "torchvision", torchvision_module)
    monkeypatch.setitem(sys.modules, "torchvision.transforms", transforms_module)


def load_service(monkeypatch):
    _install_service_stubs(monkeypatch)
    module_name = "gcp_inference_service_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, SERVICE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_media_type_and_suffix_are_stable_for_signed_urls(monkeypatch) -> None:
    service = load_service(monkeypatch)

    assert service.normalize_media_type("image/jpeg") == "image"
    assert service.normalize_media_type("video/mp4") == "video"
    assert service.normalize_media_type("", "https://example.test/path/cow.WEBM?signature=abc") == "video"
    assert service.normalize_media_type(None, "https://example.test/path/bird.jpeg?signature=abc") == "image"
    assert service.normalize_media_type("application/octet-stream", "https://example.test/blob") == ""
    assert service._media_suffix("https://example.test/blob?signature=abc", "image") == ".jpg"
    assert service._media_suffix("https://example.test/movie.mov?signature=abc", "video") == ".mov"
    assert service._frame_rate_seconds("0") == 1


def test_thumbnail_base64_is_compressed_jpeg(monkeypatch, tmp_path) -> None:
    service = load_service(monkeypatch)
    monkeypatch.setattr(service, "THUMBNAIL_MAX_EDGE", 96)
    monkeypatch.setattr(service, "THUMBNAIL_JPEG_QUALITY", 70)
    monkeypatch.setattr(service, "THUMBNAIL_MIN_JPEG_QUALITY", 45)
    monkeypatch.setattr(service, "THUMBNAIL_MAX_BYTES", 5_000)
    image_path = tmp_path / "large.png"
    Image.new("RGB", (800, 500), (42, 110, 180)).save(image_path)

    encoded = service.build_thumbnail_base64(image_path)
    payload = base64.b64decode(encoded)
    with Image.open(BytesIO(payload)) as thumbnail:
        assert thumbnail.format == "JPEG"
        assert max(thumbnail.size) <= 96
    assert len(payload) <= 5_000


def test_detection_threshold_filters_low_confidence_crops(monkeypatch, tmp_path) -> None:
    service = load_service(monkeypatch)
    monkeypatch.setattr(service, "DETECTOR_CONFIDENCE_THRESHOLD", 0.2)
    image_path = tmp_path / "wildlife.jpg"
    Image.new("RGB", (100, 100), (42, 110, 180)).save(image_path)

    class FakeDetector:
        def __init__(self) -> None:
            self.threshold: float | None = None

        def generate_detections_one_image(self, *_args: object, **kwargs: object) -> dict[str, object]:
            self.threshold = float(kwargs["detection_threshold"])
            return {
                "detections": [
                    {"category": "1", "conf": 0.1, "bbox": [0.1, 0.1, 0.2, 0.2]},
                    {"category": "1", "conf": 0.3, "bbox": [0.2, 0.2, 0.3, 0.3]},
                ]
            }

    detector = FakeDetector()
    crops = service.crop_detections(image_path, {"detector": detector}, tmp_path / "crops")

    assert detector.threshold == 0.2
    assert len(crops) == 1
    assert crops[0].exists()


def test_video_frame_resize_uses_max_edge(monkeypatch) -> None:
    service = load_service(monkeypatch)
    monkeypatch.setattr(service, "VIDEO_FRAME_MAX_EDGE", 960)

    class FakeFrame:
        shape = (1080, 1920, 3)

    class FakeCv2:
        INTER_AREA = 7
        call: tuple[object, tuple[int, int], int] | None = None

        @classmethod
        def resize(cls, frame: object, target_size: tuple[int, int], interpolation: int) -> object:
            cls.call = (frame, target_size, interpolation)
            return {"resized": target_size}

    resized = service.resize_video_frame_for_inference(FakeFrame(), FakeCv2)

    assert resized == {"resized": (960, 540)}
    assert FakeCv2.call is not None
    assert FakeCv2.call[1:] == ((960, 540), 7)


def test_video_inference_samples_one_frame_per_second_and_aggregates(monkeypatch, tmp_path) -> None:
    service = load_service(monkeypatch)
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.CAP_PROP_FPS = 5
    fake_cv2.CAP_PROP_FRAME_COUNT = 7
    fake_cv2.CAP_PROP_POS_FRAMES = 1

    class FakeCapture:
        last: "FakeCapture | None" = None

        def __init__(self, _path: str) -> None:
            type(self).last = self
            self.positions: list[int] = []
            self.released = False

        def get(self, prop: int) -> int:
            if prop == fake_cv2.CAP_PROP_FPS:
                return 5
            if prop == fake_cv2.CAP_PROP_FRAME_COUNT:
                return 16
            return 0

        def set(self, prop: int, value: int) -> bool:
            assert prop == fake_cv2.CAP_PROP_POS_FRAMES
            self.positions.append(int(value))
            return True

        def read(self) -> tuple[bool, dict[str, object]]:
            return True, {"frame": len(self.positions)}

        def release(self) -> None:
            self.released = True

    def fake_imwrite(path: str, _frame: object) -> bool:
        Image.new("RGB", (32, 24), (120, 80, 40)).save(path, format="JPEG")
        return True

    fake_cv2.VideoCapture = FakeCapture
    fake_cv2.imwrite = fake_imwrite
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

    calls: list[str] = []

    def fake_infer_image(frame_path: Path, *_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append(frame_path.name)
        return {
            "tags": {"Alectura_lathami": 1},
            "detections": [{"tag": "Alectura_lathami", "count": 1, "confidence": 0.6}],
            "thumbnailBase64": "",
        }

    monkeypatch.setattr(service, "infer_image", fake_infer_image)

    result = service.infer_video(tmp_path / "wildlife.mp4", {}, tmp_path / "request", 1)

    assert FakeCapture.last is not None
    assert FakeCapture.last.positions == [0, 5, 10, 15]
    assert FakeCapture.last.released is True
    assert calls == [
        "wildlife-frame-0000.jpg",
        "wildlife-frame-0001.jpg",
        "wildlife-frame-0002.jpg",
        "wildlife-frame-0003.jpg",
    ]
    assert result["tags"] == {"Alectura_lathami": 4}
    assert result["detections"] == [{"tag": "Alectura_lathami", "count": 4, "confidence": 0.6}]
    assert base64.b64decode(str(result["thumbnailBase64"]))
