# Wave 3 Task 10 交接

**历史快照**：本文记录框架提交 `783bd84fddbeb9e0210a40e8e50170a67c5679e9` 时的失败与交付状态。用户随后授权修复；当前修复结果、文件和迁移要求见 [修复交接](task10-repair-handoff.md)。下文历史失败数量不代表修复后的状态。

基线 main：`0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07`（已核对 origin/main）。分支：`codex/wave3-task10-security-eval`。worktree：`C:\Users\lenovo\Desktop\cs competition\.worktrees\wave3-task10-security-eval`。

## 交付状态

安全测试、独立请求 E2E、Gate 浏览器 spec、评测 schema/草案/校验与复算工具、预注册协议和空结果模板已建立。**安全验收仍失败，不能发布或宣称 Wave 3 已集成。** 已发现五类权限/架构问题，保留严格失败测试并在 ADR 0006 提案；尚未获得生产修复确认。没有 skip/xfail 隐藏产品失败。

没有调用真实或付费模型，没有使用真实学生数据，没有产生教学实验结果。确定性 Mock Provider 的合成输出不是真实模型抗注入能力证据。正式教师标注与教学试点尚未进行。

## 安全覆盖与结果边界

|领域|已执行覆盖|结果与未验证范围|
|---|---|---|
|IDOR / 角色 / 课程|两学生、两教师、两课程；真实 Router 与实时授权；提交/执行/诊断/提示/解释/建议接受拒绝纠正/记忆纠正删除/分享/删除回执和重试；正文伪 owner/course/role；不同资源类型复用幂等键；停用用户|越权与不存在资源比较 HTTP、稳定 code、字段及公开 message，忽略不同 request ID。已新增跨课程 URL 攻击。撤销课程关系后 5 个资源入口仍返回 200；旧 JWT 登出重放仍 200。|
|提示注入 / 模型请求|5 种攻击变体 × 6 输入渠道；恶意结构输出、无 approved evidence、proposal-only、提前完整答案 fallback、异常脱敏；捕获最终 diagnosis/explanation/hint DTO|foreign student/course、合成密码、实际合成 token、环境 sentinel 不进入请求/日志/审计；stdout/stderr 被过滤；其他输入确实到达被测请求。模型不能覆盖确定性 evidence；原始源代码禁止项和删除后来源诊断再次进入模型上下文仍失败。Mock 不证明外部模型鲁棒性。|
|记忆 / 分享|真实 owner/course 复核；恶意/重复/未知索引候选；授权只给指定摘要；撤销立即停止；版本血缘擦除；索引删除和反查失败补偿；新 service 恢复；检索中删除并发复核|逻辑检索与补偿通过；迟到 upsert 物理索引原文复活仍失败。新 service 使用相同 store，不冒充 PostgreSQL 进程重启。没有独立缓存/外部模型引用删除适配器，不能依据 receipt flags 声称擦除。|
|PostgreSQL / pgvector|专用测试容器的 Task 6/7 真实 PostgreSQL 集成：事务、并发接受/纠正、审计回滚、分享/课程权限撤销、迁移 round-trip；SQL删除恢复、重建repository/service两次、失败脱敏、迟到publisher、重试续行|最终指定两个 PostgreSQL 文件11项通过，删除恢复4项通过，共15项；pgvector 扩展0.8.7可用，但当前 memory index 是内存适配器，没有真实向量 SQL 检索/删除集成证据。|
|小样本隐私|54 个向量，9 种过滤 × 6 场景；4/5 不同学生边界、重复学生、异课程、group 抑制、抑制敏感字段；冻结 DTO 及可复用断言；每个有效过滤条件包含额外第 5 名反例|仅契约/向量完整性与断言检查。Task 8 Router/SQL/事务未合入，不计为真实分析服务通过。Gate 装配剥离 excluded_by 元数据，不能按其预过滤。|
|执行器|显式选择本地 image，6 项实际容器测试：non-exhaustive 编译诊断、无限循环截止、4 条诊断草案；容器无网络、只读、非 root、cap-drop、no-new-privileges、限 CPU/内存/PID/tmpfs|cjc/cjpm 1.2.0。执行器协议/控制台/容器配置另有 25 项既有回归。逃逸、输出洪泛、宿主挂载/网络攻击等完整 planned 案例仍需逐条执行，不将 6 项冒充全部执行器攻击通过。|

