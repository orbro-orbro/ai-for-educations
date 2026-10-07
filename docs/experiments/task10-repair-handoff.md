# Wave 3 Task 10 修复交接

用户在2026-10-07指示“开始修复”，授权实施ADR 0005的五类修复。修复基于框架提交 `783bd84fddbeb9e0210a40e8e50170a67c5679e9`，分支为 `codex/wave3-task10-security-eval`，worktree为 `C:\Users\lenovo\Desktop\cs competition\.worktrees\wave3-task10-security-eval`。最终提交哈希由交接消息给出，本文不写入自引用哈希。

## 完成内容与覆盖矩阵

|边界|实现及已验证范围|剩余限制|
|---|---|---|
|角色、课程与IDOR|学生读取自己的提交也检查当前课程关系；撤销后提交、执行、诊断、提示、解释统一404且不调用模型。两学生、两教师、两课程的既有越权、不存在资源、分享撤销、停用用户、伪造正文与幂等回归保留|Task 8 Router/SQL及Task 9 UI尚未合入|
|登出|受保护POST /auth/logout返回204，只撤销当前登录；随机jti区分登录；仅保存SHA-256和到期时间。SQL多实例、重启、并发幂等撤销、另一登录有效、存储故障脱敏503均验证；规范JWT编码封闭padding/unused-bits变体|内存仓库仅用于开发和测试；生产使用DATABASE_URL的SQL仓库|
|模型隐私与注入|最终SourceContext仅保留路径并拒绝content；编译器消息、规则证据不外发原文；提示和解释使用已审核课程知识。实际源码、编译器回显、其他学生/课程记忆、凭证、环境sentinel与stdout/stderr不进入被测DTO。原始证据保留在本地作绑定校验|仅确定性Mock Provider；不证明真实模型抗注入能力。外发信息减少，教学准确率未评测|
|删除与迟到索引|upsert在权威memory_claim内复核版本、内容、状态、到期与删除记录，delete保留禁写栅栏；重建索引绑定SQL仓库后拒绝旧文本。共享同库仓库包装器使用调用方活动UOW，避免自锁|当前是内存派生索引；没有真实pgvector索引擦除证据|
|来源及衍生文本擦除|同一删除事务脱敏提议正文、诊断root_cause/evidence.summary、提示reason/content、理解验证feedback/evidence_summary并禁用记忆资格；内存运行结果缓存同步脱敏。SQL重启、失败审计回滚、历史迁移擦除验证。迟到提议/理解验证/提示/缓存不能恢复旧内容；删除后待确认提议不可接受或纠正|保留原始提交与课程资料。没有独立外部缓存或模型引用删除适配器；receipt标志不是这些服务的物理证明|
|并发锁序|来源先锁诊断父行再锁子记录，写入前重新核验来源。实际PG复现delete与另一pending proposal accept/correct死锁后修复；父锁为FOR NO KEY UPDATE，与外键KEY SHARE兼容。既有并发去重与幂等冲突断言保留|不扩展到未合入的Task 8/9事务|
|教学评测与小样本|164条security planned、4条diagnosis synthetic draft、54条analytics planned向量与校验/复算工具保留；verified=0、教师标注=0。协议和结果模板仍为未执行|54向量没有执行Task 8真实聚合；7个UI Gate场景没有执行浏览器。教学实验未执行|

没有调用真实或付费模型，没有使用真实学生数据，没有填写虚构教学结果。未修改评测案例、协议或空结果模板以制造通过率。

## 验证命令与实际结果

Python使用 `C:\Users\lenovo\Desktop\cs competition\.venv\Scripts\python.exe`，加 `-B` 与 `PYTHONDONTWRITEBYTECODE=1`。以下命令的工作目录为backend（标明frontend/root的除外）。pytest统一 `-p no:cacheprovider`；使用tmp_path的运行加 `--basetemp <fresh task10-*-GUID>`，该路径事先不存在且位于本次可写visualizations目录。本地ASGI/anyio测试在提升权限下执行，未访问生产。

