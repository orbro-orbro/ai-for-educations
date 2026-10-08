# Wave 3 Integration Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 主 Agent 串行实施；全部验证结束后才使用一个全新只读审查上下文。

**Goal:** 语义集成 Task 8、9、10，以真实 PostgreSQL、隔离 Runner 和浏览器证据判断 Wave 3 Gate，形成本地提交与可复核交接。

**Architecture:** 沿用 React → FastAPI → PostgreSQL 的既定边界，教师服务只消费最小去标识事实。SQL 教师复核和 SqlAuditLog 共享现有 SqlMemoryUnitOfWork；不为可派生统计另存学生记录。测试使用独立本地 Compose 项目、分开的测试数据库、合成资料和确定性 Mock Provider。

**Tech Stack:** React、TypeScript、Vite、Vitest、Playwright/Edge、FastAPI、SQLAlchemy、Alembic、psycopg、PostgreSQL 17/pgvector、Docker、仓颉 1.2.0 STS cjnative、pytest；沿用已有依赖。

**Spec:** `docs/superpowers/specs/2026-10-01-knowbound-cangjie-design.md`、`docs/superpowers/plans/2026-10-01-knowbound-cangjie-implementation.md`，以及用户 2026-10-08 提供的 Wave 3 Integration Gate 要求。

**状态：用户已于 2026-10-08 确认实施。** 以下只读审计记录保留其发生时的状态；实施只在独立 Gate 分支/worktree 进行，实际结果见 `docs/experiments/wave3-integration-handoff.md` 和命令记录。本文不提交到 main。

## Global Constraints

- 首个试点课程：《仓颉语言设计》；仅教师、学生两类角色。
- 主线为仓颉概念误区诊断；教师默认不能读取私人对话或完整学习记忆。
- 长期记忆必须本人确认，可以纠正、拒绝、删除；教师复核不得改变学生记忆。
- 少于 5 名不同学生时完整抑制；每个过滤集合和每个 group 各自重新检查。
- OpenAPI 是公开接口事实来源；PostgreSQL 是生产权限和状态事实来源。
- 不可信源码只进入一次性隔离 sandbox；API、controller 和宿主不得执行它。
- 不用真实学生数据、不调用真实/付费模型；Mock、合成、planned、collected、skipped 均不得冒充真实通过或试点结果。
- 不增加外部基础设施、生产依赖、角色、UI 设计或冻结接口；关键架构/权限变更先 ADR 并获得用户确认。
- Task 8/9/10 worktree 只读；产品修改仅在批准后的 Gate worktree。
- 最终不 merge 到 main、不 rebase、不 push、不创建 PR、不删除任何 worktree。

## Review Focus

1. 等锁期间教师关系撤销：锁内重新解析课程并检查当前权限；拒绝/未知统一 404。由 G3 的 PostgreSQL 两实例测试覆盖。
2. 诊断/证据正文夹带私人信息：队列投影只由已审核课程证据生成，不透传个人 root_cause、compiler echo、queue summary。由 G2/G3 的 sentinel 和实际 SQL 投影测试覆盖。
3. JOIN 放大、重复学生和跨课程键：每诊断一条事实、course-scoped subject_key；人数与诊断次数分别去重。由 G2/G5 覆盖。
4. 日期结束日及快速课程切换：end 排除、结束日期转次日零时；陈旧响应不能覆盖新课程。由 G6 的单测与 G8 手机浏览器测试覆盖。
5. 旧 schema 测试降级误伤新应用：旧 Task 6/7 测试库、迁移库和浏览器库隔离，DATABASE_URL 不得覆盖 Alembic 测试库配置。由 G0/G7 环境检查覆盖。

---

## 1. 只读审计事实（2026-10-08，Asia/Shanghai）

### 1.1 Git 基线与来源

`git status --short --branch` 开始时仅显示 main 跟踪 origin/main，无改动。三个任务 worktree 均干净；Gate 分支/worktree 不存在。

本地 main、origin/main 缓存，以及本次实际 `git ls-remote origin refs/heads/main` 均为：

`0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07`

|顺序|分支|提交|父提交|相对 main 文件数|
|---|---|---|---|---|
|1|codex/wave3-task8-analytics|988cc2c49265667a7ddeba8d50a92269467c0407|0598a2e…|11|
|2|codex/wave3-task9-ui|ce9fe25486ee2c900af8a837429421d14f7fc010|0598a2e…|27（两提交合计）|
|3|codex/wave3-task9-ui|b53b4b4d3f5d18dfab2505a07fde9bb96c10bf4d|ce9fe254…|同上|
|4|codex/wave3-task10-security-eval|783bd84fddbeb9e0210a40e8e50170a67c5679e9|0598a2e…|56（两提交合计）|
|5|codex/wave3-task10-security-eval|e39f0df42e5fb17fc60e84f92db8051fb0d3a726|783bd84f…|同上|

以上关系与用户记录一致。批准后仍需再次核对；任何变化先报告，不自行换基线或来源。

完整三份 diff 已读取并建立文件清单；大型锁文件和合成 YAML 同时做全量结构解析。UTF-8 diff 内容指纹（本轮 Git 输出格式）：

|分支|diff 行数|SHA-256|
|---|---:|---|
|Task 8|1715|3354d7b9073e8ced33d2afaa581f3c6f2907aaf4325190336d969fd0c8f189cf|
|Task 9|2174|29ff6396cbbc6dee344612a522cd59344641ee34f569db728290f3953018c61d|
|Task 10|15599|6efadb6b4c7bbcd230a03d7ec7b2dd91394e3e256dd064f5f45135a49b3c9762|

### 1.2 已读交接、设计、ADR 和测试

- 根 AGENTS.md、项目设计、总实施计划，ADR 0001–0004；Task 9 CORS ADR 0005；Task 10 安全 ADR 0005（已接受实施，记录用户 2026-10-07 授权）。
- Task 10 的 `docs/experiments/task10-handoff.md`、`task10-repair-handoff.md`；历史失败与修复结果分别看待。
- Task 8/9 没有仓库内独立最终交接文件；通过已有本地会话记录读取最终交接，未把“文件不存在”解释成“未完成”。来源：
  - `C:/Users/lenovo/.codex/sessions/2026/10/07/rollout-2026-10-07T10-30-16-01a11432-7fe6-7b32-98fe-c67550c06a97.jsonl`（Task 8）。
  - `C:/Users/lenovo/.codex/sessions/2026/10/07/rollout-2026-10-07T11-52-00-01a1147d-544b-74c1-9cf8-1567964bb329.jsonl`（Task 9 UI、CORS 后续修复及最后状态）。
