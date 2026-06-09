#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-203276832845}"
ORIGINALS_BUCKET="aussie-ecolens-originals-${ACCOUNT_ID}"
THUMBNAILS_BUCKET="aussie-ecolens-thumbnails-${ACCOUNT_ID}"
QUERY_TEMP_BUCKET="aussie-ecolens-query-temp-${ACCOUNT_ID}"

create_bucket() {
  local bucket="$1"

  if ! aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
    aws s3api create-bucket --bucket "$bucket" --region "$REGION" >/dev/null
  fi

  aws s3api put-public-access-block \
    --bucket "$bucket" \
    --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-encryption \
    --bucket "$bucket" \
    --server-side-encryption-configuration \
      '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":false}]}'
  aws s3api put-bucket-tagging \
    --bucket "$bucket" \
    --tagging \
      'TagSet=[{Key=Project,Value=AussieEcoLens},{Key=Environment,Value=test}]'
}

create_bucket "$ORIGINALS_BUCKET"
create_bucket "$THUMBNAILS_BUCKET"
create_bucket "$QUERY_TEMP_BUCKET"

BUILD_DIR="$(mktemp -d)"
CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:8000,https://d3m1q0eazv9ntq.cloudfront.net}" BUILD_DIR="$BUILD_DIR" \
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/configure-s3-cors.sh"

aws s3api put-bucket-versioning \
  --bucket "$ORIGINALS_BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$ORIGINALS_BUCKET" \
  --lifecycle-configuration \
    '{"Rules":[{"ID":"ExpireNoncurrentVersions","Status":"Enabled","Filter":{"Prefix":""},"NoncurrentVersionExpiration":{"NoncurrentDays":7}},{"ID":"AbortIncompleteMultipartUploads","Status":"Enabled","Filter":{"Prefix":""},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}'

aws s3api put-bucket-versioning \
  --bucket "$THUMBNAILS_BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$THUMBNAILS_BUCKET" \
  --lifecycle-configuration \
    '{"Rules":[{"ID":"ExpireNoncurrentVersions","Status":"Enabled","Filter":{"Prefix":""},"NoncurrentVersionExpiration":{"NoncurrentDays":3}},{"ID":"AbortIncompleteMultipartUploads","Status":"Enabled","Filter":{"Prefix":""},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}'

aws s3api put-bucket-lifecycle-configuration \
  --bucket "$QUERY_TEMP_BUCKET" \
  --lifecycle-configuration \
    '{"Rules":[{"ID":"ExpireTempObjects","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":1}},{"ID":"AbortIncompleteMultipartUploads","Status":"Enabled","Filter":{"Prefix":""},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}'

if ! aws dynamodb describe-table --region "$REGION" --table-name Files >/dev/null 2>&1; then
  aws dynamodb create-table \
    --region "$REGION" \
    --table-name Files \
    --attribute-definitions \
      AttributeName=ownerId,AttributeType=S \
      AttributeName=fileId,AttributeType=S \
      AttributeName=checksum,AttributeType=S \
      AttributeName=createdAt,AttributeType=S \
    --key-schema \
      AttributeName=ownerId,KeyType=HASH \
      AttributeName=fileId,KeyType=RANGE \
    --provisioned-throughput ReadCapacityUnits=3,WriteCapacityUnits=3 \
    --global-secondary-indexes \
      '[{"IndexName":"OwnerChecksumIndex","KeySchema":[{"AttributeName":"ownerId","KeyType":"HASH"},{"AttributeName":"checksum","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"},"ProvisionedThroughput":{"ReadCapacityUnits":1,"WriteCapacityUnits":1}},{"IndexName":"OwnerCreatedAtIndex","KeySchema":[{"AttributeName":"ownerId","KeyType":"HASH"},{"AttributeName":"createdAt","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"},"ProvisionedThroughput":{"ReadCapacityUnits":1,"WriteCapacityUnits":1}},{"IndexName":"FileIdIndex","KeySchema":[{"AttributeName":"fileId","KeyType":"HASH"}],"Projection":{"ProjectionType":"ALL"},"ProvisionedThroughput":{"ReadCapacityUnits":1,"WriteCapacityUnits":1}}]' \
    >/dev/null
