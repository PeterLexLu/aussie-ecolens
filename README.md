# Aussie EcoLens

Aussie EcoLens is a multi-cloud serverless application for wildlife media
upload, inference, search, tagging, deletion, and notification workflows.

## Portfolio and Process Files

Product-management, delivery, testing, handover, role-contribution, and
confidentiality documentation is available in
[`portfolio-process/`](portfolio-process/README.md).

### Project context

- This was a multi-cloud infrastructure, backend, and machine-learning
  integration engagement for an Australian native-wildlife conservation
  non-profit organisation.
- The delivery team did not own the final product UI. The UI in this repository
  was created only for demonstrations, browser-based functional testing, and
  end-to-end integration validation.
- The client's production UI was delivered by a separate UI vendor. During
  handover, our team supported that vendor with API contracts, authentication,
  processing states, error handling, and permission boundaries.
- The documented delivery lifecycle consisted of one week of client discovery
  and PRD preparation, one week of planning and 30 user stories, six weeks of
  development, two weeks of testing and client demonstrations, and one week of
  delivery and UI-vendor handover.
- During development, stand-up meetings were held every Monday to plan the
  week's user stories and every Friday to review delivery, acceptance evidence,
  carry-over work, and blockers.
- Handover was completed by the end of June 2026. The team subsequently moved
  into after-sales code support and occasional improvement work.

### Confidentiality and information cut-off

This project was delivered under a Non-Disclosure Agreement. The public
repository is a portfolio-safe version: names, data, parameters, configurations,
deployment details, interfaces, and implementation details may have been
anonymised, removed, replaced, or modified. It must not be treated as a complete
copy of the client's production system.

All portfolio, product, process, technical, and delivery information in this
repository is current only up to **23 June 2026**. Later after-sales code changes,
configuration updates, bug fixes, requirement changes, and technical decisions
are outside the scope of this repository. See the full
[`Confidentiality and Information Cut-off Notice`](portfolio-process/CONFIDENTIALITY_NOTICE.md).

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
