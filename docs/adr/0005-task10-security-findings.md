# ADR 0005：Task 10 安全回归发现与修复决策

状态：**Accepted for implementation**。用户在阅读提案后于2026-10-07指示“开始修复”；此授权覆盖五类修复，沿用严格回归，不包含 Task 8/9 集成或新增外部服务。

框架基线：`0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07`；框架提交：`783bd84fddbeb9e0210a40e8e50170a67c5679e9`。下表保留当时的失败证据；用户授权后的实施决策见后文，修复会修改授权入口、OpenAPI、迁移及组合根。

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

框架阶段先请求确认，保持业务服务、组合根、迁移和OpenAPI不变。用户现已授权实施上述方案。每项沿用原失败测试，补充实际持久化适配器/并发/重启回归，禁止 skip、xfail 或降低断言。

## 本次实施决策

1. 使用现有课程授权事实检查学生当前 membership，沿用统一404；教师正式提交规则保持。
2. 新增受保护 POST /auth/logout（204），仅撤销当前 bearer；JWT带随机jti，不影响其他登录。新增0006迁移保存令牌SHA-256与到期秒数，生产组合根使用SQL撤销仓库，多实例/重启仍有效；内存仓库仅用于开发与测试。存储失败关闭并返回脱敏503，不保存令牌原文。
3. 模型源码 DTO 只保留路径，拒绝content；诊断消息与规则证据在外发请求中使用无源码的固定说明，原始证据在本地绑定/校验；hint/explanation 使用已审核课程知识，不传个人诊断root_cause。可能降低个性化诊断信息，不能据此宣称教学准确率不变。
4. 索引upsert在权威memory_claim内复核当前版本、原文一致性、到期与删除状态；delete保留写入栅栏。重建索引必须绑定权威仓库，不能仅依靠内存删除历史。
5. 删除事务清空相关提议正文，来源context清理覆盖诊断root_cause、提示/理解验证衍生文本及内存运行结果缓存；持久化适配器与删除事务共享UOW。保留课程、概念、权限和证据关联元数据，不移除学生原始提交或教师课程资料。没有独立外部缓存/向量/模型引用服务，相关外部物理擦除仍为Gate缺口。

删除栅栏补充：SQL使用现有tombstone与来源诊断关联；内存来源保留可随失败事务回滚的删除集合。迟到理解验证、提示和运行缓存写入必须脱敏；创建提议在锁内重新获取来源，接受/纠正待确认提议也核验来源仍合格。SQL来源写入按诊断父行→子记录锁序，父锁为FOR NO KEY UPDATE，既串行化删除与来源写入，也允许其他记忆版本的外键KEY SHARE检查。旧的失败执行缓存没有diagnosis字段，不能阻断擦除。

JWT编码补充：三段base64url必须是无填充的规范编码，避免相同签名字节的不同字符串绕过digest撤销。迁移0006也单向擦除历史deleted/deletion_pending记忆关联的来源文本；降级不能恢复。若降级丢弃撤销表，重新启用认证前必须轮换AUTH_TOKEN_SECRET，使已撤销旧令牌继续失效。

共享变更包括OpenAPI、0006迁移、SQL模型/仓库与组合根；不改Compose或环境配置，不增加依赖。每项先观察失败再最小实现，补实际PostgreSQL多实例、重启和迁移往返测试。本决策不表示Wave 3 Gate已通过。
