# PR #9、#10、#11 集成交接报告

日期：2026-10-22（Asia/Shanghai）。这是软件集成与合成数据验证，不是教师评测或学生试点结果。

> **Docker 恢复后的最新结果**：完整交付验证已在干净提交 `59e22c0105896d884bc60cb32661836d3f1ed453` 上通过，28 个记录命令全部成功；后端 1144 项无失败/跳过、前端 67 项、默认浏览器 16 项、Gate 浏览器 10 项、真实演示 15 步、容器内 worker/controller 31/12 项，以及 45 次真实 Runner 稳定性任务均通过。Docker/数据库/Runner 阻塞已解除。详见 [补跑交接报告](pr9-11-docker-followup.md) 与 [最终证据索引](experiments/pr9-11-docker-validation/evidence-index.json)。真实付费模型、教师评测、学生试点与公网入口仍未执行；依赖审计接口仍超时。下文首轮的失败/跳过是历史记录，不能当作当前 Docker 验证状态。


## 分支、提交和范围

- 集成分支：`codex/pr9-11-integration`，已推送到 `origin/codex/pr9-11-integration`。
- 已发布的功能代码 HEAD：`1f986fb4dbae30abf4f8543ae084d50f53da4424`。后续交接报告/证据提交不改变功能代码；最终分支 HEAD 在本次聊天最终交接中给出，也可用 `git rev-parse HEAD` 查询。
- 基线：`main` 的 `a0bc47120eb08fbab9b2ca74bc7761fe753fe3e2`。首次 fetch 成功，main 未前进；结束阶段 fetch 一次连接重置，随后推送成功。结束时再次经 GitHub connector 核实三个 PR 均 open、未合并且 HEAD 未变。
- #9：`c7906fa97f4ef9682c4af435d7f0bf6de043e4ad`。
- #10：`8ba400ce6c92f28bb96f833f199c5d35ce1a472f`。
- #11：`7bf0efce2485c1ce5de65ddcf207aa5cadcad7db`。
- 重新验证 #9 是 #10 的祖先，#10 仅多一个提交；依次以 merge 纳入，未重复 cherry-pick。合并节点为 `05bdbef`、`f857566`、`ec4d280`，源提交关系完整保留。
- 工作树：`C:/Users/lenovo/Desktop/cs competition/.worktrees/pr9-11-integration`。根工作树的 README 修改、未跟踪文档/PDF/artifacts 均未暂存、清理或覆盖。未合并 main、未修改或关闭原 PR、未强推、未删除分支或数据卷。

## 完成内容和已复现修复

1. 解决 App/ExercisePage 冲突，同时保留模型配置面板、按账号挂载的学生页面、本机草稿和理解验证布尔结果。
2. 保留真实模型 ADR `0009-live-model-providers.md`；教师入口 ADR 改为 `0011-teacher-test-access.md` 并更新全部引用，仍为“待用户确认”；ADR 0010 的已有审批状态未改变。
3. 用实际 `DeliveryMockProvider` 注入复现：development 会被保存的共享真实模型替换；production 仍会加载保存的个人 provider。现在固定 Mock 使用显式标志，启动忽略共享和个人存储；GET 如实显示 Mock 和锁定状态，共享/个人写入、探测、恢复环境和清除覆盖均返回 409，不能改变执行 provider。相关 HTTP 回归也覆盖学生访问共享设置的 404。
4. 网页配置须显式 `MODEL_SETTINGS_ENABLED=1` 且处于 development/test；live Compose 已设置。固定 Mock 和 production 永远锁定，未启用部署默认锁定。普通基础 Compose 不透传该开关；该 Compose 的网页配置保持关闭，需使用已支持的 live 覆盖，或在直接运行 API 的进程环境中启用。
5. 用跨域 OPTIONS 复现模型设置 PUT 被 CORS 拒绝；补入 PUT，保留来源白名单。
6. 用失败测试复现共享/个人保存与探测可在更换 base_url 时复用原 Key；现在仅同 provider、同端点可复用空 Key，更换端点必须明确输入。前端同时限制按钮并说明规则。
7. 用替身响应复现供应商将完整 Key 放入合法格式的请求 ID 时日志泄露；现在对包含当前 Key 的请求 ID 脱敏。错误不返回上游正文，前端构建未包含测试 Key 标记。
8. 用失败测试复现模型提示调用连续失败仍生成备用提示并推进层级；现在超时/供应商失败返回 503 `MODEL_PROVIDER_TIMEOUT` / `MODEL_PROVIDER_FAILURE`，不写提示事件，不推进层级。内容泄漏防护仍能生成明确标注的安全备用提示；这不是切换成 Mock。诊断失败仍进入待复核，理解检查失败保持无记忆资格。
9. 除 PR #11 的初始 understands=false 修正外，又复现“接受旧记忆后当前理解验证失败仍显示完成”；现在完成态必须同时满足当前理解通过，失败时清除陈旧完成标志。
10. 补充账号/课程/练习草稿分区、读取/写入/清除失败、理解失败重试等验证；修正 #10 新增模型面板后 #11 浏览器草稿和部分旧集成测试缺少接口夹具的问题。