- `contracts/openapi.yaml` 全量解析；当前 SQL 模型、所有 0001–0005 迁移及 Task 10 的 0006；组合根、认证、诊断、删除、检索、审计、SQL 仓库及相关现有测试。
- Task 8 analytics 三套测试；Task 9 学生/教师组件、样式和学习 E2E；Task 10 security、PG repair、两个 Playwright spec 和 Gate 配置；现有 contracts、persistence、Task 6/7 PG/闭环、Runner/controller 测试与镜像定义。

### 1.3 实际缺口

|领域|审计结果|计划处理|
|---|---|---|
|Task 8|领域事实/内存仓库/服务/Router 已有；未挂载，无 SQL 教师复核表|G2/G3/G4；新增唯一 0007|
|复核原子性|领域使用 ExitStack 包裹 repository.transaction 与 audit.transaction；内存回滚不能证明 SQL 原子提交|复用同一 UOW 和同一 Session，并测试真实 commit/rollback|
|教师队列|上游候选携带 root_cause/evidence_summaries，直接 SQL 透传个人诊断文本会违反最小化要求|已审核课程知识投影；不读私人记忆/对话正文|
|运行时契约|现有测试主要检查 runtime ⊆ shared；本轮发现 22 个旧 operation 存在 operationId、security 或 response 状态漂移|G4 全量对齐，不只补三个教师接口|
|教师 Router|operationId 和错误模型已有；未显式声明 bearerAuth；analytics union 与 shared oneOf/discriminator 需对齐|失败契约测试后修正声明/DTO 元数据|
|Task 9 logout|App.tsx 退出只清 localStorage；ApiClient 没有 logout|G6 调服务端再清会话，503 不宣称令牌已撤销|
|前端配置|两分支同时新增 playwright.config.ts；Vitest include 一个是 tests/all.test.ts，另一个是 src glob|保留聚合入口，分离 request/UI projects，测试不能漏收|
|浏览器证据|Task 9 2 项、Task 10 7 项 UI 场景均依赖 route.fulfill；security.spec 为真实 HTTP + 内存合成仓库|保留原断言，另加真实 PG/API/Runner 的组合项目|
|日期窗口|Teacher UI endOfLocalDay 使用 23:59:59.999；后端 end 排除|先边界测试，改为次日零时和相邻等长半开窗口|
|迁移|现行单链至 0005；Task 10 的 0006 接 0005，包含单向历史私人文本擦除|G7 测完整链；0007 接 0006|
|旧 PG 测试|Task 7 固定升到 0005，并有 downgrade base；migrations/env.py 优先读取 DATABASE_URL|按数据库隔离并控制进程环境，不能指向浏览器/日常库|
|删除适配器|SQL 记忆权威状态已有；当前派生 index 仍为 InMemoryRetrievalIndex，无独立外部缓存/模型引用服务|验证现有适配器，明确未实现边界；不擅自造新服务或把 receipt 布尔值当物理证明|
|攻击映射|164 案例仅 planned；test_reference 在 input 中，多数仅指向文件，不能推导逐条通过|G9 建独立执行 manifest 与具体 node ID/操作映射|

源交接报告 Task 8 68 项领域测试、Task 9 30 项组件/2 项契约浏览器、Task 10 220 项安全/25 项选定 PG/14 项请求 E2E 曾通过。这些是历史报告，**本轮没有重跑，不能算 Gate 结果**。Task 10 7 项 UI 只收集，54 向量只验证预期结构，真实聚合执行数均为 0。

全量解析当前数据：security 164 draft、diagnosis 4 draft、analytics 54（9×6），teacher verified=0。security input.execution_tier：local_mock 99、postgres_gate 57、architecture_pending 5、container_gate 3；没有逐案例 execution_status 或结构化 severity 字段。

数据原始 SHA-256：

- security_cases.yaml：`a5a33c34cc95887988972dd094d4743d14bd8c5e31df501f71c2d21fff36e34e`
- analytics_vectors.yaml：`dbef2c0beb43de36faac58fbd9eb4b3277b039c046c9e607435be25d1a8ba2b5`
- diagnosis_cases.yaml：`96ace03aab66ca806e5e56152d1fe939cf8701c6d3b31c6422e95c84d49d4410`

### 1.4 环境证据与本轮命令

|只读命令/工作目录|实际结果|退出码/边界|
|---|---|---|
|root: `git status --short --branch`、`git worktree list --porcelain`、`git branch -avv`|main 与任务分支/工作区关系核对完成|0；无改动|
|root: `git log --reverse --format='%H %P %s' main..<branch>`（三个分支）|五个提交、父关系均一致|0|
|root: `git diff main <branch>` / `git diff --stat main <branch>`（三个分支）|完整 diff、文件清单及上述指纹|0；无修改|
|root: `git ls-remote origin refs/heads/main`|首次受限环境 getaddrinfo 失败；提升权限只读重试得到 0598a2e…|首次所在组合命令工具返回1，重试0；不 fetch/push|
|root: `docker version --format '{{.Client.Version}} {{.Server.Version}}'`|受限环境 daemon permission denied；只读重试 Client/Server 均29.8.1|首次1，重试0|
|root: `docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'`、`docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}}'`|已有日常 api/controller/postgres；有 sandbox 1.2.0 image `082f87930e27` 和 pgvector:pg17 image `ac08538c6f8b`|提升权限0；没有启动/重建/停止容器|
|root: `docker exec knowbound-cj-postgres-1 psql -U knowbound -d knowbound -Atc "SELECT version(); SELECT extname,extversion FROM pg_extension WHERE extname='vector';"`|PostgreSQL17.11；已安装 vector 查询无行|0；只读现有库|
|root: 同 psql 查询 `SELECT name,default_version,installed_version FROM pg_available_extensions WHERE name='vector';`|vector可用0.8.7，installed_version空|0；未 CREATE EXTENSION|
|root: `cjc -v`、`cjpm -v`|均1.2.0；宿主 Windows cjnative|0；只报版本，无源码执行|
|root: `node --version`、`npm --version`|v24.15.0 / 11.12.1|0|
|root: `Test-Path 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'`|True|只证明安装存在，不证明浏览器测试通过|
|root: `.venv/Scripts/python.exe -B -c "print('audit-python-ready')"`|受限启动迟滞；提升权限启动正常|正常重试0；先前迟滞的组合命令中止1，不算验证通过|
|root: `.venv/Scripts/python.exe -B C:/Users/lenovo/.agents/skills/cangjie-coding/scripts/search_docs.py --query 'cjc 诊断 JSON' --query 'cjpm 版本' --max-results 1`|命中 tools.cjc/tools.cjpm 摘要，具体诊断/版本词无精确叶子命中|0；不是语义编译验证|
|root: 只读 Python stdin 审计脚本、Get-Content/rg 查询|全量解析共享契约/迁移/数据，列出运行时22处声明差异、测试与diff文件清单；读取相关会话交接|0；使用-B，不生成项目缓存|

