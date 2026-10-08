# Wave 3 Integration Gate — 最终交接（条件通过）

## 1. Gate 结论

**条件通过。**用户在安全停止报告后明确回复“继续”，授权并完成三项Important、两项Minor修复与完整回归；同一次独立只读审查的补核结果见第15节。最终后端928、组件41、浏览器16+10、隔离Runner31+12+4全部通过，无测试跳过。原220安全、54真实SQL向量、7浏览器Gate均实际执行。

不能宣布完全通过：sec-sensitive-logging-008缺明确请求编号信任规则，仍未执行严格判定；外部向量/缓存/模型引用物理擦除未实现适配器；历史Runner并发编译失败根因及负载稳定性未证实。上述限制不是实际教学成效。

## 2. 完成与未完成

已语义集成五个来源提交；真实SQL教师分析、共享事务复核/审计、正式Router与40个operations、学生/教师UI、持久化logout、迁移往返及真实PG/Runner/浏览器组合均验证。授权后教师两个敏感GET返回前提交metadata-only审计，审计写入或commit失败关闭为503；拒绝读取亦记录最小元数据。学生切课/换练习取消运行后恢复提交；队列加载清除旧条目并隔离迟到提交结果；趋势明确显示概念关联次数。正确course-b/student-a/pending撤权攻击已执行，映射恢复163通过/1未执行。

未完成范围：WG-CORRELATION-POLICY、WG-EXTERNAL-ERASURE、Runner历史失败根因/负载验证；正式教师gold、真实模型比较、教学试点及生产部署均未执行。没有增加角色、教师私人读取权限、生产依赖、外部基础设施、schema或公开DTO。

## 3. 五个来源提交及追溯

|来源|原始完整提交|Gate -x 提交|
|---|---|---|
|Task8|988cc2c49265667a7ddeba8d50a92269467c0407|d46ea9f55588838d0e2eaab2db2ebb6a3361830d|
|Task9 UI|ce9fe25486ee2c900af8a837429421d14f7fc010|3562098289a3fdbdf42b3c595d2475910582f8ff|
|Task9 CORS|b53b4b4d3f5d18dfab2505a07fde9bb96c10bf4d|2e458417bc0af5922e418ceb4fdb2864e20d7bf1|
|Task10 框架|783bd84fddbeb9e0210a40e8e50170a67c5679e9|5ed6c7503a401f3eeb7f0a3ba50aea7972c6303c|
|Task10 修复|e39f0df42e5fb17fc60e84f92db8051fb0d3a726|4fd2e835d2fd8000e9e555076cbca99b1dc9b16a|

五个 Gate 提交正文均保留 cherry picked from commit。main、cached origin/main、开始时 live remote 一致：0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07。

## 4. 共享文件与语义合并

backend/app/main.py 同时保留 CORS 白名单、SQL token 撤销、Task7 memory source_context/删除栅栏、Task8 三个 Router、同UOW及统一错误/request ID；实际未产生该文件文本冲突，装配缺口随后按契约补齐。frontend/playwright.config.ts 的 add/add 冲突保留 learning UI、security HTTP 的独立 testMatch/baseURL/服务；Vite 自动合并的重复 include 收敛为单测试聚合入口，保留全部组件、排除 Playwright。package/lockfile 不升级依赖。

共享影响：.env.example/基础 Compose 加入既定本地 CORS 配置；新增 Gate override 仅隔离测试资源/loopback端口，sandbox仍无网。迁移 env.py 设置 disable_existing_loggers=False，防止同进程迁移关闭模型网关既有日志；没有 schema/数据/权限变化。OpenAPI 仅集成来源新增接口，之后不修改冻结语义。冲突处理未使用整文件 ours/theirs。

## 5. Task8 SQL 与事务

匿名分析只选取 submissions/diagnoses/concepts/exercises/理解与成功重试所需事实，HMAC subject_key 带目的、课程和 owner 作用域，不出现在公开响应/日志/审计。人数按不同学生，所有过滤和每个group重新执行5人阈值；start包含、end不包含。私人对话、完整记忆、源码不作为分析数据源。独立修复要求明确关联的成功重试、理解达标，且之前没有4级提示。