|命令|结果|退出码|
|---|---|---|
|`python -B -m pytest tests/security/test_security_repairs.py -q -p no:cacheprovider`|15 passed / 0 failed / 0 skipped|0|
|`python -B -m pytest tests/security -q -p no:cacheprovider --tb=short --basetemp <fresh>`；显式TASK10_RUNNER_IMAGE|220 passed / 0 failed / 0 skipped，包含6项实际隔离容器编译/运行|0|
|`python -B -m pytest tests/auth tests/memories tests/model_gateway tests/contracts -q -p no:cacheprovider --basetemp <fresh>`|94 passed / 0 failed / 0 skipped|0|
|`python -B -m pytest tests/courses tests/submissions tests/diagnostics -q -p no:cacheprovider --basetemp <fresh>`|108 passed / 0 failed / 0 skipped|0|
|`python -B -m pytest tests/persistence -q -p no:cacheprovider --basetemp <fresh>`|27 passed / 0 failed / 0 skipped；此结构套件不替代PG集成|0|
|`python -B -m pytest tests/integration/test_task10_security_repairs.py -q -p no:cacheprovider --tb=short`；TASK10_POSTGRES_URL|10 passed / 0 failed / 0 skipped；14个既有Alembic DeprecationWarning|0|
|`python -B -m pytest tests/integration/test_task6_postgres.py tests/integration/test_task7_postgres.py tests/integration/test_task7_deletion_recovery.py tests/integration/test_task10_security_repairs.py -q -p no:cacheprovider --basetemp <fresh>`；三个TASK*_POSTGRES_URL|25 passed / 0 failed / 0 skipped；32个既有Alembic DeprecationWarning|0|
|frontend: `npx playwright test`|14 passed / 0 failed / 0 skipped；请求E2E，使用真实API授权及合成仓库|0|
|frontend: `npx playwright test --config playwright.gate.config.ts --list`|7 collected / 0 executed，不计通过|0|
|frontend: `npx tsc --ignoreConfig --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --types node e2e/security.spec.ts e2e/security-ui.gate.ts playwright.config.ts playwright.gate.config.ts`|静态检查成功|0|
|root: `python -B data/evaluation/evaluate.py`|164+4结构、来源与哈希检查成功，verified=0、experiment_status=not_executed；启动器有现有Python路径提示但返回正常|0|
|root: `git diff --check`|通过；仅Git既有LF/CRLF提示|0|
|root: `docker inspect knowbound-task10-repair-postgres`核验任务标签后 `docker rm --force knowbound-task10-repair-postgres`，再按该标签查询|本任务专用容器已清理，无同标签残留；不动已有日常容器|0|

测试数据库仅本次 `knowbound-task10-repair-postgres`，loopback55410、数据库task10_repair，合成凭证；TASK6_POSTGRES_URL / TASK7_POSTGRES_URL / TASK10_POSTGRES_URL均指向该库。执行器显式使用已存在的 `knowbound-cj-runner-sandbox:1.2.0`，cjc/cjpm 1.2.0，不执行宿主不可信代码。原框架的构建、25项执行器协议测试、数据校验和其他验证详见历史交接；不把历史次数累计为新样本。

## 失败到通过的证据

- 原框架9项产品失败均保留，逐项修复后纳入完整220项安全回归，没有skip/xfail或降低授权断言。
- 首批5项新修复回归观察到5 failed，再实现后通过；撤销存储读/写503测试直接覆盖边界并通过。
- JWT两种等价编码在登出后仍有效：2 failed（退出1）→规范编码修复后通过。
- 失败执行缓存阻断删除、旧提议来源快照和晚返回解释：3 failed（退出1）→修复后通过。
- 迟到提示/运行缓存：1 failed（退出1）；SQL跨实例晚解释/提示/提议：3 failed（退出1）→删除栅栏后通过。
- 已删来源的pending proposal接受/纠正：本地2 failed（退出1）；真实PG并发两参数均DeadlockDetected（2 failed，退出1）→统一父先锁及来源复核后通过。
- 原PG幂等冲突测试在事务内设置Barrier，新增来源锁使第二writer阻塞于父行，首writer等待Barrier，整体运行挂起。检查pg_stat_activity后仅停止本次pytest进程（退出1）；把Barrier移到请求开始前并加5秒超时，保留两资源同key并发及accepted/conflict全部断言后重新运行。测试同步修改反映新增串行化要求，没有绕过真实SQL。
- 默认pytest临时目录曾出现13项fixture权限错误、14项通过；专用fresh basetemp后结构套件27项通过。环境错误与产品RED分开记录。

