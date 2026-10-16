# AI Panel Studio

一个可本地运行的中文 AI 圆桌讨论 MVP。输入议题并确认主持人和专家阵容后，DeepSeek 驱动非固定轮询的讨论；页面通过 SSE 展示发言、专家状态、共识/分歧与主持人总结。另有与真实模式明确分离的 Mock 演示。

## 环境与结构

- Python 3.11+、Node.js 18+、npm；真实模式需要可用的 DeepSeek/OpenAI-Compatible API Key。以下为 Windows PowerShell 命令，其他终端可用等价命令。
- 后端：FastAPI、SQLAlchemy、SQLite、httpx；前端：React、TypeScript、Vite；测试：pytest、Vitest、Playwright/Chromium。
- `backend/app/`：API、数据模型、讨论编排、模型适配、初始化和样例脚本。
- `frontend/src/`：真实模式和独立 Mock 演示；`frontend/e2e/`：真实浏览器测试。
- `tests/`：后端单元与集成测试；`docs/`：需求、架构、API、Schema、验收、测试报告及开发过程记录。

## 安装与运行

在项目根目录执行：

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑根目录 `.env`：`DATABASE_URL=sqlite:///./data/ai_panel_studio.db` 可沿用；填入只在后端使用的 `OPENAI_API_KEY`，并按服务商设置 `OPENAI_BASE_URL` 和 `OPENAI_MODEL`。不要把真实密钥提交到 Git，也不要放进 `frontend`。当前开发环境实际使用过 DeepSeek 的 `deepseek-flash`，新环境应以服务端实际响应确认模型可用。

```powershell
python -m backend.app.init_db
python -m backend.app.seed
```

`seed` 可重复运行，导入五套明确标记为“预设样例”的讨论及主持人/四专家阵容：高校 AI 助教、自动驾驶与公交、中小企业 AI 客服、核电与碳中和、儿童短视频监管。预设阵容不是实时模型结果。现有表的初始化使用 `create_all`；它不会迁移已有表结构，字段变更须另写迁移脚本，详见 [Schema](docs/SCHEMA.md)。

然后分别打开两个终端，均从项目根目录开始：

```powershell
# 终端 1：单 Worker 后端
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# 终端 2：前端；Vite 将 /api 和 /health 代理到 8000 端口
Set-Location frontend
npm ci
npm run dev -- --host 127.0.0.1
```

打开 Vite 显示的本地地址（通常 `http://127.0.0.1:5173`）。后端健康检查为 `http://127.0.0.1:8000/health`，交互式 OpenAPI 为 `http://127.0.0.1:8000/docs`。

首页是真实模式：创建讨论会持久化草稿并调用后端生成嘉宾，确认后点击“开始真实讨论”。若模型调用失败会显示错误，不会自动切换为演示数据。首页“体验 Mock 演示”进入 `#demo`，脚本化发言只在浏览器演示，不写入真实讨论。回到真实模式可去掉 URL 的 `#demo` 并刷新。

## 已实现 API 与测试

核心 API：`POST/GET /api/v1/discussions`、`GET /api/v1/discussions/{id}`、`POST .../{id}/roster|confirm|start|stop`、`GET .../{id}/participants|transcript|insights|events`。请求/响应及 SSE 事件详见 [API](docs/API.md)。默认四专家；公开发言预算默认 18、协议范围 4–24，且不得少于“专家数 + 2”（为主持开场、每位专家至少一次参与和总结保留空间），包含最终总结，可提前结束或手动停止。

```powershell
# 根目录：独立临时 SQLite，Fake LLM，不调用真实模型
python -m pytest -q

# 前端目录
Set-Location frontend
npm test
npm run build
.\node_modules\.bin\playwright.cmd install chromium  # 首次运行
npm run test:e2e
```

Playwright 自动启动 Vite 和注入 Fake LLM 的测试后端，使用独立临时数据库并在退出时清理；不会污染开发数据库，也不会消费真实模型额度。浏览器截图保存在 `docs/evidence/`。可选的真实模型验收：从根目录运行 `python -m backend.app.real_smoke --experts 4 --budget 18 --timeout 600`；它会实际调用模型、消耗额度，但使用独立临时库，不输出密钥，并报告发言顺序、洞见证据及可获得的 token 用量。实际执行证据与本次长讨论的超时边界见 [测试报告](docs/TEST_REPORT.md)。

## 限制

这是单机、单 Uvicorn Worker MVP；讨论任务锁在当前进程内，**不要使用多个 worker**。进程重启时遗留 `running` 会标为 `failed`，历史数据保留，不自动续跑。SQLite `create_all` 不是迁移工具。模型可能拒绝或返回不合格式内容，后端最多纠正一次；模型服务质量和上下文语义不能由 Fake LLM 测试完全保证。没有账号权限、生产级队列或多 Worker 调度。GitHub 推送和邮件提交由项目所有者确认后执行。