## E2E

`security.spec.ts` 实际运行 14 项，13 passed / 1 failed：学生直接教师接口、教师私人记忆入口、学生 A 枚举学生 B 提交/执行/诊断、匿名保护 URL、学生/教师纠正和删除他人记忆、敏感验证错误、并发接受去重、摘要分享撤销均通过；登出旧令牌失败。服务只监听 loopback 8197，真实 API/权限、合成 store、Mock Provider/SyntheticRunner；不使用 Task 9 UI。

`security-ui.gate.ts` 7 项只完成收集和类型检查，**没有执行浏览器，计入通过数为 0**：学生教师 URL、教师私人记忆 URL、抑制分析不显示人数/私人对话、403/404 公共语义、敏感错误隐藏、退出后清会话、敏感操作重复点击。使用 Task 9 selectors 与 contract fixtures，保留断言且无永久 skip。Gate 必须在 Task 9 UI 就绪后运行，并补充 UI 实连 API 的组合验证。

## 数据与实验

164 条唯一、不同操作的计划安全攻击覆盖 12 类（10 类各 8 条 + 提示注入 30 + 小样本 54）。每条有前置条件、操作、预期公开拒绝/边界、敏感分级及执行层级；是计划案例，不是 164 次已执行结果，test_reference 是线索而非完整 case-to-run 证明。

诊断 4 条均 synthetic / draft、teacher_annotators=[]、verified=0；3 条真实隔离编译失败，1 条成功控制，当前工具链验证没有形成教师 gold。schema 检查唯一 ID、split、verified 审核记录条件和明显身份信息；真实性仍需独立审核。`evaluate.py` 输出结构与哈希，experiment_status=not_executed。`recompute.py` 接受未来有证据的观察，计数和 Wilson 区间，拒绝 draft 根因 gold、重复单位、缺证据、无效组/字段/哈希；不认证老师、不评分 LLM、不计算 κ/聚类 bootstrap。

protocol 已预注册三组对照、≥50/目标100真实教师核验案例、六种顺序平衡、双教师盲标/第三人裁决、八指标分子分母、缺失与超时重试、数据冻结和 split、隐私与停止规则。results-template 全部为未执行/待填写；目标准确率与零泄露门槛不描述为实际结果。

## 实际验证命令

所有 Python 命令使用根工作区 `.venv\Scripts\python.exe`，`-B` / PYTHONDONTWRITEBYTECODE=1，pytest `-p no:cacheprovider`。sandbox 中本地 ASGI/anyio 会挂起，最终测试在提升的本地执行权限下运行；未访问生产。需要 tmp_path 的命令使用本次专用且事先不存在的 visualizations/task10-*-GUID basetemp，避免默认临时目录权限失败；下表短写 python 指同一解释器。

