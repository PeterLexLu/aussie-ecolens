# 开发与交付流程

## 1. 看板状态

`Backlog → Ready → In Progress → Review → Testing → Done`

每位成员同时进行中的任务建议不超过两个，优先完成已开始的工作。

## 2. 固定会议节奏

开发六周内每周举行两次 Stand-up Meeting：

- **周一计划：** 从 30 个 User Stories 中选择当周范围，明确负责人、依赖和验收方式。
- **周五结算：** 根据 Demo 或测试证据确认 Done、Carry-over 或 Blocked，并更新甘特图和下周候选范围。

不要求每日站会，临时技术问题由相关成员单独同步。

## 3. 分支策略

- `main`：可部署、可演示版本。
- `develop`：迭代集成分支。
- `feature/<scope>`：新功能。
- `fix/<scope>`：缺陷修复。
- `hotfix/<scope>`：发布阻塞问题。

示例：

- `feature/upload-progress`
- `feature/species-subscription`
- `fix/owner-permission-check`
- `fix/video-processing-timeout`

## 4. 开发步骤

1. 从最新集成分支创建短生命周期分支。
2. 开发前确认用户故事和验收标准。
3. 完成实现、测试和必要文档。
4. 提交前运行与改动最相关的检查。
5. 创建 Pull Request 并说明影响范围。
6. Reviewer 检查业务、权限、异常路径和可维护性。
7. 测试通过后合并，避免长期分支积累。
8. 在集成环境执行端到端验证。

## 5. Commit 规范

- `feat: add upload progress feedback`
- `fix: validate ownership before media deletion`
- `test: cover duplicate upload workflow`
- `docs: add deployment prerequisites`
- `refactor: align inference response mapping`

提交应描述一个清晰目的，避免使用 `update`、`final` 或 `fix bug` 等含义不明的信息。

## 6. Pull Request 模板

### What

说明本次修改内容。

### Why

说明对应的用户问题、用户故事或缺陷。

### Scope

- [ ] Demo / test client
- [ ] AWS backend
- [ ] GCP inference
- [ ] Infrastructure
- [ ] Tests / Documentation

### Validation

列出执行过的自动化测试、手工验证和结果。

### Security and data

- 是否改变认证或授权逻辑？
- 是否引入新的环境变量？
- 是否涉及个人数据、日志或受保护媒体？

### Risk and rollback

说明潜在影响和恢复方式。

## 7. Review 检查重点

- 后端是否从认证信息推导用户身份。
- 所有权检查是否发生在可信边界内。
- 异步任务是否支持幂等和失败重试。
- 跨云请求与响应格式是否保持兼容。
- 错误是否可诊断且不泄露敏感信息。
- Demo/测试客户端是否足以验证加载、空状态、成功和失败；不以最终 UI 视觉质量作为后端交付标准。
- 测试是否覆盖正常路径与主要异常路径。

## 8. 发布流程

1. 确认 P0 验收完成。
2. 运行后端、集成和权限测试。
3. 检查 AWS 与 GCP 环境配置。
4. 部署发布候选版本。
5. 执行核心链路 Smoke Test。
6. 创建版本标签并记录已知限制。
7. 如果关键指标或主链路异常，按回滚方案恢复上一稳定版本。