复核队列由现有事件/诊断/提交关系与已审核课程证据生成去标识候选，教师权限实时从 SQL 读取。review_claim 按既有锁序锁 diagnosis FOR NO KEY UPDATE，等待后重新核对课程/权限/候选。复核和 metadata-only audit 在原 SqlMemoryUnitOfWork 同Session唯一commit；相同决定和trim理由重放，不同409，任一写入失败全部回滚。实际 PG 验证并发、撤权、审计失败、记忆完全不变（7项），数据投影13项。

## 6. ADR 编号

Task9 CORS 保留 docs/adr/0005-local-preview-cors-allowlist.md；Task10 安全 ADR 改为 docs/adr/0006-task10-security-findings.md，相关引用同步。ADR编号与数据库revision独立；没有新增权限或关键架构决策。

## 7. OpenAPI/API

三个正式教师 API 与 POST /auth/logout 同时挂载，保留 Task2–7 全部接口。运行时实际 routes/models 与共享 OpenAPI 精确比较40个operations的路径/方法/operationId/参数/body/状态/security/响应；连 bearerAuth scheme 比较，共42项通过。运行时生成器不读取冻结YAML。前端只依赖公开 DTO，无数据库字段耦合。公开 Runner DTO 与内部协议 DTO 分离，保留原公开5种状态及字段约束。

## 8. 迁移与部署/回滚要求

唯一head：0007_teacher_analytics_reviews，down_revision=0006_token_revocations；新增最小 teacher_diagnosis_reviews，diagnosis唯一、course/reviewer FK、复合课程FK、decision/reason checks。真实PG10项验证从空schema upgrade/current/check、空schema full downgrade/base重升、带业务行仅降0006/0005、约束及历史删除文本清理。

部署前备份，停旧写入实例，迁移后全实例统一切换。历史 deleted/deletion_pending 的来源/衍生文本擦除不可逆；downgrade不恢复正文。降0006丢权威复核，须备份其结果和审计；降0005丢JWT撤销记录，**恢复认证前必须轮换所有实例 AUTH_TOKEN_SECRET**。测试实际证明未轮换时旧token重新有效，并验证轮换后拒绝。课程/提交/live诊断/非目标行保留。本交接不授权生产部署。

## 9. 54组真实匿名分析向量

54/54通过正式 create_app→SQL DataSource→实际PG，另8项去掉过滤条件的反例通过。9种过滤组合、4/5人、重复学生、跨课程、group抑制、半开日期均有原参数node/JUnit证据；excluded_by只作元数据，全事实入库。跨课程练习映射为course_id--exercise_id以满足既有全局PK/复合FK，不删反例或降低数据库约束。该54与原220安全测试中的schema向量验证分开计数。

## 10. 原220项安全回归

最终backend-after-review.xml有928项、0失败/错误/跳过，其中原220/220通过：IDOR65、small_sample_contract62、prompt_injection41、security_repairs15、recompute13、cross_course_memory9、evaluation_datasets9、isolated_runner6。最后6项使用真实隔离容器。新增案例、审计和容器攻击测试另计；原Task10断言未放宽、未删除/skip/xfail。原Task8 68项保留，审计永久故障测试现在同时要求读取失败关闭及健康reader仍见pending，原复核回滚断言保留。

## 11. 原7项浏览器Gate

原 security-ui.gate.ts 7/7实际执行通过，另3项真实组合通过。默认命令原learning-loop2+security HTTP14=16通过，两份Playwright配置共26，0skip、0失败、0flaky。原7及learning-loop为投影网络fixture，HTTP14为合成内存fixture，不能称为PG证明。新增3场景不使用page.route，连接实际UI/API/SQL/Runner。

## 12. 学生/教师真实组合

最终两份浏览器命令26/26通过，重试配置0。新增3场景不使用page.route，连接实际UI/API/SQL/隔离Runner：教师真实登录、4/5人阈值、私人/跨课404、过滤422、复核409、双击仅1敏感请求、SQL队列移除、logout旧JWT401；学生真实编译失败/成功修复、诊断/提示/理解（Mock Provider）、本人接受/纠正/拒绝/删除及退出。测试专用SQL写入故障返回脱敏503/request ID，旧会话保留，普通退出重试成功；没有生产故障入口或CORS放宽。

