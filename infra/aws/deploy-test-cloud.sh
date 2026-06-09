#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-203276832845}"
USER_POOL_ID="${COGNITO_USER_POOL_ID:-us-east-1_ahvGMB95O}"
APP_CLIENT_ID="${COGNITO_APP_CLIENT_ID:-2scr7btsqhli8d0hcchdltvnf5}"
COGNITO_DOMAIN="${COGNITO_DOMAIN:-us-east-1ahvgmb95o.auth.us-east-1.amazoncognito.com}"
COGNITO_REDIRECT_URI="${COGNITO_REDIRECT_URI:-https://d3m1q0eazv9ntq.cloudfront.net/public/index.html}"
GCP_INFER_URL="${GCP_INFER_URL:-https://aussie-ecolens-infer-424km3wlqa-ue.a.run.app}"
MODEL_VERSION="${MODEL_VERSION:-2026-s1-v1}"
API_BASE_URL="${API_BASE_URL:-}"
ORIGINALS_BUCKET="aussie-ecolens-originals-${ACCOUNT_ID}"
THUMBNAILS_BUCKET="aussie-ecolens-thumbnails-${ACCOUNT_ID}"
QUERY_TEMP_BUCKET="aussie-ecolens-query-temp-${ACCOUNT_ID}"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:aussie-ecolens-notifications"
DLQ_URL="https://sqs.${REGION}.amazonaws.com/${ACCOUNT_ID}/aussie-ecolens-processing-dlq"
PROCESS_QUEUE_NAME="${PROCESS_QUEUE_NAME:-aussie-ecolens-processing-queue}"
PROCESS_VISIBILITY_TIMEOUT="${PROCESS_VISIBILITY_TIMEOUT:-960}"
PROCESS_BATCH_SIZE="${PROCESS_BATCH_SIZE:-1}"
PROCESS_RESERVED_CONCURRENCY="${PROCESS_RESERVED_CONCURRENCY:-8}"
API_MEMORY_SIZE="${API_MEMORY_SIZE:-1024}"
PROCESS_MEMORY_SIZE="${PROCESS_MEMORY_SIZE:-2048}"
API_QUERY_INFER_TIMEOUT_SECONDS="${API_QUERY_INFER_TIMEOUT_SECONDS:-90}"
PROCESS_INFER_TIMEOUT_SECONDS="${PROCESS_INFER_TIMEOUT_SECONDS:-840}"
API_ROLE_NAME="AussieEcoLensApiLambdaRole"
PROCESS_ROLE_NAME="AussieEcoLensProcessingLambdaRole"
API_FUNCTION="aussie-ecolens-api"
PROCESS_FUNCTION="aussie-ecolens-processing"
HTTP_API_NAME="aussie-ecolens-http-api"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${ROOT_DIR}/.aws-build"

mkdir -p "$BUILD_DIR"
BUILD_DIR="$BUILD_DIR" CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:8000,https://d3m1q0eazv9ntq.cloudfront.net}" \
  "${ROOT_DIR}/infra/aws/configure-s3-cors.sh"

wait_gsi_active() {
  local table_name="$1"
  local index_name="$2"
  for _ in $(seq 1 60); do
    local status
    status="$(aws dynamodb describe-table \
      --region "$REGION" \
      --table-name "$table_name" \
      --query "Table.GlobalSecondaryIndexes[?IndexName=='${index_name}'].IndexStatus | [0]" \
      --output text 2>/dev/null || echo "")"
    if [[ "$status" == "ACTIVE" ]]; then
      return 0
    fi
    sleep 5
  done
  echo "WARN: ${table_name}/${index_name} did not become ACTIVE within wait window." >&2
}

FILES_HAS_FILE_ID_INDEX="$(aws dynamodb describe-table \
  --region "$REGION" \
  --table-name Files \
  --query "contains(Table.GlobalSecondaryIndexes[].IndexName, 'FileIdIndex')" \
  --output text 2>/dev/null || echo False)"
if [[ "$FILES_HAS_FILE_ID_INDEX" != "True" ]]; then
  aws dynamodb update-table \
    --region "$REGION" \
    --table-name Files \
    --attribute-definitions AttributeName=fileId,AttributeType=S \
    --global-secondary-index-updates \
      '[{"Create":{"IndexName":"FileIdIndex","KeySchema":[{"AttributeName":"fileId","KeyType":"HASH"}],"Projection":{"ProjectionType":"ALL"},"ProvisionedThroughput":{"ReadCapacityUnits":1,"WriteCapacityUnits":1}}}]' \
    >/dev/null
  wait_gsi_active Files FileIdIndex
