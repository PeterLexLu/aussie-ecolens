# Aussie EcoLens

Aussie EcoLens is a multi-cloud serverless application for wildlife media
upload, inference, search, tagging, deletion, and notification workflows.

## Main Components

- `frontend/` static browser UI served through CloudFront.
- `backend/` local API modules, AWS Lambda handlers, auth helpers, storage,
  database, notification, and GCP inference client code.
- `infra/aws/` AWS deployment scripts and infrastructure templates.
- `backend/ml/gcp-inference/` Google Cloud Run inference service.
- `tests/` backend and integration tests.

## Test

```bash
PYTHONPATH=. pytest tests/backend tests/integration -q
```

## Deploy

AWS test environment:

```bash
bash infra/aws/deploy-test-cloud.sh
```

Frontend:

```bash
bash infra/aws/deploy-frontend-cloud.sh
```