最新浏览器后只读SQL核对：review=1、review audit=1、deleted且正文擦除版本=2、含正文私人版本=0、拒绝proposal=1、完成deletion=1、revoked logins=3。手机390×844与桌面1440×1000无document横向溢出，截图仅合成内容。原7UI/learning2投影fixture和security HTTP14内存fixture分别标注，不冒称PG证明。

审查后的取消运行两项及队列/趋势三项交互RED，最小修复后组件41/41；旧请求结果不能覆盖新课程，旧复核错误不能污染新队列。

## 13. 164条攻击执行映射及数据哈希

security_execution_manifest.json恰好164唯一原ID：**163 automated_passed、1 not_executed**。原case hash、operation、计划tier、真实tier、确切JUnit node/case_id属性、实际命令/UTC时间/退出码/report hash均保留。原修复快照的manifest仍引用有效局部报告。审查指出10:04命令只校验而未重建；主Agent实际执行带--build的G10-post-review-manifest-rebuilt并11项严格复验后，最终通过案例才引用本次完整928报告的实际节点：104本地参数、65 PG参数（3具体+54原向量+8反例）、3容器攻击；并非164独立无重叠测试。严格映射工具11项通过，拒绝缺失/重复ID、伪hash、未执行/错操作、错场景。

sec-cross-course-006原student-b/course-a/accepted错误声明曾撤回为未执行，保留停止checkpoint。授权后实际构造student-a/course-b/pending，先验证提议可读取及不存在已激活记忆，再撤销B关系；列表/接受均404，无私密正文泄漏、模型调用或记忆激活，提议仍pending。JUnit前置状态由实际仓库断言导出，映射器强制核对，不仅靠复制operation。新增场景语义RED1→GREEN及105参数回归保留。

sec-sensitive-logging-008仍未判定：调用方X-Request-ID回显的观察不等于成功拒绝；计划没有定义合法格式/替换规则。阻塞WG-CORRELATION-POLICY。五个原architecture_pending案例只有现有本地实现证据，内存index/cache/model引用不证明外部物理删除；WG-EXTERNAL-ERASURE独立保留。

数据文件未改内容；Windows core.autocrlf导致worktree CRLF与原Git blob LF字节hash不同，规范LF逐字节相等，详见verification-summary.json。原LF hash：security a5a33c34cc95887988972dd094d4743d14bd8c5e31df501f71c2d21fff36e34e；analytics ccb7d5c512137d6f4eb2cbc74cef9684847d953a0f72c7142c9d74c805eb032d；diagnosis 96ace03aab66ca806e5e56152d1fe939cf8701c6d3b31c6422e95c84d49d4410。实际raw hash另外记录，不混用。4条教学样例仍draft，verified=0，未生成真实教学结果。

## 14. 全部命令、环境与结果

wave3-command-results.json保存实际完整argv/cwd/UTC起止/退出码/环境变量名称/raw SHA及脱敏归档SHA。command-output保存实际UTF8/LF日志；历史失败/RED保留，不伪造重试。verification-summary.json从真实JUnit/Playwright JSON计算计数与hash；局部.gitattributes固定证据LF。第一次未提权场景测试Python卡在环境启动、未产生pytest结果，精确取消该helper/子进程后另次实际RED，未把取消计为断言失败。

|最终命令|实际结果|phase/报告|
|---|---|---|
|backend Python -B -m pytest tests -q -p no:cacheprovider --tb=short -o junit_family=xunit1|928 passed，0 failed/skipped；原220及真实PG全包含|G10-post-review-backend；backend-after-review.xml|
|npm test|41 passed，0 failed|G10-repair-UI-confirmed|
|npm run build；显式全部tests/E2E/config tsc|退出0；退出0|G10-post-review-frontend-build/types|
|npx playwright test --reporter=list,json|16 passed，0 skipped/unexpected/flaky|G10-post-review-browser-default；browser-default-after-review.json|
|npx playwright test --config playwright.gate.config.ts --reporter=list,json|10 passed，原7+真实3；0 skipped/unexpected/flaky|G10-post-review-browser-gate；browser-gate-after-review.json|
|hardened worker/container pytest|31 passed|G10-post-review-runner-worker|
|hardened controller/container pytest|12 passed|G10-post-review-runner-controller|
|host HTTP→controller→sandbox fixed scenarios|4 passed|G10-post-review-topology；controller-topology-after-review.xml|
|Compose config --quiet；结构与运行时合同|退出0；结构及42合同测试已包含928|G10-post-review-compose；backend-after-review.xml|
|evaluate.py；mapper --build/strict tests|退出0；163/1；11 passed|G10-post-review-evaluation/manifest-rebuilt/manifest-rebuilt-check|
|browser read-only SQL probe|退出0，上述7项准确count|G10-post-review-browser-SQL-proof|

