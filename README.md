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

## 作品集与流程文件

本项目的产品管理、开发交付、测试验收、客户交接、个人职责和保密说明集中保存在
[`portfolio-process/`](portfolio-process/README.md) 目录中。

### 项目背景

- 本项目是面向澳大利亚原生野生动物保护公益组织的多云基础设施、后端能力和机器学习推理集成外包项目。
- 本团队不负责最终产品 UI。仓库中的 UI 仅用于客户 Demo、浏览器功能测试和端到端集成验证，不能代表最终正式界面。
- 客户的正式 UI 由独立 UI 外包团队负责。在交付阶段，本团队向该团队说明 API Contract、身份认证、媒体处理状态、错误处理和权限边界。
- 项目流程包括：第一周与客户沟通并完成 PRD；第二周完成项目规划、30 个 User Stories 和甘特图；随后进行六周开发、两周系统测试与客户 Demo，以及一周正式交付和 UI 团队交接。
- 六周开发期间，每周一举行 Stand-up Meeting，安排当周需要完成的 User Stories；每周五结算完成情况、验收证据、Carry-over 工作和阻塞问题。
- 项目在 2026 年 6 月底完成交接，之后进入代码售后和偶发改进阶段。

### 保密协议与信息截止日期

本项目在与客户签订保密协议（NDA）的前提下完成。当前公开仓库是经过保密处理的作品集版本：部分名称、数据、参数、配置、部署细节、接口和实现方式可能经过匿名化、删除、替换或调整。本仓库不能被视为客户正式生产系统的完整副本。

本仓库中的作品集、产品、流程、技术和交付信息仅更新至 **2026 年 6 月 23 日**。该日期之后发生的代码售后修改、配置调整、缺陷修复、需求变化和技术决策均不包含在当前仓库中。完整说明请参阅
[`保密与信息截止日期说明`](portfolio-process/CONFIDENTIALITY_NOTICE.md)。

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