fi

FILES_HAS_CHECKSUM_INDEX="$(aws dynamodb describe-table \
  --region "$REGION" \
  --table-name Files \
  --query "contains(Table.GlobalSecondaryIndexes[].IndexName, 'ChecksumIndex')" \
  --output text 2>/dev/null || echo False)"
if [[ "$FILES_HAS_CHECKSUM_INDEX" != "True" ]]; then
  aws dynamodb update-table \
    --region "$REGION" \
    --table-name Files \
    --attribute-definitions AttributeName=checksum,AttributeType=S \
    --global-secondary-index-updates \
      '[{"Create":{"IndexName":"ChecksumIndex","KeySchema":[{"AttributeName":"checksum","KeyType":"HASH"}],"Projection":{"ProjectionType":"ALL"},"ProvisionedThroughput":{"ReadCapacityUnits":1,"WriteCapacityUnits":1}}}]' \
    >/dev/null
  wait_gsi_active Files ChecksumIndex
fi

rm -f "$BUILD_DIR/api.zip" "$BUILD_DIR/processing.zip"
(
  cd "$ROOT_DIR"
  zip -qr "$BUILD_DIR/api.zip" backend/__init__.py backend/cloud
  zip -qr "$BUILD_DIR/processing.zip" backend/__init__.py backend/cloud
)

cat >"$BUILD_DIR/lambda-trust.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