真实服务：独立Docker项目knowbound-wave3-gate；PG loopback55430、controller8199，浏览器API8198/UI5199按命令启动和结束。六个wave3_task6/task7/task10/router/migration/browser库均合成。完整pytest显式TASK6/7/10_POSTGRES_URL、TASK6/7_RUNNER_ENDPOINT、TASK10_RUNNER_IMAGE并清除DATABASE_URL，隔离迁移与业务库。SQLite仅原结构单测，Mock仅模型响应，未替换SQL授权/JWT/事务/删除边界。

实际版本PG17.11/pgvector0.8.7、cjc/cjpm1.2.0、Python3.14、Node24/npm11.12.1、Docker29.8。全部不可信仓颉源码仅非root/无网/只读/cap-dropALL/no-new-privileges/PID64/CPU1/512m/tmpfs64m容器执行，宿主只发送结构化请求。镜像digest与离线测试依赖构建详见G8；无生产新依赖。

重要历史失败仍保留：首次backend899pass/4fail为Alembic关闭logger，实际PG RED→最小修复→907通过→本次928通过；首次并发HTTP4全部compile_failed，源码/严格2秒限制不变重跑4通过，本次亦4通过。但当时Docker events未留存，根因及并发负载稳定性未证明，不宣称已修好。审查停止时6安全RED/组件36pass2fail/映射162/2均为历史事实，不能与本次最终结果混淆。

## 15. 独立审查发现和修复

全新只读上下文曾审查BASE→9e1a7b7692857d15bf789eb72d157ba7f28d66c4，0Critical/3Important/2Minor，按用户停止条件保存281b93966d4dd3fec22950ac3d46013709cc44e4，未偷偷修复。用户明确继续后修复并完整回归，由同一审查上下文补核固定repair HEAD f1c684f82e2d6815c5d2ab167cad9cb2cb2e5272；实际补核记录、逐项主 Agent 裁定及五项Declined完整清单见wave3-independent-review.md。

I1敏感GET读取审计：新增6领域+11实际PG/HTTP先17RED，修复后136相关GREEN及928全回归；success/denied元数据、独立SQL连接可见commit、flush/commit故障503与rollback/健康重试均证明。浏览器发现不存在课程误503，补2项PG RED→只对现有课程持久化拒绝审计→33相关GREEN；保留同一404与外键约束，不建虚构课程或新增迁移。
I2切换永久busy：两项有效组件RED→清running且旧请求失效→41全绿。
I3错误攻击声明：先撤回，再实际course-b pending/撤权语义RED→修正唯一场景fixture→105全绿；mapper前置语义防伪11全绿。
M1概念重复趋势：accurate关联次数标签及说明，保留冻结DTO；M2加载旧队列及迟到POST：清items/禁操作/代际隔离；三项先RED，再41全绿。

原审查者确认I1/I2/I3/M1/M2全部关闭，无未解决或新增Critical/Important；准确repair提交和只读补核范围写入独立报告。请求编号政策、外部擦除、Runner负载根因、真实教学/模型、生产部署五项继续明确暂不判定。审查者未写代码或改变Git/服务，未新增另一审查Agent。

## 16. 真实数据/模型

真实学生数据：0；真实/付费模型调用：0。身份、课程、源码、攻击、样本、截图均合成。Mock Provider只代替模型响应，不替代SQL授权、JWT撤销、复核事务或删除边界。上述软件测试结果不是实际教学试点成效。

## 17. 全部修改文件