|工作目录 / 命令|实际结果|退出码|
|---|---|---|
|backend: `python -B -m pytest tests/security -q -p no:cacheprovider --basetemp <fresh> --tb=short`，显式 TASK10_RUNNER_IMAGE|196 passed / 9 failed / 0 skipped；9项全部为 ADR 0006 中的产品失败|1|
|backend: `python -B -m pytest tests/auth tests/memories tests/model_gateway tests/contracts -q -p no:cacheprovider`|94 passed / 0 failed / 0 skipped|0|
|backend: `python -B -m pytest tests/courses tests/submissions tests/diagnostics -q -p no:cacheprovider --basetemp <fresh>`|108 passed / 0 failed / 0 skipped|0|
|backend: `python -B -m pytest tests/integration/test_task6_postgres.py tests/integration/test_task7_postgres.py -q -p no:cacheprovider --basetemp <fresh>`，TASK6_POSTGRES_URL / TASK7_POSTGRES_URL 指向本任务数据库|11 passed / 0 failed / 0 skipped；14 个既有 Alembic DeprecationWarning|0|
|backend: `python -B -m pytest tests/integration/test_task7_deletion_recovery.py -q -p no:cacheprovider`，TASK7_POSTGRES_URL 同上|4 passed / 0 failed / 0 skipped；4 个既有 Alembic DeprecationWarning|0|
|backend: `python -B -m pytest tests/security/test_evaluation_datasets.py tests/security/test_small_sample_contract.py tests/security/test_recompute.py tests/security/test_isolated_runner.py -q -p no:cacheprovider`|90 passed / 0 failed / 0 skipped（过滤窗口实际值加严前）；最终全量回归覆盖加严版|0|
|backend: `python -B -m pytest -c pyproject.toml ../runner/tests/test_protocol.py ../runner/tests/test_controller.py ../runner/tests/test_docker_engine.py -q -p no:cacheprovider`|25 passed / 0 failed / 0 skipped|0|
|backend: `python -B -m pytest -q -p no:cacheprovider --collect-only`|569 collected（后续增加2撤销POST和10跨课程参数）；只收集，不计为通过|0|
|frontend: `npx playwright test`|13 passed / 1 failed / 0 skipped|1|
|frontend: `npx playwright test --config playwright.gate.config.ts --list`|7 collected / 0 executed|0|
|frontend: `npm test`|1 passed / 0 failed / 0 skipped|0|
|frontend: `npm run build`|tsc + vite build 成功；不适用测试计数|0|
|frontend: `npx tsc --ignoreConfig --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --types node e2e/security.spec.ts e2e/security-ui.gate.ts playwright.config.ts playwright.gate.config.ts`|静态检查成功；不适用测试计数|0|
|root: `python -B data/evaluation/evaluate.py`|YAML/JSON 解析、唯一性、数量、分类、标记与结构通过；164+4，verified0|0|
|root: `git diff --check`|通过|0|
|root: `docker exec knowbound-task10-security-postgres psql ... CREATE EXTENSION IF NOT EXISTS vector` 及扩展查询|vector 0.8.7；不是向量服务测试|0|
|frontend: `npm install --save-dev '@playwright/test@^1.63.0' --ignore-scripts --no-audit --no-fund`|成功安装开发依赖；不适用测试计数|0|
|frontend: `npm install --save-dev '@types/node@^22' --ignore-scripts --no-audit --no-fund`|成功安装2个开发类型包；不适用测试计数|0|
|root: 检查 `docker inspect knowbound-task10-security-postgres` 的任务标签后 `docker rm --force knowbound-task10-security-postgres`|仅本任务容器已清理；标签筛选无残留本任务容器|0|

中间失败和修正证据：

- 数据材料未创建时的结构测试：9 failed，退出1 → 原结构/契约70 passed，退出0。
- 复算工具未创建及缺过滤反例：14 failed，退出1 → 90 passed（含容器），退出0。
- 加严 end_at 实际值完整性：1 failed，退出1；发现 `00:00:01Z` 尚在 `01:00:00Z` 上界内，已按各边界±1秒修正并纳入最终全量回归。
- 容器草案控制 main 返回2：5 passed / 1 failed，退出1；修为打印结果并 return0 → 上述90项包括6容器测试全通过。没有改执行器或放宽成功判定。
- 请求 E2E 首次启动：0 executed、RunnerRequest 缺 timeout_ms，退出1；补测试 fixture 字段后13 passed / 1产品failed。fixture 曾缺 DiagnosisService.confidence_threshold，随后修正；不属于生产缺陷。
- 前端 `npm test -- --run`：1 passed / 1 failed suite（Playwright 被 Vitest 收集）、退出1；限定 Vitest 源文件测试后1 passed、退出0。`npm run build` 此前和修正后均退出0。
- TypeScript 显式文件最初缺 --ignoreConfig（TS5112）及 Node 类型（TS2688），各退出1；正确参数+最小开发类型后退出0。
- Runner 3文件命令未显式 -c 时丢失 backend pythonpath：3 collection errors、工具报告退出1；指定现有 pyproject 后25 passed、退出0。
- 一次将 memories 和 diagnostics 同时按显式目录收集触发既有 `from conftest import` 冲突：4 collection errors、工具报告退出1；分组上述94/108实际通过；完整默认收集随后成功，不改既有 fixture 体系。
- 默认 tmp_path 首次权限错误：4 errors、退出1；使用本次独立 basetemp 后108 passed。sandbox ASGI 挂起中止的运行退出1，不计通过。
- PostgreSQL 无专用 URL 初始13 skipped、退出0；随后创建专用容器并实际执行13 passed、退出0，未用 SQLite 冒充 PostgreSQL。
- 上述早期13项是选定 PostgreSQL/删除恢复子集快照；最终分文件重新执行11+4，不把不同运行重复累计成样本数。
- 新安全边界第一次完整回归172 passed / 7 failed、退出1；这些产品 RED 保留，后续增加撤销POST影响范围。独立审查快照180 passed / 7 failed（非容器、加参数前），退出1，不与最终数量混合累计。