以上行为缺陷均先观察失败测试，再做最小修复。纯静态审查结论不作为已运行真实服务的证据。独立只读审查未发现可证明的 Critical / Important 缺陷，记录见 `experiments/pr9-11-integration/review.txt`。

## 文件与契约影响

完整纳入文件见 `experiments/pr9-11-integration/files-from-baseline.txt`；本轮修复文件见 `fix-files.txt`；完整源提交与合并节点见 `integrated-commits.txt`。

- 后端：`app/main.py`、`app/model_gateway/runtime.py`、`openai_chat_completions.py`、`app/diagnostics/hints.py`、`app/api/errors.py`、`scripts/delivery_demo.py` 及相关回归测试。
- 前端：App/ExercisePage 冲突处理、教师/学生模型面板、DraftScope、student-flow、模型面板与浏览器/旧集成夹具。
- 文档：README、operations、ADR 0010 澄清、ADR 0011 唯一编号与引用、执行计划、本报告和证据。
- 数据库：无新增迁移或 schema 变更；仍为原迁移 head。未实际运行 PostgreSQL 迁移回归。
- API：纳入 #10 的六个设置 operation（总数 47）；本轮不增删 operation/schema。提示失败使用契约已有 503 ErrorResponse，补正文案说明，运行时与冻结契约逐 operation 比较通过。
- 共享配置：`.env.example` 增加默认关闭的 `MODEL_SETTINGS_ENABLED=0`；live Compose 显式设为 1。未修改端口、项目名、卷或凭据隔离；不新增依赖。`contracts/openapi.yaml` 仅进一步澄清提示失败响应描述。
- ADR：编号冲突已消除，不扩大角色、私人数据权限、模型供应商或 Runner 边界。

## 验证结果和实际命令

所有路径以本集成工作树为起点。Python 命令中的 `python` 实际为根工作树既有 `.venv/Scripts/python.exe`；未执行无参数 pytest，也未在宿主运行整个 runner/tests。

| 命令/范围 | 结果 | 证据（相对于 experiments/pr9-11-integration/） |
|---|---|---|
| `python -m pytest -c backend/pyproject.toml backend/tests --ignore=backend/tests/integration --ignore=backend/tests/contracts/test_wave3_environment.py --ignore=backend/tests/security/test_wave3_container_attacks.py -q -o junit_family=legacy --junitxml=.../backend-final.xml` | 957 通过、6 跳过；随后新增 Key 日志、实际调用 Key 归属和 HTTP 锁定用例已由最终专项覆盖，不将两次计数相加 | backend-final.txt/xml |
| `python -m pytest -c backend/pyproject.toml backend/tests/model_gateway backend/tests/diagnostics backend/tests/contracts/test_wave3_runtime_openapi.py backend/tests/test_cors.py -q --junitxml=.../targeted-final.xml` | 最终 217 通过；包括错误 Key、401/429/500、超时、无效 JSON、结构不符、Key 归属、恢复配置、Mock 锁定和 47 个 operation 契约 | targeted-final.txt/xml |
| `python -m pytest -c backend/pyproject.toml backend/tests/integration/test_app_permissions.py backend/tests/integration/test_task6_gate.py backend/tests/integration/test_task7_gate.py backend/tests/integration/test_task6_closed_loop.py backend/tests/integration/test_task7_closed_loop.py -q` | 14 通过、2 跳过；真实 Task6/7 闭环缺少专用 PostgreSQL 环境，未算通过 | integration-selected.txt |
| `npm.cmd --prefix frontend test` | 最终 67 通过，覆盖草稿隔离与失败、账号切换、理解失败重试、旧完成态覆盖、配置只读/Key 更换端点 | frontend-final.txt |
| `npm.cmd --prefix frontend run build` | TypeScript 与普通构建通过 | frontend-build.txt |
| 教师模式 `KNOWBOUND_TEACHER_TEST=1 VITE_API_BASE_URL=/api npm run build`（PowerShell 分别设置进程变量）；随后恢复普通构建 | 通过 | teacher-build.txt |
| frontend：`npx.cmd playwright test`，`TASK10_PYTHON` 指向既有 Python | 最终 16 通过；UI 的 API 替身与本地 HTTP 权限服务，非真实 SQL/Runner 闭环 | playwright-final.txt |
| frontend：`node --test tests/teacher-preview.test.mjs`、`node --test tests/draft-browser.test.mjs` | 本地代理、认证头、GET/POST、允许/拒绝 Host，以及真实 Edge 中离线编辑刷新恢复通过 | teacher-proxy-final.txt、draft-browser-final.txt |
| `python -m pytest scripts/tests -q` | 3 通过，仅命令替身；无公网隧道 | teacher-launcher.txt |
| 三种 `docker compose ... config --format json`（仅合成凭据，解析后只保存无密钥摘要） | Mock/live/教师配置全部通过：5209/8208 与 5309/8308、独立卷、无数据库/controller 发布端口、沙箱断网、教师相对 /api | compose-validation.json |
| `python -m pytest -c backend/pyproject.toml backend/tests -x -q` | 193 通过后因 `test_gate_services_are_reachable_over_loopback` 连接拒绝失败；不宣称全量通过 | backend-full-environment-block.txt |
| 初次较大非 integration 回归（尚未排除 container attacks） | 953 通过、8 跳过、1 失败：`test_concrete_container_attack[sec-executor-abuse-007]`，Docker 引擎缺失 | backend-local.txt/xml |
| Docker 状态与启动检查 | 引擎未就绪；Desktop Secrets Engine 的 socket 重命名报系统访问失败。没有重置 Desktop/WSL、删除 socket 或卷 | docker-engine.txt、environment-blockers.json |
| 前端构建产物 Key 标记检查 | 测试密钥标记未进入 JS；未向构建提供真实 Key。此检查不能证明所有任意输入的秘密均不存在 | build-secret-scan.json |
| `git diff --check`、`git ls-files -u` | 无空白错误、无未解决冲突 | 最终交接前执行 |