完整BASE→Gate已跟踪差异及新增文件逐行列于wave3-changed-files.txt；包含三来源整合、Gate实现/测试、迁移/配置、ADR、命令、JUnit/JSON及截图，不能只列最后commit。独立审查报告和最终文档已补入，完整清单已刷新。

## 18. 风险与Wave4/Task11依赖

三项Important、两项Minor已授权修复并回归，正确course-b攻击已执行。剩余条件：WG-CORRELATION-POLICY需明确公共correlation格式/信任规则后补严格判定；WG-EXTERNAL-ERASURE需先ADR及授权真实外部适配器，再验证物理删除、迟到writer、缓存失效；Runner首次并发失败的根因、可观测性、负载验证仍待完成。重复串行通过不能证明并发稳定性。

pgvector扩展可用不代表适配器。本次没有外部新设施/依赖。教师gold、真实模型/学生、试点及比赛成效必须Wave4另获明确授权，当前不能把软件或模拟数据测试称为真实教学效果。迁移擦除/降级备份/统一密钥轮换条件见第8节。

## 19. Gate分支、提交与工作区

分支codex/wave3-integration-gate；worktree C:\Users\lenovo\Desktop\cs competition\.worktrees\wave3-integration-gate；BASE0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07。G9为8f2cf61ec7e4931e4e06de42749e933ea5c63237；原固定审查HEAD9e1a7b7692857d15bf789eb72d157ba7f28d66c4；停止checkpoint281b93966d4dd3fec22950ac3d46013709cc44e4。修复固定HEAD f1c684f82e2d6815c5d2ab167cad9cb2cb2e5272，原审查者补核已完成并写于独立报告。

最终本地提交信息feat: integrate Wave 3 analytics UI and security gate。最终准确HEAD/干净状态由提交后的交付消息与Git history提供，文档不伪造自己的提交hash；完整差异文件见wave3-changed-files.txt，main/来源HEAD及清洁核对见最终仓库证据。

## 20. 未执行动作

未merge到main，未rebase、push、创建PR或删除任何worktree；main及Task8/9/10均只读且保持原HEAD/干净状态。仅保留本地Gate提交和独立测试容器，未改日常8000服务。最终交付前再次核对这些状态。

---

# Wave 3 Integration Gate — rolling execution record

User approved the implementation plan on 2026-10-08. Work is confined to `codex/wave3-integration-gate` and its dedicated worktree.

Base: `0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07` (local main, cached origin/main, and live remote agree).

Source order: `988cc2c`, `ce9fe254`, `b53b4b4`, `783bd84`, `e39f0df`.

Status: historical phase record; current verdict and final counts are in the numbered handoff above. Daily services and source worktrees remain separate.

## G0 evidence

- Gate initializer RED: missing `tests.integration.wave3_environment`, pytest exit 1; observed before implementation.
- Main plan was copied with SHA-256 equality and its untracked original removed; no main product edit.
- Backend baseline: 79 passed. Earlier invocation had 66 passed / 13 setup errors due to inaccessible system pytest temp directory; fresh Gate basetemp resolves all 13.
- Frontend baseline: 1 passed; lockfile npm ci completed without dependency changes.
- Six synthetic databases initialized; PostgreSQL 17.11 and vector 0.8.7 verified.
- Resolved Compose isolation check passed. Actual loopback reachability initially failed (10 passed, 1 failed); Docker internal network had requested bindings but no effective host mappings.
- Ruling: attach trusted Gate PostgreSQL/controller to the already-declared public network as well as internal, with loopback-only bindings. This only changes the local test override; sandbox remains networkless and has no socket/source mount. Cost if wrong: host test resources could be unreachable; no product topology change.

## Decisions

- Ruling: execute the skill's task bookkeeping natively in PowerShell/Python rather than Bash helpers. The approved plan uses G0–G10 headings, whereas the helpers parse numbered `Task` headings. Preserve the same ledger, briefs, commit ranges and observed verification evidence. Cost if wrong: bookkeeping interoperability only.
- Ruling: preserve execution evidence in tracked handoff files rather than deleting it at completion. The user expressly requires reviewable evidence. Temporary scratch may be cleaned without deleting any worktree.

