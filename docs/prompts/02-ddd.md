# 阶段 2 DDD 提示词记录
用户授权 React、TypeScript、Vite 的讨论大厅、阵容确认和演播厅，真实 API 与明确标识的 Mock 演示分离；禁止 LLM、调度、SSE、前端伪造后端结果。
实际完成：首页真实读取/创建讨论，Vite 代理；真实样例参与者读取；新讨论的演示阵容和可停止、可重置的脚本化 Mock 演播厅。Mock 仅在浏览器状态中运行，不写入 API。
实际问题：首次构建缺少 React 类型声明，已安装官方 @types 包；随后修正 useRef 初值和 useEffect 返回 Promise 的 TypeScript 错误。Node 18 对最新 Vite 依赖发出 engine 警告，构建验证结果记录于最终汇报。
