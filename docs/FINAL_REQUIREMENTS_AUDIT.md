# 原始作业要求完整性审计（阶段 4.5）

审计日期：2026-10-16。结论标记：**满足（代码+自动化）**表示实现与自动测试均有证据；**真实模型已验证**表示 DeepSeek 实际调用有结果；**部分满足**表示主链路存在但本轮目标未完整闭环；**待人工验证**表示不能由现有自动化等价证明。Fake LLM、浏览器 Fake 服务和真实模型证据严格分开。

## 需求追踪矩阵

| ID | 原始要求 | 对应代码位置 | 对应测试 | 验证证据 | 结论 |
|---|---|---|---|---|---|
| A-01 | 首页显示讨论列表 | `frontend/src/RealApp.tsx:42,174`；`backend/app/api.py` | `frontend/e2e/discussion.spec.ts:14` | 真实 HTTP 列表及空/错状态 UI | 满足（代码+自动化） |
| A-02 | 创建新讨论 | `RealApp.tsx:72`；`api.py` 创建路由 | E2E 首场景、`tests/test_api.py` | 默认四专家与合法范围均验证 | 满足（代码+自动化） |
| A-03 | 查看并加入已有讨论 | `RealApp.tsx:56-66` | E2E 首场景刷新及重入场景 | 详情、阵容、消息、洞见并行恢复 | 满足（代码+自动化） |
| A-04 | 加入运行中讨论并继续实时观看 | `RealApp.tsx:56-66,120-163` | `discussion.spec.ts:61` | 运行中回大厅后重入，先看到旧消息，随后收到至 18 条 | 满足（真实浏览器 Fake 后端） |
| A-05 | 展示正确状态 | `RealApp.tsx:22`；`models.py:7` | Vitest 及 E2E | draft 至 failed 中文映射 | 满足（代码+自动化） |
| A-06 | 不同讨论隔离 | 所有从属表 `discussion_id`；API 按 ID 查询 | `test_two_running_discussions_complete_independently`；停止隔离 E2E | 消息、事件、洞见、任务均未串线 | 满足（代码+自动化） |
| B-01 | 任意非空话题 | `schemas.py` 创建输入约束 | API/E2E 空值及普通中文话题 | 非空清理后持久化并传给模型 | 满足（代码+自动化） |
| B-02 | 默认 4，支持 2–6 | `schemas.py`；创建表单 | API、Vitest、E2E | 默认 4，越界 422/中文反馈 | 满足（代码+自动化） |
| B-03 | AI 生成主持人与指定专家 | `discussion_service.py:36` | `test_roster_generation...`、E2E | DeepSeek 本轮实际生成 1+4 阵容成功 | 真实模型已验证 |
| B-04 | 人物字段完整 | `models.py:29`、`llm.py` roster schema | API/E2E 卡片字段断言 | 姓名、Title、背景、立场、颜色均持久化 | 满足（代码+自动化） |
| B-05 | 专家观点有差异 | roster Prompt/验证；`seed.py:8` | seed/API 测试 | 预设四专家立场互异；实时阵容结构校验 | 满足（结构自动化；语义由模型） |
| B-06 | 确认后才能启动 | `api.py` confirm/start 状态校验 | 讨论 API 集成测试 | 未确认 409，确认后 202 | 满足（代码+自动化） |
| B-07 | 重复请求不产生重复阵容 | `generate_roster` 幂等分支 | API 与 E2E 重复确认 | 人数和 ID 不增加 | 满足（代码+自动化） |
| B-08 | 新真实讨论不误用 Mock | `RealApp.tsx` 与 `DemoApp` 路由隔离 | E2E 使用真实 API 层 | 模型失败直接报错，不降级 Mock | 满足（代码+自动化） |
| C-01 | 主持人开场 | 调度 Prompt 与首轮校验 | 默认预算 Fake 集成、E2E | 第一条为主持人 | 满足（代码+自动化） |
| C-02 | 主持人追问、串联并适时介入 | `discussion_service.py:125-131` | `test_default_budget...` | Fake 顺序含主持人中途重新介入 | 满足（受控自动化）；真实长场未取回顺序 |
| C-03 | 专家主动举手 | `llm.py:Turn.hand_raised`；service `:231` | 单元、E2E 状态断言 | action 校验后独立持久事件 | 满足（代码+自动化） |
| C-04 | 抢答或插话 | `Turn.action=interrupt` 与举手约束 | 默认预算 Fake 集成 | interrupt 必须伴随 hand_raised | 满足（代码+自动化） |
| C-05 | 补充观点 | `action=add`；Prompt 要求关联上文 | Fake 集成 | 公开动作和文本共同入库 | 满足（代码+自动化） |
| C-06 | 明确反驳 | `action=rebut`；前端中文动作 | Vitest、E2E | 卡片与 Transcript 显示反驳 | 满足（代码+自动化） |
| C-07 | 根据 Transcript 动态选人 | `transcript_context:66-75`、`choose_turn` | 默认预算 Fake 测试 | 每轮将近期发言、次数、未覆盖专家交给模型 | 满足（代码路径+自动化） |
| C-08 | 非固定轮询 | 模型返回 `speaker_id`，仅做合法性/覆盖校验 | `test_default_budget...` | 顺序非 round-robin，可连续交锋 | 满足（代码+自动化） |
| C-09 | 每次公开发言 1–2 句 | `validate_turn:78`、`compact_public_text` | 单元/集成 | 句数及 160 字硬限制 | 满足（代码+自动化） |
| C-10 | 长度/终止正确 | `run_discussion:202`；`validate_turn:101-108` | 18/24、覆盖、过早 finish 测试 | 总结计预算；全部专家发言前禁止结束 | 满足（Fake 自动化）；真实 18 条未完成 |
| C-11 | 主持自然语言总结 | `make_summary` 与主持 Message | 集成/E2E | 总结持久化并单独展示 | 满足（自动化）；阶段 4 真实短场已验证 |
| C-12 | action 生成、校验、执行、事件、显示闭环 | `llm.py`、`discussion_service.py:78-108,231-270`、`RealApp.tsx:145-198` | pytest/Vitest/E2E | 举手→准备→发言有可观察间隔，内部状态不进入 Transcript | 满足（代码+自动化） |
| D-01 | 每位专家独立小窗 | `RealApp.tsx:193-199`；`real.css:10-22` | E2E `.participant-card` 数量 5 | 非普通列表，主持/专家独立卡片 | 满足（真实浏览器） |
| D-02 | 待机/准备/发言中 | 同上及 SSE 状态映射 | E2E 依次捕获 hand/preparing/speaking | 状态视觉与事件一致 | 满足（真实浏览器 Fake 后端） |
| D-03 | 当前关注点/公开摘要 | `RealApp.tsx:197` | Vitest/E2E | 事件 focus 优先，未发言时公开立场兜底并明确标为公开关注点 | 满足（代码+自动化） |
| D-04 | 不展示隐藏思维链 | Prompt 明示 focus 非思维链；UI 只用公开字段 | 代码检查/E2E | 无 reasoning 字段进入 API/UI | 满足（代码审计） |
| E-01 | 讨论中更新共识/分歧 | `run_discussion:270` | 默认预算 Fake 与 E2E | 结束前至少四次 `insights.updated` | 满足（代码+自动化） |
| E-02 | 非结束时一次性生成 | 同上 | 默认预算 Fake | 第 6、9、12、15...轮增量更新 | 满足（代码+自动化） |
| E-03 | 未形成时无预设结论 | DB 初始为空；UI 空态 | E2E 启动前 insights `[]` | 真实模式不加载 Mock 结论 | 满足（代码+自动化） |
| E-04 | 洞见引用真实发言 | `save_insights:142-180` | evidence 与跨讨论拒绝测试 | 无合法证据不保存 | 满足（代码+自动化） |
| E-05 | 合并和修订 | `save_insights:156-180` | bounded/version 测试 | 同类洞见更新版本并替换证据 | 满足（代码+自动化） |
| E-06 | 证据跨讨论隔离 | 同上 discussion_id 校验 | `test_insight_rejects_cross_discussion_evidence` | 外场证据被拒绝 | 满足（代码+自动化） |
| E-07 | 清晰区分共识与分歧 | `RealApp.tsx:206-209` | E2E/截图 | 两个独立区域和空态 | 满足（真实浏览器） |
| E-08 | 真实讨论洞见语义准确 | DeepSeek + evidence schema | 最终真实 18 条运行 | 2 共识、2 分歧均可追溯到洞见出现前的公开发言 | 满足（真实模型+人工语义审阅） |
| F-01 | 发言显示姓名/Title/颜色/内容 | Transcript 组件及 Message schema | E2E | 公开消息卡字段齐全 | 满足（代码+自动化） |
| F-02 | 内部事件不显示成发言 | events/messages 分表 | pytest/E2E | hand/status 仅状态卡，消息数无污染 | 满足（代码+自动化） |
| F-03 | 顺序展示 | `(discussion_id, sequence)` 唯一约束 | pytest/E2E | 序号连续 | 满足（代码+自动化） |
| F-04 | 持续查看新增 | EventSource + cursor | 重入 E2E | 运行中继续接收 | 满足（真实浏览器 Fake 后端） |
| F-05 | 看历史时不强制到底 | `RealApp.tsx:139,166` | `discussion.spec.ts:117-120` | 滚回顶部后 scrollTop 保持 | 满足（真实浏览器） |
| F-06 | 完成后自然语言总结 | summary 事件、详情字段、SummaryPanel | E2E；阶段 4 DeepSeek 短场 | 不显示 JSON | 满足（自动化+真实短场） |
| F-07 | 刷新恢复记录 | load detail/transcript/insights | E2E reload | 数据来自 SQLite | 满足（真实浏览器） |
| G-01 | SQLite | `database.py`、配置 | pytest | 测试和运行均 SQLite | 满足 |
| G-02 | 前后端分离 | `backend/`、`frontend/` | 构建/E2E | Vite 代理 FastAPI | 满足 |
| G-03 | Key 只由后端读取 | `config.py`、`llm.py:52`、`.gitignore` | secret 扫描/构建 | 前端无 key，报告不输出 key | 满足（代码审计） |
| G-04 | 多讨论状态/上下文/事件隔离 | 数据外键、manager 按 discussion_id | 并发 pytest/E2E | A/B 不串线 | 满足（代码+自动化） |
| G-05 | SSE 实时通信 | `api.py` events；前端 EventSource | SSE pytest/E2E | sequence/after/Last-Event-ID 可补读 | 满足（代码+自动化） |
| G-06 | 中文 UI | `RealApp.tsx`/CSS | E2E/截图 | 主流程中文 | 满足（真实浏览器） |
| G-07 | 响应式布局 | `real.css` media query | 390/1440/2560 E2E | 无页面横向溢出 | 满足（真实浏览器） |
| G-08 | 三面板独立滚动 | `real.css` layout/overflow | E2E/截图 | 专家、Transcript、洞见各自滚动 | 满足（真实浏览器） |
| G-09 | 可复现初始化 | `init_db.py`、`seed.py:47` | seed 两次测试 | 幂等五套样例 | 满足（代码+自动化） |
| G-10 | 五套高质量预设阵容 | `seed.py:8-45` | `test_seed_idempotent` | 每套 1+4，实名化人物、领域背景和实质差异立场 | 满足（定向修复后） |
| G-11 | 测试及 API 文档 | `tests/`、`frontend/e2e/`、`docs/API.md` | 全量命令 | OpenAPI 与人工文档均存在 | 满足 |
| G-12 | 本地完整运行 | `README.md`、Vite proxy | E2E 自动启动双端 | 单 worker 本地闭环 | 满足（自动化） |
| H-01 | 完整源代码 | `backend/`、`frontend/` | Git/ZIP 清单 | 源码均纳入版本控制 | 满足 |
| H-02 | 初始化脚本 | `backend/app/init_db.py`、`seed.py` | pytest | 空库可建表和导入 | 满足 |
| H-03 | 五套样例 | `seed.py` | pytest | 数量、幂等、画像差异 | 满足 |
| H-04 | PRD/架构 | `docs/PRD.md`、`ARCHITECTURE.md` | 文档审计 | 架构已按实际持久事件轮询修正 | 满足 |
| H-05 | ER 图 | `docs/ARCHITECTURE.md` Mermaid ER | 文档审计 | 与 models 对齐 | 满足 |
| H-06 | 核心流程图 | `docs/ARCHITECTURE.md` Mermaid flow | 文档审计 | roster→confirm→run→SSE | 满足 |
| H-07 | API 文档 | `docs/API.md` | OpenAPI/文档审计 | 已实现与约束准确 | 满足 |
| H-08 | 测试代码/报告 | `tests/`、`frontend/e2e/`、`TEST_REPORT.md` | 全量回归 | 失败与修复亦如实记录 | 满足 |
| H-09 | README 配置/运行准确 | `README.md` | clean ZIP 复现 | 含初始化、双端、测试、真实验收 | 满足 |
| H-10 | 至少五段真实核心 Prompt | `docs/prompts/00-05` | 文件审计 | 六段；01/02 已补回可核实完整原文 | 满足 |
| H-11 | 覆盖 SDD/DDD/TDD/E2E | `01-sdd` 至 `04-e2e` | 文件审计 | 阶段映射明确 | 满足 |
| H-12 | Prompt 有意图/反馈/问题/修复 | 各 prompt 后半部分 | 文件审计 | 只记录真实发生内容 | 满足 |
| H-13 | 工作流 1–1.5 页 | `docs/WORKFLOW.md` | 人工文档审计 | 六个紧凑段落，未扩成流水账 | 满足 |
| H-14 | 如实说明 Codex/DeepSeek | `WORKFLOW.md` 首段 | 文档审计 | 未声称使用 Claude Code | 满足 |
| H-15 | 渐进 Git 历史 | `git log` | Git 审计 | 阶段 0–4 及本轮按性质提交 | 满足 |
| H-16 | ZIP 无密钥/数据库/缓存 | `scripts/package_delivery.py` | ZIP 内容、禁入路径、本地 secret 值比对 | 67 文件；无禁入项或本地秘密命中 | 满足（自动检查） |
| H-17 | 干净解压/克隆可复现 | README、锁文件、requirements | clean ZIP pytest/npm ci/test/build | 24 pytest、4 Vitest、build 均通过 | 满足（干净解压验证） |