上述临时审计脚本内容在本聊天工具记录中；它们没有保存到产品文件。仅声明读取/环境检查结果；本轮单元、PG、浏览器、Runner 攻击、迁移验证均 **not_executed**。

## 2. 方案选择与冲突规则

采用用户建议的五次 `cherry-pick -x`，随后分阶段补 SQL、装配、契约和真实验证。逐提交来源清楚，便于检查每项行为是否保留。

不采用分别 merge 三个分支（历史交叉更复杂），也不重写/复制全部实现（丢失来源且易漏安全修复）。这不是新的产品设计；沿用既定契约和已批准 ADR。

|共享文件|必须保留的语义|解决/验证方式|
|---|---|---|
|backend/app/main.py|Task9 CORS；Task10 SQL撤销、删除source_context；Task7记忆；Task8教师SQL/内存装配、错误/request ID|按职责逐块合并；禁止整文件ours/theirs；装配测试逐一断言|
|frontend/package.json + package-lock.json|test:e2e，Playwright1.63.0、@types/node22.20.5及既有依赖|先合并manifest，再只更新必要lock元数据；不升级依赖；npm ci检查一致性|
|frontend/vite.config.ts|Task9聚合入口/单worker；Task10禁止误收Playwright|保留tests/all.test.ts并导入新增组件测试；检查旧30项全部执行|
|frontend/playwright.config.ts|Task9真实Edge UI server；Task10独立8197 request API server|projects + webServer数组，各自baseURL/testMatch；缺server直接失败，reuseExistingServer=false|
|frontend/playwright.gate.config.ts|原7项UI断言及真实组合场景|7项projection显式保留；新增real-ui project，无API拦截；两类证据分别报告|
|contracts/openapi.yaml|Task2–7、冻结3教师接口、logout204/401/503|来源logout增量保留；冻结字段不改；修运行时声明，不从runtime反写共享契约|
|backend/app/persistence/models.py + repositories.py|Task10 token表/仓库及现有UOW|新增最小TeacherDiagnosisReviewRow/SQL端口，共享同一Session事务|
|docs/adr/0005-*|CORS保留0005；Task10安全改0006|标题、文件名及所有可交付引用同步，历史状态保留|
|Compose/.env.example|严格白名单、固定sandbox边界和既有默认值|Task9来源保留；Gate只做本地测试override，不影响日常项目|

每次真实冲突写入 `docs/experiments/wave3-integration-handoff.md`：路径、来源提交、保留行为、解决原因、对应测试。没有冲突也记录语义检查。ADR 编号与 Alembic revision 独立。

## 3. 执行环境和命令约定（批准后）

所有以下命令是 **计划，不是已运行结果**。

```powershell
$projectRoot = 'C:\Users\lenovo\Desktop\cs competition'
$gateRoot = Join-Path $projectRoot '.worktrees\wave3-integration-gate'
$gatePython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
```

Python测试在 Gate/backend，使用根已有解释器；pytest加 `-p no:cacheprovider` 和每次独立、事先不存在的 `--basetemp`。本地ASGI/anyio、Docker和浏览器需要的执行权限可申请工具提升；环境权限失败不算产品FAIL，更不能算PASS。

测试项目名 `knowbound-wave3-gate`，端口预选 API8198 / UI5199 / request-fixture8197 / PG55430 / controller8199，均loopback。启动前查占用；若占用改一组显式配置并记录，不复用日常8000/5173服务。Gate标签 `knowbound.task=wave3-integration-gate`，不停止日常容器。

同一专用PG容器使用独立数据库：`wave3_task6`、`wave3_task7`、`wave3_task10`、`wave3_router`、`wave3_migration`、`wave3_browser`。旧测试的downgrade与新Router/浏览器完全隔离。

- pytest进程删除DATABASE_URL（Task6/7 fixture会自己配置），设置各TASK*_POSTGRES_URL；新测试用WAVE3_POSTGRES_URL。
- 浏览器API进程的DATABASE_URL只能指向wave3_browser；使用现有create_app和真实SQL repos、SQL撤销、TeacherAnalyticsService、RunnerClient，注入确定性Mock Provider。
- Mock只替换模型；真实组合不得替换授权、SQL、教师数据源、删除事务或Runner。
- 启动器为测试文件，APP_ENV=test、已安装依赖、无外部模型密钥；不得改生产mock默认策略来凑测试。
- 新UOW/表不读取个人记忆参与教师统计；subject_key只存在内部事实DTO。

## 4. 分阶段实施与提交

### G0：批准后创建隔离工作区和测试记录

**Files:** Gate副本中的本文；Create `docs/experiments/wave3-integration-handoff.md`、`docs/experiments/wave3-command-results.json`；Create `infra/compose/docker-compose.wave3-gate.yml`、`backend/tests/integration/wave3_environment.py`、`backend/tests/contracts/test_wave3_environment.py`。

**Interfaces:** 消费核实后的main/五来源提交；产出唯一Gate目录、基线哈希和每命令执行记录。

- [x] 使用 using-git-worktrees、executing-plans 技能；再次核对main远端、来源父关系、任务worktree状态和`.worktrees`忽略规则。变化立即报告。
- [x] 仅确认后运行：

```powershell
git check-ignore .worktrees
git worktree add '.worktrees/wave3-integration-gate' -b codex/wave3-integration-gate 0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07
```

- [x] 将根未跟踪计划复制到Gate同相对路径、核对SHA-256，然后移除根未跟踪副本，保持main产品与历史不变；不能覆盖用户新增改动。计划在Gate首次文档提交中跟踪。
- [x] 日志每行包含command、cwd、start/end实际时间、exit_code、passed/failed/skipped/not_executed、测试计数、环境变量名和合成配置、服务类型、证据路径/哈希。真实令牌/密码/密钥不写日志。
- [x] 先写环境契约RED：override端口必须loopback、不覆盖日常项目卷、sandbox无网络/无socket；初始化器拒绝非Gate资源和非wave3_库。实现最小测试override/初始化器后观察GREEN，再创建上述独立PG容器/六个空测试库和受信controller（仅既有拓扑的隔离测试副本）。不启动API/UI，待G8。Task10安全容器测试沿用已存在授权镜像，设置TASK10_RUNNER_IMAGE。
- [x] 实际启动命令为root的 `docker compose -p knowbound-wave3-gate -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.wave3-gate.yml up -d postgres runner-controller`；override的PG发布55430、controller发布8199，初始化器通过Gate标签核对后创建专用空库和vector扩展。源runner未被Task8/9/10改动，仍需G8真实验证；API镜像必须在来源集成后构建。
- [x] 基线运行局部auth/contracts/persistence和前端既有单测；将发现与本轮只读差异区分，不能先行修生产。
- [x] 提交仅计划与初始化记录：`docs: record Wave 3 integration plan and baseline`。

