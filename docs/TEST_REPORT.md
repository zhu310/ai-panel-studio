# 阶段 4/4.5 测试报告（2026-10-16）

## 当前最终结果

当前提交执行 `python -m pytest -q` 为 **25 passed、2 warnings**。第 25 项是在最终真实模型验收发现连续选择主持人后新增的调度 Prompt 防回归测试。前端最近一次结果仍为 Vitest 4 passed、Playwright 5 passed、生产构建成功；本轮只修改文档，不重复运行前端测试。

## 阶段 4.5 审计时回归快照

| 命令（执行目录） | 实际结果 | 新增验证 |
|---|---|---|
| `python -m pytest -q`（根目录） | 24 passed，2 条 FastAPI `on_event` 弃用警告 | 专家覆盖、最小预算、默认 18 条动态讨论与增量洞见 |
| `npm test -- --run`（`frontend`） | 4 passed | 独立状态卡、公开关注点、真实 SSE 状态映射 |
| `npm run build`（`frontend`） | 成功 | TypeScript 与生产构建 |
| `npm run test:e2e`（`frontend`） | 5 passed（约 1.7 分钟） | 原 4 场景加运行中重入；18 条消息无重复、继续接收 SSE |

第一次扩展 E2E 为 3 passed/2 failed：Fake LLM 在第四位专家发言前请求完成，新加入的覆盖校验按设计拒绝；测试服务改为仍由上下文脚本选人、但最早在全部专家参与后才请求完成。状态卡 Vitest 首次因文案从“发言中”变为“发言中 · 反驳”失败，调整为验证状态与公开动作；随后因卡片和 Transcript 都正确显示“反驳”而出现两个匹配，断言改为明确要求两处。没有降低产品校验或删除失败场景。

真实 DeepSeek 命令：`python -X utf8 -m backend.app.real_smoke --experts 4 --budget 18`。话题为“高校是否应该全面推广生成式 AI 助教？”，阵容成功生成（1 主持人 + 4 专家）；234.5 秒后讨论仍为 `running`，已持久化 **12 条公开消息、2 条洞见、无总结**。脚本随后停止讨论并以非零状态退出。本次运行使用的是旧版诊断分支：部分失败时在打印顺序、分布和 token 统计前返回，临时数据库随后按设计删除，所以这些细项无法从本次运行追溯；不能推测或补造。之后只修复诊断脚本，使今后部分运行也先输出可用数据并支持 `--timeout`，没有重复进行昂贵调用。因此本次真实默认预算验收结论是 **部分成功，未完成全链路**。

## 安全 ZIP 与干净目录复现

`python scripts\package_delivery.py` 从干净的已提交 Git 树生成 `delivery/AI-Panel-Studio-stage4.5.zip`：67 个文件，486856 字节（最终文档提交后重新生成时字节数可能变化）。脚本拒绝 `.env`、SQLite、`node_modules`、`.venv`、缓存、构建物和测试产物，并把本地 `.env` 中长度足够的 key/secret 值与 ZIP 内每个文件逐一比对；未发现命中，也没有输出秘密值。

将该 ZIP 解压到全新的 `delivery/verify-stage45-clean` 后实际执行：`python -m pytest -q` 为 **24 passed、2 warnings**；`npm ci` 从锁文件安装 **259 packages**；`npm test -- --run` 为 **4 passed**；`npm run build` 成功、34 modules transformed。该目录此前不存在且没有复制原工作区的依赖目录，证明源码包可按 README 的依赖步骤复现测试与构建。真实模型调用需使用者自行创建 `.env`，未在干净复现中消费额度；Playwright 已在原工作区完成 5/5 全量回归，没有在解压目录重复下载 Chromium。

## 最终真实模型补验

为消除上述部分成功结论，使用 `--timeout 720` 进行最终验收。首次执行在 1 条开场后因模型连续选择同一主持人而 `failed`；后端防连续独白校验正确，最小修复为在 Prompt 中明确上一发言者 ID、禁止连续选择及开场后必须专家回应。获授权复测结果为：`deepseek-flash`、1 主持+4 专家、18 条公开消息、2 共识+2 分歧、主持总结、`completed`、SSE 回放通过，讨论耗时 366.7 秒。27 次模型请求报告 66438 tokens，模型调用合计 310.0 秒；洞见提取的无效格式重试是主要等待瓶颈。补充防回归用例后最终 pytest 为 **25 passed、2 warnings**。完整公开 Transcript、调度顺序、发言分布、逐项质量评价见 [最终真实模型验收](REAL_MODEL_ACCEPTANCE.md)。

## 阶段 4 自动化测试历史快照