## 缺口分级与处理

- P0：审计完成后无已知 P0。密钥未写入源码、日志、截图或 ZIP。
- P1（已修复）：过早完成可能漏专家；状态事件不可观察；预设阵容模板化；专家区不像独立小窗；架构文档与代码不一致；01/02 Prompt 原文不完整。
- P1（已闭环）：最终真实 DeepSeek 四专家、18 条复测在 366.7 秒完成，四位专家均参与，形成 18 条消息、4 条有证据洞见和主持总结；完整内容与性能分析见 `REAL_MODEL_ACCEPTANCE.md`。
- P2：FastAPI `on_event` 和 Vite CJS 弃用提示；单 worker 约束；浏览器重载已验证 SSE 重建，但未用代理或浏览器离线开关模拟物理断网。

## 修复摘要

1. 完成条件加入专家覆盖及剩余槽位约束；启动预算至少为专家数加二，仍由模型动态选人，不改成固定轮询。
2. 举手、准备、发言分别提交持久事件并给 UI 可观察间隔；interrupt 必须伴随 hand raise。
3. 五套种子阵容改为领域匹配的具体人物、背景和差异化立场，更新仍按预设议题幂等。
4. 保留三栏，成员区改为主持/专家独立状态卡，显示公开关注点、角色、动作和状态，不显示思维链。
5. 架构文档删除不存在的内存 Event Hub/Repository/`occurred_at` 描述，生命周期和 SSE 字段改为实际实现。
6. 补齐能从对话记录核实的阶段 1/2 原始指令；无法核实的内容没有扩写。