## G1 integration

- Task 8 source integrated with `-x`: analytics and frozen contract 73 passed (68 analytics + 5 contract).
- Task 9 UI source integrated with `-x`: 30 components passed, production build passed, original 2 browser projection scenarios passed.
- Task 9 CORS fix integrated with `-x`: 9 CORS/config tests passed.
- Task 10 framework: add/add conflict in `frontend/playwright.config.ts`. Semantic merge retains learning UI project/Edge/Vite service and security HTTP request project/Python fixture. Each has independent testMatch/baseURL; both services reject reuse.
- Automatic merge introduced duplicate `include` in `frontend/vite.config.ts`; retained Task 9 single aggregation entry, which excludes Playwright while preserving all 30 tests. `package.json` and lock preserve both test:e2e and unchanged Playwright/Node types versions.

- Framework security: exactly 196 passed / 9 historical failures / 0 skipped; all nine match the source handoff. Applied authorized repair source with -x; no main.py conflict. CORS middleware, SQL token revocations and deletion source_context all remain.
- ADR numbering: CORS retains 0005; accepted Task 10 security decision renamed 0006 and all deliverable safety references updated. Original case/vector data unchanged.
- G1 final source safety regression: 220 passed, 0 failed, 0 skipped; actual sandbox checks included. Shared authentication/CORS/config regression: 28 passed. Components: 30 passed; build passed. Initial TS2688 installation lag resolved by lockfile npm ci; configuration typecheck then passed.

## G2 SQL data source

- First actual PG test reached existing `SqlCourseRepository.add` ordering defect: authorized-teacher insert before course caused FK violation. Dedicated reproduction observed RED before fix.
- Ruling: flush the course parent within the existing transaction before inserting authorized teachers. No permissions/schema/API change; necessary to seed and persist valid course relationships. Cost if wrong: extra database round trip, transaction still atomic.
- G2 final: 83 passed (13 actual PostgreSQL projection tests + original 68 analytics + 2 development projection tests), no skips. Covered multiple concepts/checks, duplicate students, actual private memory sentinel, mismatched/null queue relations, half-open dates, cross-course HMAC keys and explicit successful retry evidence. Review SQL persistence remains G3; application mounting remains G4.

## G3 reviews and minimal migration
- Missing review_claim observed RED. Added teacher_diagnosis_reviews only, migration0007 after0006. Shared SqlMemoryUnitOfWork locks diagnosis FOR NO KEY UPDATE, revalidates current candidate/teacher permissions, then inserts review and metadata-only audit with one commit.
- 89 projection/domain/review tests passed; additional single-commit/factory-UOW proof passed in the final 7-review-test run. Same/different simultaneous requests use independent SQL adapters and yield one review/one success audit. Flush failures roll back both; actual memory rows/version/status unchanged; post-wait permission revocation uniformly404.
- Legacy PG first run: 23 passed/2 environment failures (Task6 empty DB has no migration fixture). Migrated only wave3_task6, then all25 passed/no skips. Single head 0007 verified. Full migration roundtrip remains G7.

### G4 — 正式应用及全部运行时契约
正式 create_app 挂载三个教师 Router。DATABASE_URL 装配 SqlTeacherAnalyticsRepository 与原 memory audit 同一 UOW；开发模式投影现有动态仓库。Task 7 来源清理、Task 10 SQL 撤销和 Task 9 CORS 保留。
全部 40 operations 精确比较 paths/methods/operationId/parameters/body/status/security/response；240 项相关回归执行通过，0 skip。比较器保留名为 title/description 的业务字段，仅忽略 schema 注释；nullable enum 合并 null 是表达等价转换，未放宽 enum。
新增 api/contract.py 只从实际 routes/models 生成 OpenAPI，移除无法失败的无请求体/无约束 string 路径自动 422；不读取共享 YAML。知识接口用实际有效 Annotated + SkipValidation 保留原业务校验和错误码，随后各 handler 仍调用严格模型；SourceMetadata 未提供 note 时省略，显式 null 拒绝。公开 DTO 独立于内部 Runner DTO，保留公开字段约束。
HTTP 探针确认删除墓碑仍返回既有已脱敏诊断，满足非空公开约束且无原文；初始新增测试要求 404 属于错误假设，已撤回该额外权限行为。两组重置 wave3_router 的测试误并发引发测试数据 FK/唯一冲突，已改串行，全部重跑通过。共享 OpenAPI 本身未修改。