| 命令（执行目录） | 实际结果 | 说明 |
|---|---|---|
| `python -m pytest -q`（根目录） | 21 passed，2 条 FastAPI `on_event` 弃用警告 | 临时 SQLite；含约束、生命周期、SSE 补读、重启遗留状态、模型格式纠正、18/24 预算 |
| `npm test`（`frontend`） | 4 passed | Vitest 仅扫描 `src`；真实模式前端状态与错误反馈 |
| `npm run build`（`frontend`） | 成功，Vite 5.4.14，34 modules transformed | TypeScript 检查和生产构建；Vite CJS API 弃用提示不影响构建 |

阶段 4 增加的 18 条预算测试首次失败：实际 19 条（含总结）；修复 `turn_limit = min(budget - 1, 23)` 后两个边界通过。之后完整 pytest 首次为 3 failed/18 passed，因为旧低预算测试仍把四轮发言加总结当成预算 4；这些测试改用预算 5 保留原有洞见断言，完整回归最终 21 passed。`npm test` 首次因 Vitest 收集 Playwright 文件而失败；限制为 `vitest run src` 后 4 passed。以上失败均保留真实记录，没有删断言。

## Fake LLM 集成与真实浏览器 E2E

命令：在 `frontend` 执行 `npm run test:e2e`；首次需先执行 `.\node_modules\.bin\playwright.cmd install chromium`。结果：**4 passed**，Chromium 129、Playwright 1.47.2。Playwright 自动启动 Vite（4173）和单进程 Fake LLM FastAPI（8765），后端进程使用独立临时 SQLite 并清理；未写开发数据库，也未把 Mock 状态当真实 HTTP 结果。浏览器测试覆盖：

1. 通过页面创建默认四专家讨论，读取后端阵容，核对主持人/专家、职业、背景、立场和颜色；重复确认不产生嘉宾；启动后从 SSE 渐进显示 Transcript、状态、洞见和总结；刷新后恢复。
2. 运行中停止 A，再完成 B；验证停止后的 A 无新增消息、两讨论消息 ID 和事件不串线、刷新后终态正确。
3. 手机视口新消息自动跟随；用户滚回历史后，后续消息不强制拉到底部。
4. 空话题、人数越界、受控模型故障；1440×900、390×844、2560×1440 的面板可见、主要按钮可点击且无页面横向溢出。

截图：[阵容桌面](evidence/roster-desktop.png)、[完成态桌面](evidence/studio-completed-desktop.png)、[确认态桌面](evidence/studio-confirmed-desktop.png)、[手机](evidence/studio-confirmed-phone.png)、[超宽屏](evidence/studio-confirmed-wide.png)。截图中嘉宾与发言来自 Fake LLM 浏览器测试，**不是**真实 DeepSeek 截图。截图检查曾发现完成态显示“实时连接中断”；禁止终态重新订阅 SSE 后重新跑 E2E，截图与断言均无此提示。

## 真实 DeepSeek 与人工检查

命令：根目录执行 `python -m backend.app.real_smoke --experts 4 --budget 6`，独立临时 SQLite，实际环境模型名为 `deepseek-flash`。第一次：生成 1 主持+4 专家成功；讨论在 2 条发言后因连续两次结构化输出不合格转 `failed`，无洞见或总结。放宽模型草稿文本解析上限、保留最终发言压缩和 160 字校验后，复测：`completed`，5 位参与者、**6 条公开消息（含主持总结）**、**4 条洞见**，共识/分歧均存在，SSE 回放通过。脚本报告了数量和类型；没有保存真实文本样本，因此不能声称已人工审阅每条真实发言的语义质量。没有把失败自动换成 Fake LLM。

已人工查看上述真实 Chromium 截图：桌面三栏完整，手机上下重排可用，标题与状态不重叠，超宽屏中央文字区域受限；Transcript、专家与洞见区域的滚动/无横向溢出主要由浏览器断言验证。阶段 2 的人工截图初检由用户此前反馈，本报告不把它写成本阶段重新执行的手测。

## 当前未验证与已知限制

- 已完成一次 18 条**真实 DeepSeek** 默认讨论并人工审阅语义；24 条最大预算仍只由 Fake LLM/pytest 覆盖，不主张真实模型每次均有相同质量与耗时。
- 浏览器 E2E 的 SSE 断线后恢复主要由服务端 `Last-Event-ID` 接口测试和前端事件去重逻辑验证，未在浏览器中主动制造网络断线。
- 单 Worker 限制、启动时遗留 `running → failed` 是设计约束。FastAPI `on_event` 与 Vite CJS 的弃用提示属于 P2 维护项。
