#!/usr/bin/env bash
set -euo pipefail

ACCOUNT_ID="${AWS_ACCOUNT_ID:-203276832845}"
ORIGINALS_BUCKET="${ORIGINALS_BUCKET:-aussie-ecolens-originals-${ACCOUNT_ID}}"
THUMBNAILS_BUCKET="${THUMBNAILS_BUCKET:-aussie-ecolens-thumbnails-${ACCOUNT_ID}}"
QUERY_TEMP_BUCKET="${QUERY_TEMP_BUCKET:-aussie-ecolens-query-temp-${ACCOUNT_ID}}"
CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:8000,https://d3m1q0eazv9ntq.cloudfront.net}"

BUILD_DIR="${BUILD_DIR:-$(mktemp -d)}"
CORS_FILE="${BUILD_DIR}/s3-cors.json"

IFS=',' read -r -a ORIGINS <<<"$CORS_ORIGINS"
python3 - "$CORS_FILE" "${ORIGINS[@]}" <<'PY'
import json
import sys

path = sys.argv[1]
origins = [origin.strip() for origin in sys.argv[2:] if origin.strip()]
if not origins:
    origins = ["http://localhost:8000", "https://d3m1q0eazv9ntq.cloudfront.net"]

config = {
    "CORSRules": [
        {
            "AllowedOrigins": origins,
            "AllowedMethods": ["GET", "HEAD", "PUT"],
            "AllowedHeaders": ["*"],
            "ExposeHeaders": ["ETag"],
            "MaxAgeSeconds": 3000,
        }
    ]
}

with open(path, "w", encoding="utf-8") as handle:
    json.dump(config, handle)
PY

for bucket in "$ORIGINALS_BUCKET" "$THUMBNAILS_BUCKET" "$QUERY_TEMP_BUCKET"; do
  aws s3api put-bucket-cors \
    --bucket "$bucket" \
    --cors-configuration "file://${CORS_FILE}"
done

echo "Configured S3 CORS for ${CORS_ORIGINS}"