### G1：按五提交串行集成并解决共享配置

**Files:** 三来源diff的全部文件；重点为上表共享文件。

**Interfaces:** 产出既有Task8领域Router、Task9 UI、Task10修复和测试，尚不代表SQL Gate通过。

- [x] 依次cherry-pick（每次完成验证再开始下一次）：

```powershell
git cherry-pick -x 988cc2c49265667a7ddeba8d50a92269467c0407
git cherry-pick -x ce9fe25486ee2c900af8a837429421d14f7fc010
git cherry-pick -x b53b4b4d3f5d18dfab2505a07fde9bb96c10bf4d
git cherry-pick -x 783bd84fddbeb9e0210a40e8e50170a67c5679e9
git cherry-pick -x e39f0df42e5fb17fc60e84f92db8051fb0d3a726
```

- [x] Task8后：`& $gatePython -B -m pytest tests/analytics tests/contracts/test_wave3_openapi.py -q -p no:cacheprovider`。
- [x] Task9 UI后：frontend `npm test`、`npm run build`、原配置 `npx playwright test`（此时仅learning-loop）；Task10配置合并后才使用 `--project learning-ui`。CORS后backend `pytest tests/test_cors.py tests/contracts/test_compose_contract.py`。
- [x] Task10框架提交可能重现已记录的历史安全RED：封存并核对是否精确属于下一修复提交，不改断言，随后应用已授权的e39f0df。新的Critical/Important失败必须停止；不能把框架RED当最终允许失败。
- [x] Task10修复后：`pytest tests/security -q`，显式TASK10_RUNNER_IMAGE；观察220项全部执行。每次cherry-pick后 `git diff --check`、`git ls-files -u`；冲突逐块合并并记录来源。
- [x] Playwright默认配置各project独立匹配：learning-ui只learning-loop.spec.ts；security-request只security.spec.ts。Vitest仅tests/all.test.ts；新增测试必须导入聚合入口。
- [x] 将安全ADR重命名 `0006-task10-security-findings.md`，标题改ADR0006；`rg -n '0005-task10|ADR 0005' docs data`逐处区分CORS与安全，更新安全引用，不误改CORS。
- [x] 来源cherry-pick保留自己的-x提交；共享配置/ADR收尾单独提交 `chore: reconcile Wave 3 test configuration and ADR references`。

### G2：真实SQL匿名事实和安全队列投影

**Files:** Create `backend/app/analytics/persistence.py`；Create `backend/app/analytics/data_source.py`（开发内存动态投影）；Create `backend/tests/integration/wave3_support.py`；Create `backend/tests/integration/test_wave3_analytics_postgres.py`；Create `backend/tests/analytics/test_data_source.py`。

**Interfaces:** 实现现有TeacherAnalyticsRepository的 `list_facts(course_id)`、`list_candidates(course_id)`、`get_candidate(diagnosis_id)`；返回现有AnalyticsDiagnosisFact/TeacherReviewCandidate。SQL仓库名 `SqlTeacherAnalyticsRepository(uow)`；内存动态源 `InMemoryTeacherAnalyticsDataSource(submissions, diagnostics, knowledge)`。

- [x] 先写PG失败测试：真实已迁移数据库创建课程、用户、练习、提交、诊断、概念、理解检查；构造4/5学生、同学生重复、多概念、多理解检查、异课程、边界时间。通过真实服务/Router取JSON，而非直接返回expected_response。

```python
@pytest.mark.parametrize("students,status", [(4, "insufficient_sample"), (5, "available")])
def test_distinct_students_at_sql_boundary(wave3_pg, students, status):
    seeded = wave3_pg.seed_diagnoses(students=students, duplicates=3)
    response = wave3_pg.get_analytics(seeded.course_id)
    assert response.status_code == 200
    assert response.json()["status"] == status
    if students == 4:
        assert set(response.json()) == {"status", "course_id", "filters", "minimum_sample_size"}
    else:
        assert response.json()["sample_size"] == 5
```

`wave3_pg`为wave3_support定义的测试fixture端口：seed_diagnoses、get_analytics使用实际数据库行与登录Router；不得用内存facts替代。G2/G3先在独立FastAPI测试应用挂载原create_teacher_router并注入真实SQL服务，以完成局部RED/GREEN；G4才验证正式create_app组合根，G5再次使用正式组合根。G0已准备空库，fixture以当时Gate实际head迁移，不能等待G7才建立数据库。

- [x] 运行上述文件观察RED，记录缺SQL适配器/Router的失败；禁止用SQLite验证此任务。
- [x] 最小SQL SELECT只取DiagnosisRow.id/course/category/created_at、SubmissionRow.id/exercise/owner作为内部键、DiagnosisConceptRow.concept_id和理解验证布尔事实；不取source_files、个人root_cause、feedback、memory正文。每诊断一条事实，concept去重，检查多子行JOIN不放大。
- [x] subject_key用课程+owner经现有AUTH_TOKEN_SECRET派生HMAC-SHA256（固定teacher-analytics用途前缀）；只在内部DTO，不能进API/log/audit。数据库不新增subject映射表，不暴露跨课相同key。
- [x] `independent_repaired`使用保守可证明证据：同诊断存在`understands=true`且confidence达到课程阈值的ExplanationCheck，并存在DiagnosisAttemptRow明确关联的retry SubmissionRow；retry必须与原诊断同owner/course/exercise、created_at晚于原提交、ExecutionResultRow.status=succeeded，且修复成功前无level4 HintEvent。用EXISTS避免多个理解/attempt倍增；仅理解通过、没有明确retry关联、低置信度或失败执行均为false。向量true事实通过这些关系行表达，不能直接写一个模拟布尔列。这是应用行为指标，不是预注册30分钟/3次教学实验率；不能称真实自主修复成效。增加上述正反例SQL测试；不把同练习的任意后续提交猜成原诊断的独立修复。
- [x] 队列重连queue→diagnosis→submission验证ID/course一致，diagnosis为空或关系不匹配不产生可复核候选；课程以诊断/提交权威关系重新解析。
- [x] root_cause/evidence_summaries由关联concept的已审核MisconceptionPattern/ApprovedEvidence生成；compiler evidence仅固定脱敏说明，不读取compiler源码回显；review_reason使用稳定reason code。缺已审核文本用稳定“证据不足”说明，不伪造课程结论。
- [x] 在实际SQL query hook记录仅表名/列名，禁止analytics访问memories/conversations正文；把私人sentinel种入提交、诊断正文和现有记忆，通过API/log/audit验证零回显。
- [x] 内存开发模式从现有提交/诊断/知识仓库动态投影，不能只注入永远空的repository；仍沿用原Task8内存repo测试。
- [x] GREEN：PG数据源测试、Task8全部领域测试通过，提交 `feat: derive teacher analytics from authoritative SQL facts`。

