# 阶段 4 测试报告（2026-10-16）

## 自动化单元与接口测试

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

## 未验证与已知限制

- 未做完整 18–24 条**真实 DeepSeek** 长讨论；预算上限由 Fake LLM/pytest 覆盖。真实模型的语义关联、反驳质量只完成低预算自动闭环，未逐句人工评分。
- 浏览器 E2E 的 SSE 断线后恢复主要由服务端 `Last-Event-ID` 接口测试和前端事件去重逻辑验证，未在浏览器中主动制造网络断线。
- 单 Worker 限制、启动时遗留 `running → failed` 是设计约束。FastAPI `on_event` 与 Vite CJS 的弃用提示属于 P2 维护项。