fi

if ! aws dynamodb describe-table --region "$REGION" --table-name TagIndex >/dev/null 2>&1; then
  aws dynamodb create-table \
    --region "$REGION" \
    --table-name TagIndex \
    --attribute-definitions \
      AttributeName=ownerTag,AttributeType=S \
      AttributeName=fileId,AttributeType=S \
    --key-schema \
      AttributeName=ownerTag,KeyType=HASH \
      AttributeName=fileId,KeyType=RANGE \
    --provisioned-throughput ReadCapacityUnits=3,WriteCapacityUnits=3 \
    >/dev/null
fi

if ! aws dynamodb describe-table --region "$REGION" --table-name Subscriptions >/dev/null 2>&1; then
  aws dynamodb create-table \
    --region "$REGION" \
    --table-name Subscriptions \
    --attribute-definitions \
      AttributeName=ownerTag,AttributeType=S \
      AttributeName=subscriptionId,AttributeType=S \
    --key-schema \
      AttributeName=ownerTag,KeyType=HASH \
      AttributeName=subscriptionId,KeyType=RANGE \
    --provisioned-throughput ReadCapacityUnits=2,WriteCapacityUnits=2 \
    >/dev/null
fi

if ! aws dynamodb describe-table --region "$REGION" --table-name Notifications >/dev/null 2>&1; then
  aws dynamodb create-table \
    --region "$REGION" \
    --table-name Notifications \
    --attribute-definitions \
      AttributeName=ownerId,AttributeType=S \
      AttributeName=notificationId,AttributeType=S \
    --key-schema \
      AttributeName=ownerId,KeyType=HASH \
      AttributeName=notificationId,KeyType=RANGE \
    --provisioned-throughput ReadCapacityUnits=2,WriteCapacityUnits=2 \
    >/dev/null
fi

for table in Files TagIndex Subscriptions Notifications; do
  aws dynamodb wait table-exists --region "$REGION" --table-name "$table"
done

aws sns create-topic \
  --region "$REGION" \
  --name aussie-ecolens-notifications \
  --tags Key=Project,Value=AussieEcoLens Key=Environment,Value=test \
  >/dev/null

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
  --queue-name aussie-ecolens-processing-queue \
  --query QueueUrl \
  --output text 2>/dev/null || aws sqs create-queue \
    --region "$REGION" \
    --queue-name aussie-ecolens-processing-queue \
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
python3 - <<'PY' >"${BUILD_DIR}/processing-queue-attributes.json"
import json
import os

policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowS3PendingUploadNotifications",
            "Effect": "Allow",
            "Principal": {"Service": "s3.amazonaws.com"},
            "Action": "sqs:SendMessage",
            "Resource": os.environ["PROCESS_QUEUE_ARN"],
            "Condition": {
                "ArnEquals": {"aws:SourceArn": f"arn:aws:s3:::{os.environ['ORIGINALS_BUCKET']}"},
                "StringEquals": {"aws:SourceAccount": os.environ["ACCOUNT_ID"]},
            },
        }
    ],
}
attributes = {
    "VisibilityTimeout": "960",
    "MessageRetentionPeriod": "1209600",
    "SqsManagedSseEnabled": "true",
    "RedrivePolicy": json.dumps({"deadLetterTargetArn": os.environ["DLQ_ARN"], "maxReceiveCount": 3}),
    "Policy": json.dumps(policy),
}
print(json.dumps(attributes))
PY
aws sqs set-queue-attributes \
  --region "$REGION" \
  --queue-url "$PROCESS_QUEUE_URL" \
  --attributes "file://${BUILD_DIR}/processing-queue-attributes.json"

echo "Aussie EcoLens free-tier test base is ready in ${REGION}."