红灯证据：`delivery-cors-red.txt`、`key-redirect-red.txt`、`key-log-red.txt`、`provider-error-red.txt`、`frontend-settings-red.txt`、`understanding-memory-red.txt`。最初 `backend-initial.txt` 与 `playwright-default.txt` 是已中断尝试，不作最终通过证据；最终重跑记录以上表为准。

`npm ci` 成功，报告既有锁文件 5 项漏洞（4 low、1 high）；额外 registry audit 请求未完成而中断，未升级依赖，未宣称依赖审计干净。详细状态在 `npm-audit.json`。测试另有 Starlette/httpx 弃用警告，未因本任务引入新依赖。

## 两套启动方式

Mock：

```powershell
pwsh -NoProfile -File ./scripts/start-delivery.ps1
# Web http://127.0.0.1:5209；API http://127.0.0.1:8208
```

真实模型：

```powershell
./start-live-demo.cmd
# 或 pwsh -NoProfile -File ./scripts/start-live-demo.ps1
# 在本机编辑 .delivery/live-model.env 后再次运行
# Web http://127.0.0.1:5309；API http://127.0.0.1:8308
```

首次真实启动仍需有效模型名和供应商凭据；不在聊天中提供完整 Key。live 项目 `knowbound-live-demo` 与 Mock 的 `knowbound-wave4-demo` 独立生成凭据并使用不同卷/镜像。真实调用可能收费，必须具备授权和费用范围；本次未调用任何真实供应商。运行失败不会静默切换成 Mock。

本机草稿按来源、账号、课程、练习分区，是明文浏览器存储，不是密码学访问隔离。同一浏览器配置目录的使用者、扩展和同源脚本可能读取；退出不清除草稿，公用电脑应清除草稿或站点数据。更换来源/端口不能自动恢复。服务器 Key 同样是容器内明文，仅 Linux 文件权限 0600；不能承诺对主机/容器管理员隐藏。

## 首轮未完成项与后续依赖（历史记录，最新状态见补跑报告）

**首轮结论（已由上方补跑结果更新）：当时不具备合入 main 的完整验证条件。** 功能集成、修复、替身/本地验证和推送已完成；以下项目未通过，不能折算为通过：

1. 恢复 Docker Desktop Linux 引擎后，执行 Mock 的冷启动、15 步真实编译纠错与记忆流程、真实 SQL 探针；当前只完成接口替身浏览器学习闭环。
2. 使用仓库现有专用测试环境重跑 PostgreSQL 迁移、权限/删除恢复、Task6/7 真实闭环、gate 浏览器、隔离容器攻击与 Runner 测试。可使用现有 `scripts/verify-delivery.ps1 -Python '<既有 Python 绝对路径>' -EvidenceDirectory '<新目录>'`；注意专用环境检查与旧卷保护，不运行宿主 runner/tests 全目录。
3. 真实 DeepSeek/千问调用缺少本次明确授权、凭据与费用范围，未执行。传输/失败/切换/隔离均使用 HTTP 替身，不据此宣称真实供应商已验证。
4. 公网教师入口仍需用户确认 ADR 0011 和具体邮箱；本任务未启动隧道、邀请教师或改白名单。此项不阻塞本地集成，但不能宣称公网已验收。
5. 既有 npm 锁文件漏洞尚未完成细项审计；需在独立授权范围内处理，不能擅自升级依赖。

没有开展教师评测或学生试点，也没有把合成数据和目标成效写成真实结果。