### G5 — 原始匿名向量真实执行
原 54 组向量通过正式 create_app / SQL / PostgreSQL，附加 8 组逐个移除过滤条件的反例检查，共 62 passed / 0 failed / 0 skipped。JUnit 含唯一 vector node、真实请求 URL、响应、总入库事实数及 excluded_by 反例数；原 YAML 与哈希未变。
测试映射说明：源向量用课程内 exercise-a 名称，数据库已存在全局 Exercise PK + course 复合 FK。course-a 保留公开 ID；其他课程的练习使用 course_id--exercise_id，保持全部 diagnosis/owner/course/concept/time/repair 事实与反例入库，不绕过或降低 SQL 约束。跨课程排除另由 G2 真实 SQL 课程隔离测试佐证。多概念逐一构造独立已审核证据后一起装载；不依据 excluded_by 预过滤。

### G6 — 前端连接与退出
保留原 UI，增加真实 POST /auth/logout；busy ref 阻止重复请求。204/已失效401才清本地会话，503保留令牌与请求编号，允许重试。结束日期使用下一本地日零时；相邻窗口为 [start-duration,start)，无一毫秒空隙；取消旧课程队列响应后不覆盖新课程。
原30+新增5项 Vitest 全部通过，构建通过，显式 src/组件测试/E2E/两份配置 TypeScript 检查通过。发现两处旧测试把 Array.some 第二参数（index）误当 init，修正为解构调用元组，严格原断言保留。首次 UI Gate 拒绝文案不一致属 Minor 展示整合缺口，课程列表拒绝用通用文案，已有课程拒绝保留课程文案；无权限/隐私边界变化。

### G7 — 独立迁移往返
专用 wave3_migration 库中的逐测试可丢弃 synthetic schema，从空 schema 验证0001→0007单head、current、check、full downgrade base→重升；有合成业务行的 schema 仅降0006/0005。10 passed / 0 failed / 0 skip。实际token长度/唯一、review唯一/decision/reason/跨课程复合FK约束拒绝。
两种历史状态 deleted/deletion_pending 的 proposal、diagnosis、evidence、hint、explanation 原文均清理；live诊断/提交和非目标课程保留，擦除内容不随降级恢复。0007降到0006丢复核而保留token撤销；0006降到0005丢撤销记录，测试先证明原密钥会重新接受旧token，再验证轮换密钥拒绝旧token。
部署/回滚要求：部署前备份，停止旧写入实例，迁移后全部实例统一切换。擦除不可逆，downgrade不能恢复正文。降级删除token_revocations后必须在恢复认证前轮换AUTH_TOKEN_SECRET；复核结果丢失须单独备份恢复审计与权威结果。这里只验证合成环境，不授权生产部署。
# G8 actual browser and isolated Runner

The default Playwright command executed all original 2 learning projection and 14 security HTTP scenarios (16 passed). The Gate command executed all original 7 UI projection scenarios and 3 new official-application/SQL/real-controller scenarios (10 passed). Projection scenarios use network fixtures; they are not evidence of PostgreSQL or real Runner execution. New scenarios do not intercept UI network requests. Diagnosis/hint/explanation providers remain deterministic Mock; all actors, sources and facts are synthetic.

The real scenarios cover teacher four/five-student thresholds, private/foreign-resource 404, invalid-filter 422, conflicting-review 409, double-click suppression, SQL queue refresh, student actual compilation failure and successful repair, hints, explanation validation, owner acceptance/correction/rejection/deletion, logout and captured-token 401. A test-module-only SQL write failure produces sanitized 503 with request ID; the fault is sent through Playwright's API context (production CORS does not allow the test header), followed by ordinary browser logout. Components separately verify the visible 503/retry state. No production fault endpoint was added.

