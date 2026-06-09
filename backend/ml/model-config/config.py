"""Model artifact and version configuration placeholders."""

import os


MODEL_VERSION = os.environ.get("MODEL_VERSION", "2026-s1-v1")
MODEL_BUCKET = os.environ.get("MODEL_BUCKET", "aussie-ecolens-models")
SPECIES_MODEL_KEY = os.environ.get("SPECIES_MODEL_KEY", "models/model.pt")
DETECTOR_MODEL_KEY = os.environ.get("DETECTOR_MODEL_KEY", "models/mdv5a.pt")
LABELS_KEY = os.environ.get("LABELS_KEY", "models/labels.txt")
GCP_INFERENCE_ENDPOINT = os.environ.get("GCP_INFERENCE_ENDPOINT", "")
GCP_INFER_PATH = "/infer"
VIDEO_FRAME_RATE_SECONDS = int(os.environ.get("VIDEO_FRAME_RATE_SECONDS", "1"))

MODEL_CONFIG_KEYS = (
    "MODEL_VERSION",
    "MODEL_BUCKET",
    "SPECIES_MODEL_KEY",
    "DETECTOR_MODEL_KEY",
    "LABELS_KEY",
    "GCP_INFERENCE_ENDPOINT",
    "VIDEO_FRAME_RATE_SECONDS",
)
