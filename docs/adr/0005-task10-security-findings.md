# ADR 0005：Task 10 安全回归发现与待确认修复

状态：**Proposed，未获确认，未实施生产修复**。日期：2026-10-07。

基线：`0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07`。本次只增加测试和评测材料；本 ADR 不改变 ADR 0001–0004、OpenAPI 或授权规则。

## 已复现的问题

|问题|证据|风险与拟议修复|
|---|---|---|
|撤销学生课程关系后仍可读取自己原有提交、执行、诊断并调用提示和解释|`tests/security/test_idor.py` 的 revoked enrollment 五个参数：预期统一 404，实际 200；提示/解释仍调用 Mock Provider|`CourseSubmissionAccess.require_read` 只检查用户与 owner，没有检查当前 enrollment。拟在真实授权入口重新检查课程关系，并覆盖提示、解释、分享等衍生入口。属于权限变更，须确认。|
|登出后旧 JWT 仍有效|后端 logout replay 回归和 `frontend/e2e/security.spec.ts` 的旧 token 重放：预期 401，实际 200|main 没有 `/auth/logout` 契约或服务端撤销状态。须先确认登出契约及 session/token 撤销设计、持久化与失效范围，再实施；只清浏览器存储不能满足此要求。|
|原始代码进入诊断模型请求|`test_raw_source_must_not_enter_final_model_request` 捕获最终 DTO 包含私有代码 sentinel|现有设计允许 DiagnosisRequest.source_files，本任务明确禁止原始代码进入模型，二者冲突。拟改为经允许的最小诊断证据及脱敏结构；脱敏方法、语义损失和契约变化须先确认。保留严格断言。|
|删除后的迟到 upsert 恢复物理索引副本|`test_cross_course_memory.py` 迟到 upsert：逻辑搜索为空，但索引再次存在原文|拟用删除 tombstone/版本栅栏约束所有写入，并验证持久化索引、重启和并发。现有读侧权限和状态复核不能证明物理擦除。|
|删除记忆后原文从来源诊断再次进入模型上下文|`test_deleted_memory_original_text_cannot_reenter_model_context` 删除后请求 hint 仍包含原文|记忆原文来自 retained diagnosis.root_cause。须确认删除语义是否覆盖来源诊断和衍生模型上下文，设计来源依赖清理/脱敏；不得仅删除索引以宣称完成。|

## 尚不能验证的边界

删除 receipt 的 `cache_cleared` / `model_references_cleared` 不等于独立物理验证。main 尚无独立缓存、外部模型引用删除适配器；本次仅验证可检查的数据库、内存索引、最终模型 DTO 与恢复流程。专用 PostgreSQL 集成验证不等于 pgvector 向量索引擦除验证。不存在的适配器不能通过 mock receipt 视作通过。

Task 8 Router/SQL 聚合和 Task 9 UI 尚未合入本分支。相应安全验收必须在 Wave 3 Gate 执行；测试契约和浏览器用例收集不是运行时安全结论。

## 建议决策与验收

请分别确认上述权限、登出、模型输入和删除血缘方案，再分任务实现。每项沿用当前失败测试，补充实际持久化适配器/并发/重启回归，禁止 skip、xfail 或降低断言。确认前本 Task 10 不修改业务服务、组合根、迁移、OpenAPI、Compose 或环境示例。

本 ADR 是风险与修复提案，不表示已获架构批准，也不表示 Wave 3 Gate 已通过。
