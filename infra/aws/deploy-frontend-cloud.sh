#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND_DIR="${FRONTEND_DIR:-${ROOT_DIR}/frontend}"
FRONTEND_BUCKET="${FRONTEND_BUCKET:-aussie-ecolens-frontend-${ACCOUNT_ID}}"
USER_POOL_ID="${COGNITO_USER_POOL_ID:-us-east-1_ahvGMB95O}"
APP_CLIENT_ID="${COGNITO_APP_CLIENT_ID:-2scr7btsqhli8d0hcchdltvnf5}"
API_FUNCTION_NAME="${API_FUNCTION_NAME:-aussie-ecolens-api}"
ORIGINALS_BUCKET="${ORIGINALS_BUCKET:-aussie-ecolens-originals-${ACCOUNT_ID}}"
THUMBNAILS_BUCKET="${THUMBNAILS_BUCKET:-aussie-ecolens-thumbnails-${ACCOUNT_ID}}"
QUERY_TEMP_BUCKET="${QUERY_TEMP_BUCKET:-aussie-ecolens-query-temp-${ACCOUNT_ID}}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/.aws-build}"

if [[ -z "${CLOUDFRONT_DISTRIBUTION_ID:-}" && "$ACCOUNT_ID" == "203276832845" ]]; then
  CLOUDFRONT_DISTRIBUTION_ID="E28TQ3D7POPUN1"
fi

mkdir -p "$BUILD_DIR"

FRONTEND_WEBSITE_URL="http://${FRONTEND_BUCKET}.s3-website-${REGION}.amazonaws.com"

aws s3api head-bucket --bucket "$FRONTEND_BUCKET" 2>/dev/null \
  || aws s3api create-bucket --bucket "$FRONTEND_BUCKET" --region "$REGION"

aws s3api put-public-access-block \
  --bucket "$FRONTEND_BUCKET" \
  --public-access-block-configuration \
    BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false

python3 - "$FRONTEND_BUCKET" "$BUILD_DIR/frontend-bucket-policy.json" <<'PY'
import json
import sys

bucket = sys.argv[1]
path = sys.argv[2]
policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadForStaticWebsite",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{bucket}/*",
        }
    ],
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(policy, handle)
PY

aws s3api put-bucket-policy \
  --bucket "$FRONTEND_BUCKET" \
  --policy "file://${BUILD_DIR}/frontend-bucket-policy.json"

python3 - "$BUILD_DIR/frontend-website.json" <<'PY'
import json
import sys

config = {
    "IndexDocument": {"Suffix": "index.html"},
    "ErrorDocument": {"Key": "index.html"},
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(config, handle)
PY

aws s3api put-bucket-website \
  --bucket "$FRONTEND_BUCKET" \
  --website-configuration "file://${BUILD_DIR}/frontend-website.json"

aws s3 sync "$FRONTEND_DIR" "s3://${FRONTEND_BUCKET}" \
  --delete \
  --exclude ".gitkeep" \
  --exclude "._*"

if [[ -z "${CLOUDFRONT_DISTRIBUTION_ID:-}" ]]; then
  python3 - "$FRONTEND_BUCKET" "$BUILD_DIR/frontend-cloudfront.json" <<'PY'
import json
import sys
import time

bucket = sys.argv[1]
path = sys.argv[2]
origin = f"{bucket}.s3-website-us-east-1.amazonaws.com"
config = {
    "CallerReference": str(int(time.time())),
    "Comment": "Aussie EcoLens frontend",
    "Enabled": True,
    "PriceClass": "PriceClass_100",
    "DefaultRootObject": "index.html",
    "Origins": {
        "Quantity": 1,
        "Items": [
            {
                "Id": "s3-website-frontend",
                "DomainName": origin,
                "CustomOriginConfig": {
                    "HTTPPort": 80,
                    "HTTPSPort": 443,
                    "OriginProtocolPolicy": "http-only",
                    "OriginSslProtocols": {
                        "Quantity": 1,
                        "Items": ["TLSv1.2"],
                    },
                },
            }
        ],
    },
    "DefaultCacheBehavior": {
        "TargetOriginId": "s3-website-frontend",
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": {
            "Quantity": 2,
            "Items": ["GET", "HEAD"],
            "CachedMethods": {
                "Quantity": 2,
                "Items": ["GET", "HEAD"],
            },
        },
        "ForwardedValues": {
            "QueryString": False,
            "Cookies": {"Forward": "none"},
        },
        "MinTTL": 0,
        "DefaultTTL": 300,
        "MaxTTL": 3600,
        "Compress": True,
    },
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(config, handle)
PY
  CLOUDFRONT_DISTRIBUTION_ID="$(
    aws cloudfront create-distribution \
      --distribution-config "file://${BUILD_DIR}/frontend-cloudfront.json" \
      --query Distribution.Id \
      --output text
  )"
