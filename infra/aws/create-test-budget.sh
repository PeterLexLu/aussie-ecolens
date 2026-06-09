#!/usr/bin/env bash
set -euo pipefail

ACCOUNT_ID="${AWS_ACCOUNT_ID:-203276832845}"
ALERT_EMAIL="${AWS_BUDGET_ALERT_EMAIL:?Set AWS_BUDGET_ALERT_EMAIL before running this script.}"
BUDGET_NAME="AussieEcoLens-Test-Monthly-US\$3"

cat >/tmp/aussie-ecolens-budget.json <<'JSON'
{
  "BudgetName": "AussieEcoLens-Test-Monthly-US$3",
  "BudgetLimit": {"Amount": "3", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
JSON

cat >/tmp/aussie-ecolens-budget-notifications.json <<JSON
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 1,
      "ThresholdType": "ABSOLUTE_VALUE"
    },
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}"}]
  },
  {
    "Notification": {
      "NotificationType": "FORECASTED",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 3,
      "ThresholdType": "ABSOLUTE_VALUE"
    },
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}"}]
  }
]
JSON

if aws budgets describe-budget \
  --account-id "$ACCOUNT_ID" \
  --budget-name "$BUDGET_NAME" \
  >/dev/null 2>&1; then
  echo "Budget already exists: ${BUDGET_NAME}"
else
  aws budgets create-budget \
    --account-id "$ACCOUNT_ID" \
    --budget file:///tmp/aussie-ecolens-budget.json \
    --notifications-with-subscribers \
      file:///tmp/aussie-ecolens-budget-notifications.json
fi
