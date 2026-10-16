# AI Panel Studio

面向知识工作者的 AI 圆桌讨论 Web App。用户给出议题并确认由 AI 生成的主持人与专家阵容后，在演播厅观看一场有角色差异、实时状态和可追溯共识/分歧的讨论。

## 当前状态

项目处于**阶段 3：真实 AI 圆桌讨论引擎**。已具备中文讨论大厅、真实嘉宾生成与确认、后端动态讨论、SSE、持久化 Transcript/洞见/总结，以及独立的阶段 2 Mock 演示入口。

## 文档入口

- [产品需求](docs/PRD.md)
- [架构方案](docs/ARCHITECTURE.md)
- [分阶段开发计划](docs/DEVELOPMENT_PLAN.md)
- [验收矩阵](docs/ACCEPTANCE.md)
- [阶段 0 提示词记录](docs/prompts/00-kickoff.md)

后端运行：先 `python -m pip install -r requirements.txt`，按 [.env.example](.env.example) 配置根目录 `.env`，运行 `python -m backend.app.init_db`，可选 `python -m backend.app.seed`，再用 `python -m uvicorn backend.app.main:app --reload` 启动。OpenAPI 位于 `/docs`。API Key 仅由后端读取。

前端运行：进入 `frontend`，执行 `npm install` 与 `npm run dev`。Vite 将 `/api` 代理到本地 FastAPI 端口 8000。首页创建讨论后调用真实模型生成阵容，确认后可启动讨论；“体验 Mock 演示”仍是独立入口。

验证：仓库根目录执行 `python -m pytest -q`；前端目录执行 `npm run build`。少量真实模型烟雾测试可在根目录执行 `python -m backend.app.real_smoke`，该脚本使用临时 SQLite 库与四轮公开发言预算，不写入运行数据库。
