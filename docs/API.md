# API（阶段 1）
已实现：健康检查；创建讨论（topic、expert_count=4，范围 2–6）；讨论列表/详情；按讨论查询 participants、transcript、insights。错误：422 参数错误，404 资源不存在。OpenAPI：运行服务后访问 /docs。尚未实现：阵容 AI 生成、启动/停止、SSE、调度与 LLM。
示例：POST /api/v1/discussions，body 为 {"topic":"高校 AI 助教","expert_count":4}。