fi

CLOUDFRONT_DOMAIN="$(
  aws cloudfront get-distribution \
    --id "$CLOUDFRONT_DISTRIBUTION_ID" \
    --query Distribution.DomainName \
    --output text
)"
FRONTEND_CLOUD_URL="https://${CLOUDFRONT_DOMAIN}"
FRONTEND_CALLBACK_URL="${FRONTEND_CLOUD_URL}/public/index.html"

aws cognito-idp update-user-pool-client \
  --region "$REGION" \
  --user-pool-id "$USER_POOL_ID" \
  --client-id "$APP_CLIENT_ID" \
  --callback-urls \
    "http://localhost:8000/" \
    "http://localhost:8000/public/index.html" \
    "${FRONTEND_CLOUD_URL}/" \
    "$FRONTEND_CALLBACK_URL" \
  --logout-urls \
    "http://localhost:8000/" \
    "http://localhost:8000/public/index.html" \
    "${FRONTEND_CLOUD_URL}/" \
    "$FRONTEND_CALLBACK_URL" \
  --allowed-o-auth-flows code \
  --allowed-o-auth-scopes openid email \
  --allowed-o-auth-flows-user-pool-client \
  --supported-identity-providers COGNITO \
  --explicit-auth-flows ALLOW_ADMIN_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH >/dev/null

aws lambda get-function-configuration \
  --region "$REGION" \
  --function-name "$API_FUNCTION_NAME" \
  --query Environment.Variables \
  --output json >"${BUILD_DIR}/api-env-vars.json"

python3 - "${BUILD_DIR}/api-env-vars.json" "${BUILD_DIR}/api-env-update.json" "$FRONTEND_CALLBACK_URL" <<'PY'
import json
import sys

source_path, target_path, redirect_uri = sys.argv[1:]
with open(source_path, "r", encoding="utf-8") as handle:
    variables = json.load(handle)
variables["COGNITO_REDIRECT_URI"] = redirect_uri
with open(target_path, "w", encoding="utf-8") as handle:
    json.dump({"Variables": variables}, handle)
PY

aws lambda update-function-configuration \
  --region "$REGION" \
  --function-name "$API_FUNCTION_NAME" \
  --environment "file://${BUILD_DIR}/api-env-update.json" >/dev/null

aws lambda wait function-updated \
  --region "$REGION" \
  --function-name "$API_FUNCTION_NAME"

FRONTEND_CORS_ORIGIN="$FRONTEND_CLOUD_URL"
CORS_ORIGINS="http://localhost:8000,${FRONTEND_CORS_ORIGIN}" \
  ORIGINALS_BUCKET="$ORIGINALS_BUCKET" \
  THUMBNAILS_BUCKET="$THUMBNAILS_BUCKET" \
  QUERY_TEMP_BUCKET="$QUERY_TEMP_BUCKET" \
  BUILD_DIR="$BUILD_DIR" \
  "${ROOT_DIR}/infra/aws/configure-s3-cors.sh"

cat >"${BUILD_DIR}/frontend-cloud.env" <<EOF
FRONTEND_BUCKET=${FRONTEND_BUCKET}
FRONTEND_WEBSITE_URL=${FRONTEND_WEBSITE_URL}
CLOUDFRONT_DISTRIBUTION_ID=${CLOUDFRONT_DISTRIBUTION_ID}
FRONTEND_CLOUD_URL=${FRONTEND_CLOUD_URL}
FRONTEND_CALLBACK_URL=${FRONTEND_CALLBACK_URL}
EOF

cat "${BUILD_DIR}/frontend-cloud.env"