Post-browser read-only SQL proof: 1 authoritative review, 1 review audit, 2 erased/deleted memory versions, 0 remaining non-null private versions, 1 rejected proposal, 1 completed deletion and 3 revoked login digests. Desktop 1440×1000 and mobile 390×844 screenshots are synthetic; mobile document width checks pass. The older projection fixture needed a logout 204 response, and initial browser locator errors were corrected without weakening security assertions.

Original Runner suites executed in hardened Linux test containers: worker/executor/parser/CLI/protocol 31 passed; controller/docker-engine 12 passed. Test images bake existing local pure Python pytest dependencies (including its py compatibility module); no production dependency, network installation, host source mount or worker Docker socket. Real HTTP controller→sandbox success/compile-failure/infinite-loop/output-cap scenarios: 4 passed, with no newly retained sandbox containers. Both cjc and cjpm versions are read directly from the actual SDK image. Every untrusted source runs only in the isolated worker.

Sandbox parent image: sha256:082f87930e2752fddab9a5633ca232847ff164944cf96e0b7bbec8df45edbbee; controller parent: sha256:4a8bd167ca8c42b819f7bd4625ba4cdc436546a28d03d7931c6a630c9fd2a03b. Offline test-image manifest digests after adding py: worker e39acee3c8519f3787096b43c6bea88d9a3bdb7f0406a23ca2eba54344c91eaf; controller caae15f6c04060590d06d78e5fa1774316cd0d42cd9ace6495e20fc372ddff07. Build commands use infra/compose/wave3-runner-tests.Dockerfile with explicit BASE_IMAGE and --network none. These are testing artifacts, not production deployment.

## G9 per-case execution

The original 164 planned cases and draft annotations remain unchanged (normalized LF bytes equal original Git blobs). `security_execution_manifest.json` joins each original case hash to an exact executed JUnit node, actual command/timing/exit code, report digest, mapping rationale and adapter boundary. The mapper validates 164 unique IDs and rejects missing/duplicate IDs, unknown statuses, missing evidence, altered hashes or a node merely collected rather than executed (7 G9 validation tests; 10 after G10 strict case/operation/command checks).

Actual case evidence: 104 local parameters passed; 3 concrete PostgreSQL cases plus all original 54 SQL vector parameters and 8 filter-omission checks passed (65); 3 real container attacks passed. Network connection to a documentation-reserved address is denied; PID telemetry reaches exactly 64 and remains within the cap until deadline termination; stdout flood is capped at 65536 and deadline bounded. Initial PID expectation of an exception message was replaced with stronger actual kernel-backed telemetry, because the SDK can block creating runtime threads at the cap. No original Task 10 assertion was relaxed.

The G9 manifest reported **163 automated_passed, 1 not_executed**. Independent review withdrew the wrong-scenario claim, yielding **162 automated_passed, 2 not_executed at the security-stop checkpoint**. After the user authorized repairs, the correct course-b pending proposal scenario actually passed and the final manifest returned to **163 automated_passed, 1 not_executed**; see the current numbered handoff. Both historical snapshots remain archived. `sec-sensitive-logging-008` has an actual observation: client X-Request-ID is reflected as correlation metadata. Its planned expected denial does not specify whether valid caller-provided correlation is permitted or must be replaced, so an echo observation is not called a successful sanitization attack test. Blocker **WG-CORRELATION-POLICY** requires an explicit API/security decision and a corresponding strict denial criterion. This is a documented unverified requirement, not proof of a cross-user leak, and prevents an unconditional Gate pass.

Five cases originally labelled architecture_pending now have concrete local implementation evidence (deleted HintRequest context, late in-memory upsert fence, validation-source redaction, raw-source gateway exclusion and logout revocation). Their original planned tier is preserved alongside the actual tier; in-memory index evidence does not prove an external pgvector/cache/model-reference adapter. **WG-EXTERNAL-ERASURE** remains a separate deployment dependency requiring ADR and authorization for those adapters. Installed pgvector alone is not physical erasure evidence. Both blockers must be carried into the final Gate verdict.

New fixture mistakes (unpublished URL shapes and incorrect teacher-field names) produced retained failing command records, then were corrected against existing OpenAPI/models without product permission changes. Dataset raw worktree and original LF hashes are separately recorded in verification-summary.json; all normalized LF content equals the original Git blobs. See numbered handoff for final hash labels.