## 修改的全部文件

生产新增：`backend/app/auth/revocations.py`、`backend/app/auth/persistence.py`、`backend/migrations/versions/0006_token_revocations.py`。

生产修改：`backend/app/api/auth.py`、`backend/app/api/errors.py`、`backend/app/diagnostics/hints.py`、`backend/app/diagnostics/persistence.py`、`backend/app/diagnostics/repository.py`、`backend/app/diagnostics/service.py`、`backend/app/main.py`、`backend/app/memories/deletion.py`、`backend/app/memories/persistence.py`、`backend/app/memories/repository.py`、`backend/app/memories/retrieval.py`、`backend/app/memories/service.py`、`backend/app/memories/source.py`、`backend/app/model_gateway/base.py`、`backend/app/persistence/models.py`、`backend/app/persistence/repositories.py`、`backend/app/submissions/service.py`、`contracts/openapi.yaml`。

测试新增：`backend/tests/security/test_security_repairs.py`、`backend/tests/integration/test_task10_security_repairs.py`。

测试修改：`backend/tests/memories/test_deletion.py`（普通迟到upsert应被拒绝，再人工污染原始派生存储以继续验证物理反查）、`backend/tests/integration/test_task7_postgres.py`（并发同步点）、`backend/tests/security/test_idor.py`、`backend/tests/security/test_prompt_injection.py`（源码注入渠道改为验证被过滤，其他渠道保留可达性断言）、`frontend/e2e/security.spec.ts`（登出必须204，旧token必须401）。

文档修改：`docs/adr/0005-task10-security-findings.md`、`docs/experiments/task10-handoff.md`（标记历史快照）、`data/evaluation/README.md`。文档新增：本文。忽略目录中的内部ledger记录实施决策和证据，不作为交付文件提交。

## 数据库、API与部署要求

新增OpenAPI路径 `POST /auth/logout`：bearer认证、成功204、认证失败401、存储不可用503；其他路由及既有错误契约沿用。组合根在DATABASE_URL存在时注入SQL撤销仓库及共享删除UOW；开发测试保留内存实现。没有新增依赖、Compose、环境变量示例或根级配置，没有修改Task 8/9 worktree。

部署前在backend运行 `alembic upgrade head`，新增token_revocations表（digest主键64字符、expires_at秒数），并单向擦除已deleted/deletion_pending记忆关联的历史来源文本。必须先备份和按环境流程安排迁移；这里仅在专用测试库验证升级、降级、重新升级，未部署到任何真实环境。旧源码提交、课程与证据关联元数据保留。

**回滚要求**：降级会丢弃撤销表，重新升级不会恢复撤销记录；重新启用认证前必须轮换AUTH_TOKEN_SECRET，使旧JWT失效。擦除的私人文本不会在降级后恢复。部署期间不得依赖旧实例继续接受已删除来源的迟到写入，需完成实例切换后再开放服务。

## 独立复核与剩余任务

全新只读上下文独立审查发现JWT编码绕过、晚写入和失败缓存3项Important，后续提出父子锁序问题。全部按失败测试→最小修复→回归处理。最终独立本地15项通过，确认父锁编译为FOR NO KEY UPDATE、失败删除回滚内存栅栏；未发现新增Critical/Important。审查者没有改文件、访问测试数据库或调用真实模型。PG证据来自主Agent实际运行。

Wave 3 Gate仍需：合入Task 8后执行54向量的真实Router/SQL/过滤及并发抑制；合入Task 9后执行7浏览器场景并实连API；增加真实向量、独立缓存和外部引用擦除适配器/探针；逐条记录164计划攻击的实际执行覆盖；按协议获得≥50、目标100教师核验案例并另行授权正式模型/教学试点。框架、Mock、合成数据和绿色局部回归不能代表这些工作已完成。

本任务专用容器已核验标签并清理，无同标签容器残留；根main仍干净。本分支创建本地提交，提交后工作树状态及实际哈希见最终交接消息。未执行merge、rebase、cherry-pick、push、PR创建或worktree删除。
