# AI Panel Studio

面向知识工作者的 AI 圆桌讨论 Web App。用户给出议题并确认由 AI 生成的主持人与专家阵容后，在演播厅观看一场有角色差异、实时状态和可追溯共识/分歧的讨论。

## 当前状态

项目处于**阶段 1：数据模型、基础 API 与测试**。已实现后端基础 API、SQLite Schema 和预设样例；未实现前端、LLM、讨论调度或 SSE。

## 文档入口

- [产品需求](docs/PRD.md)
- [架构方案](docs/ARCHITECTURE.md)
- [分阶段开发计划](docs/DEVELOPMENT_PLAN.md)
- [验收矩阵](docs/ACCEPTANCE.md)
- [阶段 0 提示词记录](docs/prompts/00-kickoff.md)

运行：`python -m pip install -r requirements.txt`，随后 `python -m backend.app.init_db`、`python -m backend.app.seed`，并以 `python -m uvicorn backend.app.main:app --reload` 启动。OpenAPI 位于 `/docs`。
