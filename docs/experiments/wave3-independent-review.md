# Wave 3 独立只读审查与主 Agent 裁定

审查基线：0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07。
固定审查HEAD：9e1a7b7692857d15bf789eb72d157ba7f28d66c4。
审查者：全新上下文 /root/wave3_readonly_review；没有继承实现对话，没有写文件、改Git状态或服务、派发其他审查者、运行宿主不可信代码或使用真实学生/模型。补核了审查期间新增的失败证据及映射更正。

## 审查优势及证据核对

- 五来源保留-x；CORS/JWT撤销/记忆删除/教师Router组合行为保留。
- SQL最小字段、课程作用域HMAC、不同学生/过滤后/group五人阈值，复核队列不透传私人正文。
- 复核与审计共享UOW/Session/提交边界，实际PG验证并发、回滚与锁等待后撤权。
- 固定快照103命令（65退出0、38退出非0）归档SHA全部相符；三数据规范LF与原Git blobs相等；后端907节点零失败/错误/跳过，浏览器16+10零skip/unexpected/flaky。
- 原严格安全断言保留，Runner首次失败及严格重跑成功均保留，未谎称根因已修复。

## Critical

未发现。这个结论不抵消下列Important，Gate仍未通过。

## Important

### I1 / WG-TEACHER-READ-AUDIT — 教师敏感读取未审计、故障不失败关闭

位置（固定HEAD）：backend/app/analytics/service.py:109、:64；backend/app/api/teacher.py:93。

review_queue/course_analytics两个GET均不调用audit，也不接request_id。教师队列返回逐条诊断/提交标识、时间/置信度；即使audit.record必定抛异常，读取仍成功。设计§8.7要求敏感读取审计，ADR0004§13要求无法可靠审计时失败关闭。

审查复现：queue items=1、audit events=0；主 Agent 新增tests/security/test_wave3_teacher_read_audit.py，队列/available/suppressed三类的成功审计与故障拒绝共6项全部失败，teacher-read-audit-red.xml保留。全部合成领域事实，没有SQL/外部物理证明的冒称。

主 Agent 裁定：**接受，未修复，触发用户第16节/已确认计划的停止条件。**停止产品实现，保留RED，等待明确授权。拟修复只加现有metadata-only审计与已有503语义；不记录subject_key、正文、过滤明细，不改权限、阈值、公开DTO或migration。

### I2 / WG-STUDENT-RUN-CANCEL — 切换任务后永久busy

位置：frontend/src/student/ExercisePage.tsx:42、:134。

clearLearningResult取消旧resultRequest，但不清running；旧finally因aborted也不清，新课程/练习提交按钮仍禁用。两种切换组件回归实际失败，最新npm test为36passed/2failed（38）。第一次新增测试fixture错误调用/submissions，不能证明该问题；修正为既有/exercises/{id}/submissions后的第二次RED才是有效交互复现，两次记录均保留。

主 Agent 裁定：**接受，未修复。**I1触发停止时尚未修改UI实现。授权后失效旧请求并复位当前运行状态，同时验证旧请求不能覆盖新状态以及随后重新提交。

### I3 / WG-CASE-CROSS-COURSE-006 — 错场景被计为原攻击通过

位置：backend/tests/security/test_wave3_case_execution.py:69；security_support.py:146；data/evaluation/map_security_execution.py（固定HEAD）:100。

计划为student-a持有course-b pending proposal后撤销B关系；实际节点撤销student-b/course-a，访问已accepted的course-a proposal。case_id与复制的operation字符串不能证明前置状态/课程正确。该问题是证据缺口，未据此宣称运行时授权漏洞。

主 Agent 裁定：**接受；撤回过高通过声明，正确场景仍未执行。**未改攻击节点或产品实现，只更正报告生成：保留原错误观察，改为not_executed并注明具体阻塞号。新增生成器负向测试先1failed/10passed，最小证据修正后11passed；真实重建为162automated_passed/2not_executed。原163/1只是审查前快照，不能作为当前结论。

## Minor

### M1 — 多概念趋势重复计数

位置：frontend/src/teacher/CourseDashboard.tsx:31。同一diagnosis的多个concept group相加会重复，诊断/修复“总数”可能误导教师。

主 Agent 裁定：接受，未修复。授权后使用准确的概念关联次数标注，保留既有公开契约，不从前端猜唯一诊断数或新增API字段。

### M2 — 加载新队列时旧items可操作

位置：frontend/src/teacher/ReviewQueue.tsx:18、:49。旧GET响应有abort保护，但旧已加载items在切课/刷新期间仍显示且可提交。

主 Agent 裁定：接受，未修复。授权后加载时清除/隐藏旧队列并禁用提交，验证课程切换和迟到结果不会影响当前队列。

## Declined to judge — 完整清单及主 Agent 逐项裁定

|审查者暂不判定的行为与理由|主 Agent裁定及依赖|
|---|---|
|客户端X-Request-ID格式/允许回显或替换：契约未定义信任规则；只能确认回显|接受暂不判定；保留WG-CORRELATION-POLICY和sec-sensitive-logging-008 not_executed，待明确API/安全决策，不虚构攻击通过或越权结论|
|外部pgvector/cache/model-reference物理擦除：无真实适配器|接受暂不判定；WG-EXTERNAL-ERASURE须ADR/授权适配器及真实删除/迟到writer/cache验证，不能以内存证据冒称通过|
|首次Runner4 compile_failed根因/并发稳定性：缺当时Docker events及完整诊断|接受暂不判定；保留失败与严格重跑记录，负载/可观测性待验证，不能宣称根因修复|
|真实教学效果/真实模型比较：仅synthetic+Mock，无gold|接受范围外；真实数据/模型使用均0，教师gold/试点/比赛指标需要Wave4明确授权|
|生产部署/回滚已安全完成：仅合成PG往返|接受范围外；未部署。迁移擦除/降级丢撤销/备份/全实例密钥轮换前提已验证/说明，不能冒称生产执行成功|

没有其他Declined项，没有默默丢弃的范围。

## 最终审查结论与后续授权范围

**Gate未通过，当前不能条件通过。**0Critical、3Important、2Minor；I1/I2产品未修复，I3正确场景未执行。最新证据：6安全RED，组件36pass/2fail，攻击映射162pass/2未执行（非教学成效）。不能用此前907/36/26绿色覆盖审查发现。

具体待授权步骤：

1. 从已保留RED修复I1，在正式Router传入request_id、返回前可靠持久化最小审计；审计失败统一脱敏503且不返回诊断内容；补真实PG/HTTP持久化与故障回归。无需新migration/生产依赖/角色权限变化。
2. 修复I2及M1/M2，各先补失败测试再最小修改原UI，不重新设计。
3. 正确构造course-b/student-a/pending提议撤权场景，验证统一拒绝、无泄漏/激活，再生成实际证据；未验证前保持not_executed。
4. 完整后端、真实PG/迁移、组件/构建/类型、两份浏览器及隔离Runner回归；由同一次独立审查上下文补核修复，重新判Gate。保留全部失败历史与上述5项限制。

此授权不包含merge、rebase、push、PR、worktree删除、生产部署、真实学生/模型或新增外部适配器。
