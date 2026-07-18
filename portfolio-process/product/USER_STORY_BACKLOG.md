# Product Backlog：30 个 User Stories

> 以下 User Stories 根据客户需求和已交付能力补录，用于呈现需求拆解和项目跟踪方法。优先级分为 Must、Should 和 Could。

| ID | Epic | User Story | 优先级 |
| --- | --- | --- | --- |
| US-01 | Authentication | 作为注册用户，我希望安全登录系统，以便访问受保护的野生动物媒体能力。 | Must |
| US-02 | Authentication | 作为用户，我希望退出登录，以便结束当前会话。 | Must |
| US-03 | Authentication | 作为系统所有者，我希望后端验证 Cognito Token，以免未经认证的请求访问资源。 | Must |
| US-04 | Upload | 作为用户，我希望上传野生动物图片，以便系统执行识别。 | Must |
| US-05 | Upload | 作为用户，我希望上传野生动物视频，以便系统按时间采样并识别。 | Must |
| US-06 | Upload | 作为用户，我希望收到上传成功或失败结果，以便知道是否需要重试。 | Must |
| US-07 | Upload | 作为客户，我希望系统识别重复文件，以免重复存储和推理。 | Should |
| US-08 | Processing | 作为系统所有者，我希望上传任务异步进入队列，以便长时间推理不阻塞请求。 | Must |
| US-09 | Processing | 作为系统所有者，我希望失败任务能够重试，以提高处理可靠性。 | Must |
| US-10 | Inference | 作为用户，我希望图片得到自动物种标签，以便快速理解媒体内容。 | Must |
| US-11 | Inference | 作为用户，我希望视频按每秒一帧抽样识别，以便在合理成本下分析视频。 | Must |
| US-12 | Inference | 作为用户，我希望视频帧结果被聚合，以便获得简洁的媒体级标签。 | Must |
| US-13 | Thumbnail | 作为用户，我希望系统生成压缩缩略图，以便快速浏览媒体结果。 | Must |
| US-14 | Metadata | 作为客户，我希望保存文件、所有者、标签和处理结果，以便后续查询和管理。 | Must |
| US-15 | Library | 作为用户，我希望查询自己拥有的媒体，以便管理个人记录。 | Must |
| US-16 | Library | 作为用户，我希望查看允许共享的媒体，以便发现其他记录。 | Must |
| US-17 | Search | 作为用户，我希望按物种标签搜索，以便找到指定动物的媒体。 | Must |
| US-18 | Search | 作为用户，我希望按标签数量条件查询，以便筛选符合条件的结果。 | Should |
| US-19 | Search | 作为用户，我希望通过文件执行查询，以便定位相关媒体。 | Should |
| US-20 | Search | 作为用户，我希望通过缩略图执行查询，以便从视觉输入找到结果。 | Should |
| US-21 | Tags | 作为媒体所有者，我希望添加手动标签，以便补充模型结果。 | Must |
| US-22 | Tags | 作为媒体所有者，我希望删除手动标签，以便修正错误信息。 | Must |
| US-23 | Tags | 作为媒体所有者，我希望批量维护标签，以便减少重复操作。 | Could |
| US-24 | Authorization | 作为媒体所有者，我希望只有自己能修改或删除媒体，以保护数据完整性。 | Must |
| US-25 | Authorization | 作为共享用户，我希望可以查看媒体但不能执行所有者操作，以符合权限边界。 | Must |
| US-26 | Media Access | 作为客户，我希望原媒体和缩略图受到保护，以免未认证用户直接访问。 | Must |
| US-27 | Delete | 作为媒体所有者，我希望删除自己的媒体，以便管理不再需要的记录。 | Must |
| US-28 | Notification | 作为用户，我希望订阅指定物种，以便出现匹配媒体时收到通知。 | Should |
| US-29 | Notification | 作为用户，我希望取消已有订阅，以便停止不需要的通知。 | Should |
| US-30 | Operations | 作为维护人员，我希望通过日志和请求标识定位跨云处理问题，以便提供售后支持。 | Should |

## Story 管理规则

- 周一 Stand-up 从 Backlog 中选择当周 Stories。
- 每条 Story 必须有负责人、Reviewer、验收标准和依赖。
- 周五 Stand-up 根据测试证据将 Story 更新为 Done、Carry-over 或 Blocked。
- 未完成 Story 不按百分比计为 Done，而是记录剩余工作和下一行动。
- 客户 Demo 反馈先进入 Backlog，再判断属于缺陷、范围内改进或新需求。