## 真实模型验收边界

阶段 4.5 的首次默认预算调用在旧等待上限后停止；最终验收先发现并修复了模型连续选择主持人的明确 Prompt 阻断，再进行一次获授权复测。复测使用 `deepseek-flash`，在 366.7 秒完成 18 条消息、4 条洞见及总结，四专家均参与，SSE 回放通过。27 次请求共报告 66438 tokens；洞见格式失败重试是主要等待瓶颈。详见 `REAL_MODEL_ACCEPTANCE.md`。

## 浏览器证据与边界

Playwright 5/5 覆盖：完整创建/阵容/状态/SSE/洞见/总结/刷新；运行中重入并从历史继续到 18 条且无重复；停止与 A/B 隔离；用户阅读历史不被强滚；三类视口及错误态。页面重载会真正关闭并重建 EventSource，服务端 `after`/`Last-Event-ID` 另有接口测试；没有模拟操作系统级断网。截图位于 `docs/evidence/`，内容来自 Fake LLM E2E，不能作为 DeepSeek 内容证据。

## 交付复现

从新生成 ZIP 解压到此前不存在的 `delivery/verify-stage45-clean`，实际完成 `python -m pytest -q`（24 passed）、`npm ci`（259 packages）、`npm test -- --run`（4 passed）和 `npm run build`（成功）。打包脚本同时检查禁入路径，并用本地 `.env` 中的 key/secret 值逐文件比对且不打印秘密；无命中。详见 `docs/TEST_REPORT.md`。