cat >"$BUILD_DIR/api-policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::${ORIGINALS_BUCKET}/*",
        "arn:aws:s3:::${THUMBNAILS_BUCKET}/*",
        "arn:aws:s3:::${QUERY_TEMP_BUCKET}/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"],
      "Resource": [
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/Files",
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/Files/index/*",
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/TagIndex",
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/Subscriptions",
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/Notifications"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["sns:Subscribe", "sns:SetSubscriptionAttributes"],
      "Resource": "${SNS_TOPIC_ARN}"
    }
  ]
}
JSON

DLQ_URL="$(aws sqs get-queue-url \
  --region "$REGION" \
  --queue-name aussie-ecolens-processing-dlq \
  --query QueueUrl \
  --output text 2>/dev/null || aws sqs create-queue \
    --region "$REGION" \
    --queue-name aussie-ecolens-processing-dlq \
    --attributes SqsManagedSseEnabled=true,MessageRetentionPeriod=1209600 \
    --tags Project=AussieEcoLens,Environment=test \
    --query QueueUrl \
    --output text)"

DLQ_ARN="$(aws sqs get-queue-attributes \
  --region "$REGION" \
  --queue-url "$DLQ_URL" \
  --attribute-names QueueArn \
  --query Attributes.QueueArn \
  --output text)"

PROCESS_QUEUE_URL="$(aws sqs get-queue-url \
  --region "$REGION" \
  --queue-name "$PROCESS_QUEUE_NAME" \
  --query QueueUrl \
  --output text 2>/dev/null || aws sqs create-queue \
    --region "$REGION" \
    --queue-name "$PROCESS_QUEUE_NAME" \
    --attributes SqsManagedSseEnabled=true \
    --tags Project=AussieEcoLens,Environment=test \
    --query QueueUrl \
    --output text)"
PROCESS_QUEUE_ARN="$(aws sqs get-queue-attributes \
  --region "$REGION" \
  --queue-url "$PROCESS_QUEUE_URL" \
  --attribute-names QueueArn \
  --query Attributes.QueueArn \
  --output text)"
PROCESS_QUEUE_ARN="$PROCESS_QUEUE_ARN" \
DLQ_ARN="$DLQ_ARN" \
ORIGINALS_BUCKET="$ORIGINALS_BUCKET" \
ACCOUNT_ID="$ACCOUNT_ID" \
PROCESS_VISIBILITY_TIMEOUT="$PROCESS_VISIBILITY_TIMEOUT" \
python3 - <<'PY' >"$BUILD_DIR/processing-queue-attributes.json"
import json
import os

queue_arn = os.environ["PROCESS_QUEUE_ARN"]
dlq_arn = os.environ["DLQ_ARN"]
originals_bucket = os.environ["ORIGINALS_BUCKET"]
account_id = os.environ["ACCOUNT_ID"]
visibility_timeout = os.environ["PROCESS_VISIBILITY_TIMEOUT"]
policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowS3PendingUploadNotifications",
            "Effect": "Allow",
            "Principal": {"Service": "s3.amazonaws.com"},
            "Action": "sqs:SendMessage",
            "Resource": queue_arn,
            "Condition": {
                "ArnEquals": {"aws:SourceArn": f"arn:aws:s3:::{originals_bucket}"},
                "StringEquals": {"aws:SourceAccount": account_id},
            },
        }
    ],
}
attributes = {
    "VisibilityTimeout": visibility_timeout,
    "MessageRetentionPeriod": "1209600",
    "SqsManagedSseEnabled": "true",
    "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 3}),
    "Policy": json.dumps(policy),
}
print(json.dumps(attributes))
PY
aws sqs set-queue-attributes \
  --region "$REGION" \
  --queue-url "$PROCESS_QUEUE_URL" \
  --attributes "file://${BUILD_DIR}/processing-queue-attributes.json"

cat >"$BUILD_DIR/processing-policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::${ORIGINALS_BUCKET}/*",
        "arn:aws:s3:::${THUMBNAILS_BUCKET}/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
      "Resource": [
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/Files",
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/TagIndex",
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/Subscriptions",
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/Notifications"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "${SNS_TOPIC_ARN}"
    },
    {
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${DLQ_ARN}"
    },
    {
      "Effect": "Allow",
      "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"],
      "Resource": "${PROCESS_QUEUE_ARN}"
    }
  ]
}
JSON

ensure_role() {
  local role_name="$1"
  local policy_name="$2"
  local policy_file="$3"

  if ! aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
    aws iam create-role \
      --role-name "$role_name" \
      --assume-role-policy-document "file://${BUILD_DIR}/lambda-trust.json" \
      >/dev/null
  fi
  aws iam put-role-policy \
    --role-name "$role_name" \
    --policy-name "$policy_name" \
    --policy-document "file://${policy_file}"
}

ensure_role "$API_ROLE_NAME" "AussieEcoLensApiPolicy" "$BUILD_DIR/api-policy.json"
ensure_role "$PROCESS_ROLE_NAME" "AussieEcoLensProcessingPolicy" "$BUILD_DIR/processing-policy.json"
sleep 8

API_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${API_ROLE_NAME}"
PROCESS_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${PROCESS_ROLE_NAME}"

cat >"$BUILD_DIR/api-env.json" <<JSON
{
  "Variables": {
    "ORIGINALS_BUCKET": "${ORIGINALS_BUCKET}",
    "THUMBNAILS_BUCKET": "${THUMBNAILS_BUCKET}",
    "QUERY_TEMP_BUCKET": "${QUERY_TEMP_BUCKET}",
    "FILES_TABLE_NAME": "Files",
    "TAG_INDEX_TABLE_NAME": "TagIndex",
    "SUBSCRIPTIONS_TABLE_NAME": "Subscriptions",
    "NOTIFICATIONS_TABLE_NAME": "Notifications",
    "SNS_TOPIC_ARN": "${SNS_TOPIC_ARN}",
    "GCP_INFER_URL": "${GCP_INFER_URL}",
    "MODEL_VERSION": "${MODEL_VERSION}",
    "COGNITO_REGION": "${REGION}",
    "COGNITO_USER_POOL_ID": "${USER_POOL_ID}",
    "COGNITO_APP_CLIENT_ID": "${APP_CLIENT_ID}",
    "COGNITO_DOMAIN": "${COGNITO_DOMAIN}",
    "COGNITO_REDIRECT_URI": "${COGNITO_REDIRECT_URI}",
    "QUERY_INFER_TIMEOUT_SECONDS": "${API_QUERY_INFER_TIMEOUT_SECONDS}",
    "API_BASE_URL": "${API_BASE_URL}"
  }
}
JSON

cat >"$BUILD_DIR/processing-env.json" <<JSON
{
  "Variables": {
    "ORIGINALS_BUCKET": "${ORIGINALS_BUCKET}",
    "THUMBNAILS_BUCKET": "${THUMBNAILS_BUCKET}",
    "QUERY_TEMP_BUCKET": "${QUERY_TEMP_BUCKET}",
    "FILES_TABLE_NAME": "Files",
    "TAG_INDEX_TABLE_NAME": "TagIndex",
    "SUBSCRIPTIONS_TABLE_NAME": "Subscriptions",
    "NOTIFICATIONS_TABLE_NAME": "Notifications",
    "SNS_TOPIC_ARN": "${SNS_TOPIC_ARN}",
    "GCP_INFER_URL": "${GCP_INFER_URL}",
    "MODEL_VERSION": "${MODEL_VERSION}",
    "PROCESS_QUEUE_URL": "${PROCESS_QUEUE_URL}",
    "INFER_TIMEOUT_SECONDS": "${PROCESS_INFER_TIMEOUT_SECONDS}"
  }
}
JSON

ensure_function() {
  local function_name="$1"
  local role_arn="$2"
  local handler="$3"
  local zip_file="$4"
  local env_file="$5"
  local timeout="$6"
  local memory="$7"

  if aws lambda get-function --region "$REGION" --function-name "$function_name" >/dev/null 2>&1; then
    aws lambda update-function-code \
      --region "$REGION" \
      --function-name "$function_name" \
      --zip-file "fileb://${zip_file}" \
      >/dev/null
    aws lambda wait function-updated --region "$REGION" --function-name "$function_name"
    aws lambda update-function-configuration \
      --region "$REGION" \
      --function-name "$function_name" \
      --role "$role_arn" \
      --handler "$handler" \
      --runtime python3.12 \
      --timeout "$timeout" \
      --memory-size "$memory" \
      --environment "file://${env_file}" \
      >/dev/null
  else
    aws lambda create-function \
      --region "$REGION" \
      --function-name "$function_name" \
      --role "$role_arn" \
      --handler "$handler" \
      --runtime python3.12 \
      --timeout "$timeout" \
      --memory-size "$memory" \
      --environment "file://${env_file}" \
      --zip-file "fileb://${zip_file}" \
      >/dev/null
  fi
  aws lambda wait function-active-v2 --region "$REGION" --function-name "$function_name"
}

ensure_function \
  "$API_FUNCTION" \
  "$API_ROLE_ARN" \
  backend.cloud.aws_api_handler.lambda_handler \
  "$BUILD_DIR/api.zip" \
  "$BUILD_DIR/api-env.json" \
  45 \
  "$API_MEMORY_SIZE"

ensure_function \
  "$PROCESS_FUNCTION" \
  "$PROCESS_ROLE_ARN" \
  backend.cloud.aws_processing_handler.lambda_handler \
  "$BUILD_DIR/processing.zip" \
  "$BUILD_DIR/processing-env.json" \
  900 \
  "$PROCESS_MEMORY_SIZE"

aws lambda update-function-configuration \
  --region "$REGION" \
  --function-name "$PROCESS_FUNCTION" \
  --dead-letter-config "TargetArn=${DLQ_ARN}" \
  >/dev/null
aws lambda wait function-updated --region "$REGION" --function-name "$PROCESS_FUNCTION"

if ! aws lambda put-function-concurrency \
  --region "$REGION" \
  --function-name "$PROCESS_FUNCTION" \
  --reserved-concurrent-executions "$PROCESS_RESERVED_CONCURRENCY" \
  >/dev/null 2>"$BUILD_DIR/put-function-concurrency.err"; then
  echo "WARN: Lambda reserved concurrency could not be set; using SQS event source maximum concurrency instead." >&2
  cat "$BUILD_DIR/put-function-concurrency.err" >&2
fi

for function_name in "$API_FUNCTION" "$PROCESS_FUNCTION"; do
  log_group="/aws/lambda/${function_name}"
  aws logs create-log-group --region "$REGION" --log-group-name "$log_group" 2>/dev/null || true
  aws logs put-retention-policy --region "$REGION" --log-group-name "$log_group" --retention-in-days 7
done

MAPPING_UUID="$(aws lambda list-event-source-mappings \
  --region "$REGION" \
  --function-name "$PROCESS_FUNCTION" \
  --event-source-arn "$PROCESS_QUEUE_ARN" \
  --query "EventSourceMappings[0].UUID" \
  --output text)"
if [[ "$MAPPING_UUID" == "None" ]]; then
  aws lambda create-event-source-mapping \
    --region "$REGION" \
    --function-name "$PROCESS_FUNCTION" \
    --event-source-arn "$PROCESS_QUEUE_ARN" \
    --batch-size "$PROCESS_BATCH_SIZE" \
    --maximum-batching-window-in-seconds 0 \
    --scaling-config "MaximumConcurrency=${PROCESS_RESERVED_CONCURRENCY}" \
    --enabled \
    >/dev/null
else
  aws lambda update-event-source-mapping \
    --region "$REGION" \
    --uuid "$MAPPING_UUID" \
    --batch-size "$PROCESS_BATCH_SIZE" \
    --maximum-batching-window-in-seconds 0 \
    --scaling-config "MaximumConcurrency=${PROCESS_RESERVED_CONCURRENCY}" \
    --enabled \
    >/dev/null
fi

cat >"$BUILD_DIR/s3-notification.json" <<JSON
{
  "QueueConfigurations": [
    {
      "Id": "AussieEcoLensPendingUploadQueue",
      "QueueArn": "${PROCESS_QUEUE_ARN}",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [{"Name": "prefix", "Value": "users/"}]
        }
      }
    }
  ]
}
JSON
aws s3api put-bucket-notification-configuration \
  --bucket "$ORIGINALS_BUCKET" \
  --notification-configuration "file://${BUILD_DIR}/s3-notification.json"

API_ID="$(aws apigatewayv2 get-apis \
  --region "$REGION" \
  --query "Items[?Name=='${HTTP_API_NAME}'].ApiId | [0]" \
  --output text)"
if [[ "$API_ID" == "None" ]]; then
  API_ID="$(aws apigatewayv2 create-api \
    --region "$REGION" \
    --name "$HTTP_API_NAME" \
    --protocol-type HTTP \
    --cors-configuration \
      '{"AllowOrigins":["*"],"AllowHeaders":["authorization","content-type"],"AllowMethods":["GET","POST","OPTIONS"]}' \
    --query ApiId \
    --output text)"
fi
aws apigatewayv2 update-api \
  --region "$REGION" \
  --api-id "$API_ID" \
  --cors-configuration \
    '{"AllowOrigins":["*"],"AllowHeaders":["authorization","content-type"],"AllowMethods":["GET","POST","OPTIONS"]}' \
  >/dev/null

HTTP_API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com"
API_BASE_URL="${API_BASE_URL:-$HTTP_API_URL}"
cat >"$BUILD_DIR/api-env.json" <<JSON
{
  "Variables": {
    "ORIGINALS_BUCKET": "${ORIGINALS_BUCKET}",
    "THUMBNAILS_BUCKET": "${THUMBNAILS_BUCKET}",
    "QUERY_TEMP_BUCKET": "${QUERY_TEMP_BUCKET}",
    "FILES_TABLE_NAME": "Files",
    "TAG_INDEX_TABLE_NAME": "TagIndex",
    "SUBSCRIPTIONS_TABLE_NAME": "Subscriptions",
    "NOTIFICATIONS_TABLE_NAME": "Notifications",
    "SNS_TOPIC_ARN": "${SNS_TOPIC_ARN}",
    "GCP_INFER_URL": "${GCP_INFER_URL}",
    "MODEL_VERSION": "${MODEL_VERSION}",
    "COGNITO_REGION": "${REGION}",
    "COGNITO_USER_POOL_ID": "${USER_POOL_ID}",
    "COGNITO_APP_CLIENT_ID": "${APP_CLIENT_ID}",
    "COGNITO_DOMAIN": "${COGNITO_DOMAIN}",
    "COGNITO_REDIRECT_URI": "${COGNITO_REDIRECT_URI}",
    "QUERY_INFER_TIMEOUT_SECONDS": "${API_QUERY_INFER_TIMEOUT_SECONDS}",
    "API_BASE_URL": "${API_BASE_URL}"
  }
}
JSON
aws lambda update-function-configuration \
  --region "$REGION" \
  --function-name "$API_FUNCTION" \
  --environment "file://${BUILD_DIR}/api-env.json" \
  >/dev/null
aws lambda wait function-updated --region "$REGION" --function-name "$API_FUNCTION"

API_FUNCTION_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${API_FUNCTION}"
INTEGRATION_ID="$(aws apigatewayv2 get-integrations \
  --region "$REGION" \
  --api-id "$API_ID" \
  --query "Items[?IntegrationUri=='${API_FUNCTION_ARN}'].IntegrationId | [0]" \
  --output text)"
if [[ "$INTEGRATION_ID" == "None" ]]; then
  INTEGRATION_ID="$(aws apigatewayv2 create-integration \
    --region "$REGION" \
    --api-id "$API_ID" \
    --integration-type AWS_PROXY \
    --integration-uri "$API_FUNCTION_ARN" \
    --payload-format-version 2.0 \
    --query IntegrationId \
    --output text)"
fi

AUTHORIZER_ID="$(aws apigatewayv2 get-authorizers \
  --region "$REGION" \
  --api-id "$API_ID" \
  --query "Items[?Name=='CognitoJwt'].AuthorizerId | [0]" \
  --output text)"
if [[ "$AUTHORIZER_ID" == "None" ]]; then
  AUTHORIZER_ID="$(aws apigatewayv2 create-authorizer \
    --region "$REGION" \
    --api-id "$API_ID" \
    --name CognitoJwt \
    --authorizer-type JWT \
    --identity-source '$request.header.Authorization' \
    --jwt-configuration \
      "Audience=${APP_CLIENT_ID},Issuer=https://cognito-idp.${REGION}.amazonaws.com/${USER_POOL_ID}" \
    --query AuthorizerId \
    --output text)"
fi

ROUTE_ID="$(aws apigatewayv2 get-routes \
  --region "$REGION" \
  --api-id "$API_ID" \
  --query "Items[?RouteKey=='\$default'].RouteId | [0]" \
  --output text)"
if [[ "$ROUTE_ID" == "None" ]]; then
  aws apigatewayv2 create-route \
    --region "$REGION" \
    --api-id "$API_ID" \
    --route-key '$default' \
    --authorization-type JWT \
    --authorizer-id "$AUTHORIZER_ID" \
    --target "integrations/${INTEGRATION_ID}" \
    >/dev/null
fi

ensure_public_route() {
  local route_key="$1"
  local route_id
  route_id="$(aws apigatewayv2 get-routes \
    --region "$REGION" \
    --api-id "$API_ID" \
    --query "Items[?RouteKey=='${route_key}'].RouteId | [0]" \
    --output text)"
  if [[ "$route_id" == "None" ]]; then
    aws apigatewayv2 create-route \
      --region "$REGION" \
      --api-id "$API_ID" \
      --route-key "$route_key" \
      --authorization-type NONE \
      --target "integrations/${INTEGRATION_ID}" \
      >/dev/null
  else
    aws apigatewayv2 update-route \
      --region "$REGION" \
      --api-id "$API_ID" \
      --route-id "$route_id" \
      --authorization-type NONE \
      --target "integrations/${INTEGRATION_ID}" \
      >/dev/null
  fi
}

ensure_public_route "GET /api/config"
ensure_public_route "OPTIONS /{proxy+}"

STAGE_NAME="$(aws apigatewayv2 get-stages \
  --region "$REGION" \
  --api-id "$API_ID" \
  --query "Items[?StageName=='\$default'].StageName | [0]" \
  --output text)"
if [[ "$STAGE_NAME" == "None" ]]; then
  aws apigatewayv2 create-stage \
    --region "$REGION" \
    --api-id "$API_ID" \
    --stage-name '$default' \
    --auto-deploy \
    >/dev/null
fi

aws lambda add-permission \
  --region "$REGION" \
  --function-name "$API_FUNCTION" \
  --statement-id AllowHttpApiInvoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*" \
  >/dev/null 2>&1 || true

echo "HTTP_API_URL=${HTTP_API_URL}"
echo "GCP_INFER_URL=${GCP_INFER_URL}"
echo "PROCESS_QUEUE_URL=${PROCESS_QUEUE_URL}"
echo "PROCESS_RESERVED_CONCURRENCY=${PROCESS_RESERVED_CONCURRENCY}"
echo "API_MEMORY_SIZE=${API_MEMORY_SIZE}"
echo "PROCESS_MEMORY_SIZE=${PROCESS_MEMORY_SIZE}"
echo "PROCESS_VISIBILITY_TIMEOUT=${PROCESS_VISIBILITY_TIMEOUT}"
echo "PROCESS_INFER_TIMEOUT_SECONDS=${PROCESS_INFER_TIMEOUT_SECONDS}"
