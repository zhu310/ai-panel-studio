# API（阶段 3）

启动后访问 `/docs` 查看实际 OpenAPI 契约。所有接口以 `/api/v1/discussions` 为根；参数错误返回 422、资源不存在返回 404、状态冲突返回 409、模型服务失败返回 502。错误正文使用 FastAPI 的 `detail` 字段。

| 方法与路径 | 已实现行为 |
| --- | --- |
| `GET /health` | 返回 `{"status":"ok"}` |
| `POST /api/v1/discussions` | 创建草稿，JSON：`{"topic":"高校 AI 助教","expert_count":4}`；专家数 2–6，默认 4 |
| `GET /api/v1/discussions` | 按创建时间倒序列出讨论 |
| `GET /api/v1/discussions/{id}` | 返回讨论、参与者及可选的自然语言 `summary` |
| `POST /api/v1/discussions/{id}/roster` | 真实模型生成并保存阵容；草稿可调用，已生成阵容重复调用幂等 |
| `GET /api/v1/discussions/{id}/participants` | 查询嘉宾阵容 |
| `POST /api/v1/discussions/{id}/confirm` | 确认完整阵容，状态变为 `confirmed` |
| `POST /api/v1/discussions/{id}/start` | 异步启动；JSON：`{"message_budget":18}`，允许 4–24，预算包含最后一条主持总结，最多 24 条公开消息且可提前结束 |
| `POST /api/v1/discussions/{id}/stop` | 停止运行并保留已存数据，重复停止安全 |
| `GET /api/v1/discussions/{id}/transcript` | 按场内序号查询公开发言，附带由持久化事件恢复的 `action` |
| `GET /api/v1/discussions/{id}/insights` | 查询共识/分歧与证据发言 ID |
| `GET /api/v1/discussions/{id}/events?after=N` | SSE 事件流，亦支持 `Last-Event-ID`；按场内序号补读 |

SSE 事件名包括 `discussion.status`、`participant.status`、`participant.hand_raised`、`message.created`、`insights.updated`、`discussion.summary`、`discussion.error`。每条事件的 `id` 是该讨论的递增事件序号；`data` 含 `discussion_id`、`sequence`、`type` 和 `payload`。内部事件不会写入 Transcript。刷新时先查询讨论详情、发言与洞见，再订阅事件；客户端用消息 ID 去重。

`draft → roster_ready → confirmed → running → completed` 是正常流程；运行可转为 `stopped` 或 `failed`。进程重启时遗留 `running` 会标为 `failed` 并保留已有记录。当前单进程部署，不支持多个 Uvicorn worker 共同调度。

阶段 4 验收补充：`POST .../confirm` 对已确认阵容幂等；重复 `start` 返回 409，重复 `stop` 对已停止状态返回成功。终态 SSE 可回放已持久化事件后结束，客户端在读取到终态时不再订阅；`Last-Event-ID` 或 `after` 可请求断线补读。浏览器 E2E 使用本地 Fake LLM 测试服务，不改变这些正式接口契约。