### G3：最小0007和教师复核原子事务

**Files:** Modify `backend/app/analytics/persistence.py`、`service.py`、`backend/app/persistence/models.py`、`repositories.py`；Create `backend/migrations/versions/0007_teacher_analytics_reviews.py`；Create `backend/tests/integration/test_wave3_reviews_postgres.py`。

**Interfaces:** SQL仓库补齐get_review/save_review/transaction/review_claim；原服务函数签名和TeacherDiagnosisReviewDTO不变。SqlRepositories新增analytics字段，SQL analytics与audit使用同一memory_uow。

- [x] 先写PG RED：同决定/trim理由重放等于首次结果；改决定或理由409；两teacher两repository同时复核只有一个权威结果/成功审计；审计失败无review，review失败无audit；权限撤销/未知统一404；真实memory状态/版本/行数完全不变。
- [x] TeacherDiagnosisReviewRow最小字段：diagnosis_id（PK）、course_id、reviewer_user_id、decision、reason、reviewed_at。复合FK(diagnosis_id,course_id)→diagnoses(id,course_id)，reviewer→users；decision check；reason非空且≤2000；必要course索引。无需复制候选/学生数据。
- [x] 0007 revision=`0007_teacher_analytics_reviews`，down_revision=`0006_token_revocations`，只有该表/约束/索引；downgrade仅移除新表。
- [x] review_claim进入共享UOW并先锁diagnosis父行（保持Task10 FOR NO KEY UPDATE锁序）；锁内重新读候选及当前教师权限、再检查已有review。相同重放不新增审计，不同409；最后事务唯一约束仍保护跨实例。
- [x] save_review在当前Session flush；SqlAuditLog.record在同Session flush；外层唯一commit。禁止各repository私有session独立commit或“补偿删除”冒充原子性。

```python
def test_review_and_audit_use_one_commit_boundary(wave3_pg):
    seeded = wave3_pg.seed_review_candidate()
    wave3_pg.fail_audit_flush()
    response = wave3_pg.post_review(seeded.diagnosis_id, "confirmed", "PRIVATE_REASON_SENTINEL")
    assert response.status_code == 503
    assert wave3_pg.review_count(seeded.diagnosis_id) == 0
    assert wave3_pg.success_audit_count(seeded.diagnosis_id) == 0
    assert "PRIVATE_REASON_SENTINEL" not in wave3_pg.logs()
```

上述方法归wave3_support；失败注入只在审计存储flush，真实授权/复核写入保持，不替换为mock成功。

- [x] 用Barrier放在请求开始前，Future.result(timeout=10)、SQL lock_timeout限制挂起；同请求和不同请求竞争分别执行，不能在持锁事务内等待双writer Barrier。
- [x] PG GREEN后，运行Task10删除/迟到写入/父子锁回归，检查只有一个head，提交 `feat: persist atomic teacher diagnosis reviews`。

### G4：组合根、三个Router和全部运行时契约

**Files:** Modify `backend/app/main.py`、`backend/app/api/teacher.py`、`backend/app/analytics/schemas.py`；按已发现漂移最小修改 `backend/app/api/auth.py`、`courses.py`、`knowledge.py`、`submissions.py`、`diagnostics.py`；Modify `backend/tests/contracts/test_openapi_runtime.py`、`test_wave3_openapi.py`；Create `backend/tests/integration/test_wave3_gate.py`、`backend/tests/contracts/test_wave3_runtime_openapi.py`。

**Interfaces:** create_app新增可选teacher_analytics_repository/service注入；application.state保留全部既有对象，新增teacher_analytics_service/repository；公开paths/operationId来自共享契约。

- [x] RED：create_app的runtime必须含3教师接口和logout；DATABASE_URL模式为SQL，不配置时仅development/test可用内存；analytics/audit共享UOW；Task7 source_context、TokenRevocations、CORS均存在。
- [x] 全量共享/runtime比较先失败：paths/method精确集合、operationId、parameters位置/required/schema、body严格字段、response状态/字段、Bearer、统一错误信封。解析$ref和path-level parameters；只忽略生成title/description和等价nullable表示，不忽略required、enum、oneOf、minimum或额外字段。
- [x] 原Task7 isolated memories router的“无teacher路径”断言仍保留（该测试只装memory router）；Wave3旧测试名可以改为集成语义并增加真实runtime断言，冻结状态/字段/阈值断言全部保留。
- [x] 最小补齐FastAPI声明与response_model字段元数据；教师analytics使用status discriminated union；readOnly/writeOnly按shared对齐。旧接口用共享operationId、隐藏手动Authorization参数、声明bearerAuth和稳定错误模型。不能把application.openapi直接替换成静态shared文件来隐藏实际漂移。
- [x] health明确operation_id=getHealth；不改既有业务请求语义或冻结接口名称。未预料的契约矛盾不能通过放宽比较器解决。
- [x] 真实HTTP合同探针验证错误/边界响应，与声明比较共同成立；CORS本地预检、未列源拒绝、禁止*、非开发默认空均测试。
- [x] GREEN后提交 `fix: wire Wave 3 services and align runtime API contracts`。

### G5：54组向量真正进入Router/SQL/PostgreSQL

**Files:** Create `backend/tests/integration/test_wave3_analytics_vectors_postgres.py`；Modify wave3_support；保留Task10 analytics_assertions.py、analytics_vectors.yaml及原结构测试不变。

**Interfaces:** 每vector全部facts→合成关系行→真实Router query filters→assert_analytics，param ID为vector_id。

- [x] 先写54参数化RED；fixture将(subject_key,course_id)映射为合成学生，diagnosis_id/submission/concept/exercise完整存入真实PG；包括异课程和excluded_by标记的全部反例。
- [x] 只在完成fixture事实解析之后丢弃非数据库元数据excluded_by，绝不根据它预过滤；created_at对应DiagnosisRow.created_at，independently_repaired通过G2真实理解/执行证据行表达。

