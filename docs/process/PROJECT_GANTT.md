# 项目甘特图

> 时间轴用于展示项目阶段顺序。图中的起始日期用于表达阶段长度，并非已验证的实际会议日期；对外发布前应根据原会议邀请、PRD 版本记录和交接记录校准。

```mermaid
gantt
    title Aussie EcoLens 项目交付计划
    dateFormat  YYYY-MM-DD
    axisFormat  %m/%d

    section 需求与规划
    客户需求沟通与PRD        :a1, 2026-03-16, 5d
    30个User Stories与甘特图 :a2, after a1, 5d

    section 六周开发
    认证、基础设施与上传       :d1, after a2, 5d
    异步处理与图片推理         :d2, after d1, 5d
    视频处理与结果持久化       :d3, after d2, 5d
    媒体管理与查询             :d4, after d3, 5d
    权限、标签、删除与通知     :d5, after d4, 5d
    可靠性与开发收敛           :d6, after d5, 5d

    section 测试与客户反馈
    系统与跨云集成测试         :t1, after d6, 5d
    客户Demo与反馈改进         :t2, after t1, 5d

    section 交付与维护
    客户及UI供应商交接         :r1, after t2, 5d
    代码售后与按需改进         :active, r2, after r1, 20d
```

## 阶段门禁

| Gate | 进入条件 | 退出条件 |
| --- | --- | --- |
| G1 需求确认 | 客户目标和使用场景已沟通 | PRD 经内部可行性 Review |
| G2 进入开发 | 30 个 Stories、依赖和甘特图完成 | 当周 Stories 可测试、可分配 |
| G3 开发完成 | Must Stories 进入验收 | 核心链路通过内部 Demo |
| G4 客户验收 | 系统测试和 Demo 环境准备完成 | 客户反馈已记录并完成约定改进 |
| G5 正式交付 | 发布候选版本稳定 | 文档、接口和 UI 供应商交接完成 |
| G6 售后维护 | 交付完成 | 持续按问题单响应，无固定结束日期 |
