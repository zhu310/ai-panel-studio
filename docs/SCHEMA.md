# Schema（阶段 1）
discussions 保存议题、2–6 专家数、生命周期（draft/roster_ready/confirmed/running/completed/stopped/failed）与预设标识；participants 保存角色和画像；messages 保存公开发言并以 (discussion_id, sequence) 唯一排序；discussion_events 保存内部事件并同样排序，最终总结通过 discussion.summary 事件与主持人 Message 持久化；discussion_insights 保存共识/分歧版本；insight_evidence 将洞见关联到真实 message。
所有从属表以外键关联 discussion 并启用 SQLite PRAGMA foreign_keys=ON；删除 discussion 级联删除从属记录。初始化用 Base.metadata.create_all。本阶段未改动既有表结构；新增 confirmed 枚举值存入既有 VARCHAR 状态列，因此现有 SQLite 文件无需重建。未来涉及新增列或约束时应先编写可执行迁移，再部署代码；create_all 不会修改已存在的表。