```python
@pytest.mark.parametrize("vector", vectors(), ids=lambda v: v["vector_id"])
def test_vector_through_router_sql_postgres(wave3_pg, vector):
    wave3_pg.seed_vector_facts(vector["facts"])
    filters = {k: v for k, v in vector["expected_response"]["filters"].items() if v is not None}
    response = wave3_pg.get_analytics("course-a", filters=filters)
    assert response.status_code == 200
    assert_analytics(vector, response.json())
```

- [x] 除原assert_analytics外，比较实际payload与手算expected完整字段值；不能仅检status或用expected_response当API结果。
- [x] 额外测试去掉任一有效过滤后四人反例变五人；SQL正常保留所有反例，start相等包含/end相等排除，group独立阈值，多概念/重复diagnosis不倍增。
- [x] JUnit记录54条唯一node ID、PG server/version、请求路径与脱敏响应证据；不是expected DTO schema验证数。
- [x] GREEN：54/54 executed/passed、0skip，提交 `test: execute anonymity vectors through SQL teacher routes`。

### G6：前端真实连接与服务端logout

**Files:** Modify `frontend/src/api/client.ts`、`src/App.tsx`、`src/auth/session.ts`（仅必要时）、`src/teacher/CourseDashboard.tsx`、`ReviewQueue.tsx`；Create `frontend/tests/wave3-integration.test.tsx`；Modify `frontend/tests/all.test.ts`。

**Interfaces:** ApiClient.logout(): Promise<void>消费POST/auth/logout；仍只消费OpenAPI DTO。前端页面布局/视觉保留。

- [x] RED：点击退出调用旧token一次、204后清会话；延迟响应重复点击不重复；503显示request ID和重试，不显示“服务端已失效”；401已失效可清本地会话。
- [x] 最小实现logout busy锁，调用时保留accessToken至请求结束；成功/已失效才清session。未知错误保留可重试状态，不能用finally无条件宣称撤销成功。
- [x] RED：日期end转次日零时、相邻窗口[start-duration,start)；UTC转换、边界24:00和夏令时日期使用日历天；取消旧请求后不覆盖新课程/队列。
- [x] 如真实组合发现loading/empty/404/409/422/503缺口，先补组件RED再最小修；已处理复核从待处理UI去除或真实刷新队列，保存原409刷新操作。
- [x] 无私人入口/不调用me/memories等教师断言保留；真实401不会靠改localStorage角色获得权限。
- [x] `npm test`覆盖旧30项及新增项，`npm run build`、显式E2E/config类型检查通过，提交 `fix: connect UI logout and teacher review to Gate APIs`。

### G7：独立迁移库完整往返和安全语义

**Files:** Create `backend/tests/integration/test_wave3_migrations_postgres.py`；复用G0的 `infra/compose/docker-compose.wave3-gate.yml` 和 `backend/tests/integration/wave3_environment.py`（受信初始化器，不含生产入口）。

**Interfaces:** Gate override只调整loopback端口、测试项目资源和来源白名单；初始化器拒绝非Gate标签容器/非wave3_数据库，产出PG/pgvector版本、revision链和迁移前后行数证据。

- [x] 核对G0独立项目/测试数据库和实际vector安装，不读日常学生数据；专用迁移库查询extversion。按实际image digest和版本记录，不引用历史值当本次证据。
- [x] 避免Alembic配置被进程DATABASE_URL覆盖；迁移进程明确设置wave3_migration，运行：

```powershell
& $gatePython -B -m alembic heads
& $gatePython -B -m alembic upgrade head
& $gatePython -B -m alembic current
& $gatePython -B -m alembic check
& $gatePython -B -m alembic downgrade 0006_token_revocations
& $gatePython -B -m alembic upgrade head
& $gatePython -B -m alembic downgrade 0005_memories_audit
& $gatePython -B -m alembic upgrade head
```

- [x] 从空库upgrade→0007单head；0007降到0006只丢教师复核，token状态保留；降到0005会丢token撤销，先证明旧token失效不能凭空维持，再模拟AUTH_TOKEN_SECRET轮换后旧token401。重升0006不恢复擦除文本。
- [x] 种入deleted/deletion_pending历史链、live链、非目标诊断/课程/提交；比较历史proposal/diagnosis/evidence/hint/explanation正文擦除，live及非目标行保留；不用日志输出正文。
- [x] 验证token digest长度/主键、review唯一/复合FK/check、非法跨课程review被数据库拒绝；review/audit失败事务回滚。
- [x] full downgrade base仅在另一个空的可丢弃迁移测试schema/库执行，不删除已有非目标数据来“证明保留”。保留Task7既有往返回归的独立库。
- [x] 文档：部署前备份、停旧写入实例、迁移后全实例切换；擦除不可逆，downgrade不能恢复；丢revocation表时重开认证前轮换密钥。本文不授权生产部署。
- [x] GREEN提交 `test: verify Wave 3 PostgreSQL migrations and rollback semantics`。

### G8：真实前后端/PG/Runner浏览器与全部Runner验证

**Files:** Create `backend/tests/integration/wave3_browser_fixture.py`；Create `frontend/e2e/wave3-real.spec.ts`；Modify两个playwright配置（保留全部原spec）；Create `runner/tests/test_wave3_isolated_topology.py`；必要的测试镜像构建文件仅在infra/compose测试目录。

**Interfaces:** Browser fixture=create_app实际组合根+wave3_browser SQL+Mock Provider+真实RunnerClient；真实UI用VITE_API_BASE_URL=http://127.0.0.1:8198，CORS显式允许5199。