## 变更文件与配置影响

新增 `backend/tests/security/`：`__init__.py`、`conftest.py`、`security_support.py`、`http_fixture.py`、`analytics_assertions.py`、`test_idor.py`、`test_prompt_injection.py`、`test_cross_course_memory.py`、`test_isolated_runner.py`、`test_small_sample_contract.py`、`test_evaluation_datasets.py`、`test_recompute.py`。

新增 `data/evaluation/`：`cases.schema.json`、`security_cases.yaml`、`diagnosis_cases.yaml`、`analytics_vectors.yaml`、`evaluate.py`、`recompute.py`、`README.md`。

新增 `frontend/e2e/security.spec.ts`、`frontend/e2e/security-ui.gate.ts`、`frontend/playwright.config.ts`、`frontend/playwright.gate.config.ts`。

新增 `docs/adr/0006-task10-security-findings.md`、`docs/experiments/protocol.md`、`docs/experiments/results-template.md`、`docs/experiments/task10-handoff.md`。

修改 `frontend/package.json`、`frontend/package-lock.json`：新增最小 Playwright devDependency ^1.63.0 与配置静态检查所需 @types/node ^22；没有 runtime dependency。修改 `frontend/vite.config.ts` 仅 test.include，使 Vitest 收集 src 下 test/spec，避免 Playwright 冲突；不改构建和 UI。

未修改业务代码、OpenAPI、数据库迁移、Compose、环境示例、根级配置、Task 8/9 worktree。测试数据库为新建本次专用容器 `knowbound-task10-security-postgres`，loopback55410，合成凭证，只供 Task 6/7 集成回归；结束只清理此容器，不动已有 API/controller/PostgreSQL 容器。测试 image 使用已存在本地 image，不拉取/构建新基础设施。Playwright 默认配置与 Task 9 属共享冲突点，Gate 必须人工整合 projects/testMatch/webServer 保留两套测试。

## 独立审查与下一步

全新只读 reviewer 按用户要求及 requesting-code-review 技能检查，无直接修改。Important 发现：原时间向量不包含窗口外记录；新增反例的 end_at 值又尚在窗口内。均添加失败完整性断言后最小修正，最终回归复验。审查另外独立复现撤销课程后的提示/解释 200 且调用模型，已增加两项严格 RED 并更新 ADR。未发现真实身份、伪 verified、虚构实验结果、复制 Task 8 实现或生产业务改动。

最终补充审查确认9个四学生向量及16个独立过滤反例满足实际过滤4/忽略单项过滤5，30个文件清单完整，无新增 Critical/Important 框架问题；可交接测试与评测框架，不能宣称生产安全或 Wave 3 Gate 通过。专用测试数据库已实际清理，未删除 worktree。

Wave 3 Gate 依赖：先确认 ADR 0006 决策并修复五类问题；Task 8 合入后执行真实 Router/SQL/并发的小样本全部向量；Task 9 合入后执行7浏览器场景并实连 API；完善真实向量索引、缓存/外部引用删除探针、持久化重启与迟到 writer 验证；对164计划攻击逐条记录实际执行覆盖。真实教师 gold 和正式模型/试点须另行授权与审核。

本地提交信息：`test: add security and education evaluation harness`。最终 commit 可在该 worktree 执行 `git rev-parse HEAD` 取得，外部交接消息给出实际哈希；本文不嵌入自引用哈希。提交后工作树状态以最终 `git status --short` 为准。

未执行 merge、rebase、cherry-pick、push、PR 创建或 worktree 删除。Task 10 的框架交付不能代表 Wave 3 Gate 通过。
