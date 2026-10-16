# 分阶段开发计划

每项完成后先运行验证，再由用户明确授权下一项；提交只含实际完成内容。

| 阶段 | 任务 | 交付物与依赖 | 验证/通过条件 | 建议提交 |
|---|---|---|---|---|
| 0 | 0.1 现状检查与规划 | 本文档集；无依赖 | 文档、Mermaid、编号可审阅 | docs: establish requirements and phased development plan |
| 1 SDD | 1.1 Schema/迁移 | 实体、约束、初始化策略；依赖 0 | 空库建表、外键、隔离测试 | feat(db): define discussion schema and migrations |
| 1 | 1.2 种子数据 | ≥5 套议题/阵容；依赖 1.1 | 可重复初始化、完整性测试 | feat(db): add reproducible sample discussions |
| 1 | 1.3 API 契约/骨架 | OpenAPI DTO、路由；依赖 1.1 | 契约与请求校验测试 | feat(api): define discussion contracts |
| 2 DDD | 2.1 页面骨架 | 中文首页、创建页、演播厅；依赖 1.3 | 组件/视觉验收 | feat(ui): add studio shell and discussion pages |
| 2 | 2.2 Mock 状态流 | 阵容、卡片、Transcript、洞见；依赖 2.1 | 独立滚动和状态转换测试 | feat(ui): model studio states with fixtures |
| 3 TDD | 3.1 先写编排测试 | 调度、限长、结束、隔离；依赖 1.3 | 失败测试表达 FR-04~10 | test: specify discussion orchestration behavior |
| 3 | 3.2 阵容/适配器 | Schema 校验、重试、安全配置；依赖 3.1 | mock LLM 集成测试 | feat(debate): generate validated panel rosters |
| 3 | 3.3 调度/洞见 | 动态行动、证据、持久化；依赖 3.2 | TDD 全绿 | feat(debate): orchestrate dynamic panel discussion |
| 4 E2E | 4.1 REST+SSE 联调 | Hub、断线补发；依赖 2.2/3.3 | SSE 顺序/重连测试 | feat(realtime): stream isolated discussion events |
| 4 | 4.2 完整并发流 | 受控/真实 LLM 流；依赖 4.1 | Playwright 双讨论不串线 | test(e2e): cover panel discussion lifecycle |
| 4 | 4.3 缺陷修复 | 仅测试发现问题；依赖 4.2 | 回归全绿 | fix: resolve verified discussion flow defects |
| 5 | 5.1 交付证据 | README、API、测试、Prompt；依赖 4 | 新环境复现检查 | docs: prepare delivery evidence |

后续指令顺序：先授权 **1.1 Schema/迁移设计**，再按 1.2、1.3 推进；不得跳过阶段。