- [x] 先RED验证真实浏览器启动/登录/SQL教师API，不使用page.route拦截。新fixture的fail/delay控制仅test进程可启用，不能成为生产debug API。
- [x] 默认命令实际运行原learning-loop 2场景、security-request 14场景；Gate命令实际运行原security-ui.gate 7场景与新增real-ui场景。每项目独立计数，原projection结果明确标记网络模拟。
- [x] 新real-ui覆盖学生/教师真实登录；直接角色URL/私有资源404；4人全抑制和5人边界；教师无私人入口；复核后SQL结果/审计及队列刷新；学生提交→真实编译失败→诊断→提示→修复重提→理解验证→建议本人确认→纠正/拒绝/删除；旧token退出后401；重复点击只有一次敏感HTTP请求及一次SQL结果。
- [x] 真实错误404/409/422/503及request ID由API产生；403/404投影一致保持原7测试，真实后端资源仍统一404。存储不可用/延迟测试在隔离fixture端口注入，核心授权/删除边界不能Mock。
- [x] 390×844手机关键按钮可达，无document/table横向溢出；桌面1440×1000；产出脱敏截图/trace和请求计数，不保存访问令牌。
- [x] 使用cangjie-coding批量查询本次实际用到的match/无限循环/文件或网络攻击API；知识缺口在真实隔离容器最小验证，不在宿主猜测/执行。
- [x] 真实sandbox内读取cjc/cjpm -v并实际编译/运行；固定image digest、network none/read-only/user10001/cap-drop/no-new-privileges/CPU/memory/PID/tmpfs。控制面只接受结构化请求，不允许用户覆盖这些参数。
- [x] Runner原worker/executor/parser/cli/protocol测试在含1.2.0工具链的测试sandbox运行；controller/docker_engine测试在受信测试控制面环境运行。测试依赖沿用现有pytest/docker，不加生产依赖；不得把Docker socket挂给不可信worker。测试源码可在构建时COPY，不给学生job挂宿主项目目录。
- [x] Task10容器6项在真实镜像执行；真实controller→新sandbox的HTTP闭环至少验证成功、编译失败、无限循环、输出限制和任务清理。Windows应用控制/符号链接skip不能替代Linux隔离验证。
- [x] GREEN提交 `test: verify real Wave 3 browser and isolated runner flows`。

### G9：164条攻击逐条可追溯映射

**Files:** Create `data/evaluation/security_execution_manifest.json`、`data/evaluation/map_security_execution.py`；Create `backend/tests/security/test_execution_manifest.py`；必要时Create `backend/tests/security/test_wave3_case_execution.py`；保留security_cases.yaml/cases.schema.json/protocol内容。

**Interfaces:** 不给严格case schema增加未知字段；独立manifest以case_id连接原164案例，记录case哈希、确切测试参数/node ID/操作、映射依据、敏感分级、status、运行时间、命令退出码、证据文件SHA-256和执行边界。

- [x] RED校验manifest恰好164个唯一ID，缺ID/重复/非法status/不存在证据/把collected当pass均失败。
- [x] status只允许automated_passed/automated_failed/manual_passed/manual_failed/not_executed；尚未运行初始均not_executed并写原因，无伪时间。
- [x] 小样本54条逐个映射到G5参数node；提示注入30条逐payload×channel；文件级test_reference不足时补确切case操作测试，不能整文件pass自动覆盖所有案例。
- [x] executor_abuse 8条逐条分清protocol拒绝和真实容器执行；计划没有实际网络/文件逃逸证据时不得用普通compile成功代替。
- [x] architecture_pending 5条分别核对是否有真实适配器；未实现外部缓存/向量/模型引用的条目注明边界与后续ADR/授权依赖，不能造mock服务让其通过。Critical/高敏感未执行必须有具体理由并进入Gate阻塞清单。
- [x] 每个失败加入Gate blocker；运行map_security_execution读取JUnit/浏览器报告及哈希，不根据日志字符串“passed”猜案例结果。映射工具不改变教学draft/verified标记。
- [x] 对原数据重算上述三哈希与evaluate结构；recompute用既有测试中的合成观察验证逻辑，不填真实教学observations/results。
- [x] 提交 `test: record traceable execution of planned security cases`。

### G10：全量回归、全新只读审查和最终提交

**Files:** 全部Gate修改与新增文件；更新wave3-integration-handoff、command-results、manifest、本文完成checkbox。

**Interfaces:** 产出Gate结论、完整文件清单、五来源追溯、实际命令和独立审查报告；不产生main合并/远端交付。

- [x] 按下一节矩阵执行全部相关测试，任何变更后重跑受影响范围；最后完整后端、前端、浏览器、Runner、PG迁移回归不能以早期次数替代。
- [ ] 使用requesting-code-review；全新只读上下文审查，传设计、用户Gate要求、baseline→Gate diff、完整命令证据与已知适配器缺口。审查者不改代码、不接触真实数据/模型、不停止服务。
- [ ] Critical/Important安全新发现立即停止产品修改并报告；用户授权修复后先RED再最小修复和回归。普通契约/环境/既定SQL缺口按systematic-debugging持续处理，不放宽断言。
- [ ] 使用verification-before-completion核对最终实际结果、0未解决冲突、来源-x、head/契约、manifest覆盖、无Critical/Important；分类结论见第6节。
- [ ] 最终交接含用户要求的20项：结论；完成/未完成；5来源；冲突；SQL/事务；ADR；API；迁移回滚；54；220；7；真实学生/教师组合；164映射；全命令；独立审查；真实数据/模型边界；全文件；风险/Wave4依赖；Gate分支/哈希/状态；禁止动作未执行声明。
- [x] 将脱敏证据摘要/哈希提交，原临时截图/日志按现有ignore保存本地并给绝对路径；不提交令牌/凭证/原文。
- [ ] 最终本地提交：`feat: integrate Wave 3 analytics UI and security gate`；`git status --short --branch`干净、`git diff --check`0、`git ls-files -u`空。其他Task worktree/main状态再次比对，不清理任何worktree，不push/PR。

## 5. 最终测试矩阵与命令

所有pytest实际调用在表中短写；执行ledger必须展开 `$gatePython`、完整cwd和独立basetemp，保留退出码/计数/实际环境。pytest结果为0但含必测环境skip时仍不能算Gate绿色。

|工作目录|完整命令主体|必验证边界|
|---|---|---|
|Gate/backend|`& $gatePython -B -m pytest tests/analytics -q -p no:cacheprovider`|原Task8 68项不删减|
|Gate/backend|`& $gatePython -B -m pytest tests/security -q -p no:cacheprovider --junitxml=security-results.xml`|原220项全部执行，新增测试另计；TASK10_RUNNER_IMAGE显式本地镜像|
|Gate/backend|`& $gatePython -B -m pytest tests/auth tests/courses tests/submissions tests/diagnostics -q -p no:cacheprovider`|身份/课程/提交/诊断；若既有conftest模块冲突按原目录拆开执行并记录，不删测试|
|Gate/backend|`& $gatePython -B -m pytest tests/memories tests/model_gateway tests/contracts tests/persistence -q -p no:cacheprovider`|生命周期/DTO/契约/结构；SQLite结构测试不计PG证据|
|Gate/backend|`& $gatePython -B -m pytest tests/integration/test_task6_postgres.py tests/integration/test_task7_postgres.py tests/integration/test_task7_deletion_recovery.py tests/integration/test_task10_security_repairs.py -q -p no:cacheprovider`|各独立TASK*_库，真实PG/并发/迟到写入/重启|
|Gate/backend|`& $gatePython -B -m pytest tests/integration/test_task6_closed_loop.py tests/integration/test_task7_closed_loop.py -q -p no:cacheprovider`|真实controller/sandbox；TASK6/7_RUNNER_ENDPOINT明确|
|Gate/backend|`& $gatePython -B -m pytest tests/integration/test_wave3_analytics_postgres.py tests/integration/test_wave3_reviews_postgres.py tests/integration/test_wave3_analytics_vectors_postgres.py tests/integration/test_wave3_migrations_postgres.py -q -p no:cacheprovider --junitxml=wave3-postgres-results.xml`|SQL、原子review、54实际Router、迁移；WAVE3_POSTGRES_URL专用|
|Gate/backend|`& $gatePython -B -m pytest tests -q -p no:cacheprovider --junitxml=backend-results.xml`|完整后端tests；runner独立在真实隔离环境运行，避免默认testpaths把worker源码跑到Windows宿主|
|Gate/frontend|`npm ci --ignore-scripts --no-audit --no-fund`|锁文件与manifest一致；不升级依赖|
|Gate/frontend|`npm test`|所有既有/新增组件，Vitest无Playwright文件|
|Gate/frontend|`npm run build`|tsc-b/Vite生产构建|
|Gate/frontend|`npx tsc --ignoreConfig --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --types node e2e/learning-loop.spec.ts e2e/security.spec.ts e2e/security-ui.gate.ts e2e/wave3-real.spec.ts playwright.config.ts playwright.gate.config.ts`|全部E2E与配置类型检查|
|Gate/frontend|`npx playwright test`|Task9 learning-loop与Task10 security.spec实际执行，不只--list|
|Gate/frontend|`npx playwright test --config playwright.gate.config.ts`|原7项实际浏览器+真实组合，分别报告|
|Gate/root|`docker compose -p knowbound-wave3-gate -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.wave3-gate.yml config --quiet`|Compose解析、端口/CORS、安全边界；另通过解析器断言不能只靠config退出0|
|测试sandbox /app|`python -B -m pytest runner/tests/test_executor.py runner/tests/test_parser.py runner/tests/test_cli.py runner/tests/test_protocol.py -q -p no:cacheprovider`|实际1.2.0、非root/无网/只读；测试镜像烘焙代码且无宿主挂载|
|受信测试controller /app|`python -B -m pytest runner/tests/test_controller.py runner/tests/test_docker_engine.py runner/tests/test_wave3_isolated_topology.py -q -p no:cacheprovider`|真实拓扑探针另计；socket仅controller|
|Gate/backend（迁移专用进程）|`& $gatePython -B -m alembic current` / `heads` / `check`，及G7 upgrade/downgrade序列|0007唯一head、模型/迁移一致、擦除/回滚约束|
|Gate/root|`& $gatePython -B data/evaluation/evaluate.py`|164+4结构与来源/hash；输出仍not_executed教学状态|
|Gate/root|`& $gatePython -B data/evaluation/map_security_execution.py --manifest data/evaluation/security_execution_manifest.json`|164完整映射、真实报告/证据哈希、未执行原因|
|Gate/root|`git diff --check` / `git ls-files -u` / `git status --short --branch`|0空白错误、无冲突、最终本地提交后干净|

## 6. 停止条件、结论与依赖

立即停止产品修改并报告：需改变角色/教师私人读取权限、降低5人阈值、让模型直接写记忆、新外部基础设施/生产依赖、冻结OpenAPI无法协调、迁移多head/意外不可逆或破坏非目标数据、Task10出现新的Critical/Important安全失败、只有skip真实PG/浏览器/Runner才能绿色、来源历史变化、发现未授权真实数据/真实模型调用。

普通语义冲突、测试环境配置和既定范围内SQL/装配缺口继续系统化调试。上述停止不等于放弃文档与可复核证据：保留当前分支/失败测试、列清问题，等待用户决策。

Gate结论：

- **通过**：用户18节全部条件同时成立；54真实Router/SQL/PG、原220安全、原7浏览器和真实组合、隔离Runner、迁移/并发均有本次执行证据，契约一致，无Critical/Important，无未验证的必需边界，最终本地提交/worktree干净。
- **条件通过**：已验证的集成边界全部通过，但有明确未实现/未验证的非生产外部适配器边界或其他未完成要求；逐条列出条件，不称完全通过。
- **未通过**：任何必须测试失败、匿名/授权/删除/迁移安全问题、Critical/Important未解、必需真实验证缺失或无理由高敏感攻击未执行。

当前派生索引是内存实现；pgvector扩展可用不能证明真实向量删除。不存在的外部缓存/模型引用服务不能用receipt宣称验证。本计划不擅自新增这些子系统；如果用户要求这些外部物理边界成为本次完全通过条件，须先新增ADR并授权具体适配器范围。正式教师gold、真实模型比较、教学试点和比赛结果属于Wave4/Task11后续授权，当前均不执行。

## 7. 计划自查与确认门槛

- [x] 用户19节任务/18节标准已映射到G0–G10及命令矩阵；真实/Mock/历史边界明确。
- [x] 五提交顺序和父关系核对；每次-x及局部验证；框架历史RED不允许掩盖新安全FAIL。
- [x] 共享冲突明确保留双方行为，禁止整文件ours/theirs；ADR0005/0006与迁移序列分开。
- [x] 迁移0007接0006，最小表、唯一结果、共享Session/audit原子事务；单向擦除/密钥轮换写清。
- [x] 54向量全facts保留，excluded_by仅元数据；54与220与7与164分开计数。
- [x] SQL事实最小化、队列来源脱敏、教师权限实时检查、前端不读数据库结构。
- [x] Vitest聚合入口、两个Playwright命令全部实际执行；projection与真实组合分开报告。
- [x] 旧迁移测试库与浏览器数据库隔离，防DATABASE_URL覆盖及降级误伤。
- [x] 停止条件不被“先补测试再修”覆盖；新增Critical/Important先报告授权。
- [x] 全新只读审查安排在全部测试后；最终只本地提交，不执行用户禁止动作。
- [x] 再次依赖自查：PG/controller准备前移G0；G2/G3局部Router与G4正式装配区分；Task9局部浏览器使用其当时配置，不引用尚未建立的project。
- [x] 用户明确确认本文，随后才开始G0及产品集成。

**确认内容：** 采用上述串行实施、五来源顺序、最小SQL/0007、共享事务、契约全量对齐和真实测试矩阵；对尚无外部适配器的边界如实列未验证，绝不默认新增基础设施或声称完全通过。确认前维持只读审计/计划范围。
