# PR 9–11：Docker 恢复后补跑交接

日期：2026-10-22，Asia/Shanghai。仅使用合成账号/数据和确定性模型，不是教师评测或学生试点。

## 完成与分支

- 分支仍为 `codex/pr9-11-integration`。最终完整验证对应干净提交 `59e22c0105896d884bc60cb32661836d3f1ed453`；本报告和证据归档的后续提交仅修改文档/证据，最终推送 HEAD 在聊天交接中给出。
- 本轮只修正 `frontend/e2e/security-ui.gate.ts` 的测试夹具：补齐 #10 新增的共享/个人模型设置 GET 响应。此前两项旧错误页面测试把模型面板的 404 当作课程错误，实际断言读错区域；先观察 8 通过/2 失败，再补夹具，10 项全部通过。未放宽原隐私断言，未把测试夹具缺失描述为已复现的生产权限漏洞。
- 生产代码、数据库、API、环境示例、Compose 和 ADR 均无新增变更。此前集成的三个 PR HEAD、合并关系和所有修复见主交接报告，均保持不变。
- 未合并 main，未改动/关闭原 PR，未强推，未删除分支或数据卷。结束阶段只读核对远端 main 仍为 `a0bc47120eb08fbab9b2ca74bc7761fe753fe3e2`。

## 实际执行

在独立工作树运行：

```powershell
$env:npm_config_offline='true'
$env:npm_config_audit='false'
$env:npm_config_fetch_retries='0'
$env:npm_config_fetch_timeout='20000'
& 'C:/Users/lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe' -NoProfile -File scripts/verify-delivery.ps1 -Python 'C:/Users/lenovo/Desktop/cs competition/.venv/Scripts/python.exe' -EvidenceDirectory 'C:/Users/lenovo/Desktop/cs competition/.worktrees/pr9-11-integration/.superpowers/pr9-11-docker-20261022-final'
```

使用本机缓存依照未修改的 package-lock.json 安装，未升级依赖。联网 npm 安装/审计曾等待超时，第一次尝试中断后保留原证据；第二次发现旧 Gate 夹具问题并保留失败记录；最终从已提交、干净的 59e22c0 完整运行，退出码 0。整个最终流程的 28 个命令、源码 HEAD、工作树状态、退出码和日志 SHA256 已由仓库脚本自动核验，`mode=final`。

专用测试凭据从带正确 Compose 所属标签的既有 wave4 工作树复制到本集成工作树的忽略目录，未打印。演示使用 `-FreshData` 选择新合成卷，全部旧卷保留；测试库仅使用 `knowbound-wave4-test` 的专用卷、55440 端口和六个 `wave4_*` 数据库。未操作日常/Wave3 数据库。

## 结果与证据

完整原始证据：`.superpowers/pr9-11-docker-20261022-final/`。已归档的关键证据：`docs/experiments/pr9-11-docker-validation/`。`evidence-index.json` 是原始全量索引，`archive-sha256.json` 校验本次归档子集；临时 pytest 工作目录留在原始证据中，未发布。局部 `.gitattributes` 仅防止 Git 转换证据换行，避免破坏原始字节哈希。

| 检查 | 最终结果 |
|---|---|
| 冷构建启动、重复启动、运行时版本和健康检查 | 通过；Docker 29.8.1、Compose v5.5.1、容器 Python 3.12.11/Node 22.23.3、PostgreSQL 17.11、cjc/cjpm 1.2.0 |
| `playwright test --config playwright.delivery.config.ts` | 真实部署的 15 步演示全部通过；没有响应拦截，真实 PostgreSQL 与每任务隔离 Runner |
| `probe-delivery.ps1` | 只读 SQL 确认编译失败到成功、唯一重试关联、提示等级 1/2、记忆接受/纠正/拒绝/删除、来源上下文清理、tombstone 和相同查询反查 |
| 专用环境 `python -B -m pytest tests -q ... --junitxml=.../backend.xml` | **1144 通过，0 失败，0 error，0 跳过**；包含真实 Task6/7 闭环、迁移、删除恢复、权限与容器攻击 |
| `pytest tests/contracts/test_wave3_runtime_openapi.py` | 49 通过，冻结契约与运行时一致，47 个 operation |
| `npm test` / `npm run build` | 67 通过，类型检查和构建通过 |
| 默认 `playwright test` | 16 通过（接口替身 UI 与本地 HTTP 权限服务） |
| `playwright test --config playwright.gate.config.ts` | 10 通过，其中包含官方 API、真实 SQL/Runner 的教师与学生流程 |
| `tests.integration.wave3_browser_sql_probe` | 权威复核 1 条、复核审计 1 条、已删除版本 2、剩余私人版本 0、拒绝提议 1、完成删除 1、撤销登录 3 |
| worker 测试：executor/parser/cli/protocol | **31 通过，全部在断网、只读、非 root、资源受限容器内** |
| controller/Docker Engine 单元测试 | **12 通过，全部在同类加固容器内** |
| 宿主可信编排：topology/stability | 5 通过，宿主只发送 JSON；**45 次真实任务全部通过，创建/销毁均 45，无残留任务容器，资源限制验证通过，无监控错误** |
| 原始安全回归与执行映射 | 220 项原回归、164 个安全用例映射、54 个官方 Router/SQL 权限测试通过；不修改教师标注状态或历史 manifest |
| 实际部署 Mock 模型设置检查 | 共享/个人保存、探测、恢复/清除覆盖全部 409；学生读取共享设置 404；CORS PUT 通过，零真实模型调用；见 deployed-mock-lock.json |
| Git 和证据完整性 | 最终验证时工作树干净，无冲突、无空白错误；28 个命令均成功，源码版本和哈希核验通过 |

稳定性耗时 p50 约 1.11s、p95 约 5.61s、最大约 5.62s；这些是本机合成任务的软件运行数据，包含预期超时场景，不是模型质量、教学成效或学生学习结果。耗时不可推广为生产 SLA。

## 启动与当前运行状态

Mock 当前运行于 `http://127.0.0.1:5209`，API 为 `http://127.0.0.1:8208`。在**本集成工作树**执行：

```powershell
pwsh -NoProfile -File ./scripts/start-delivery.ps1 -NoBuild
```

账号密码位于本工作树忽略的 `.delivery/demo.env`，不要在聊天或公开报告中粘贴。根工作树有自己的旧配置，不能把两个工作树的凭据或 active-volume 文件混用。旧卷均已保留。

真实模型仍使用独立 `start-live-demo.cmd`（或 scripts/start-live-demo.ps1）、5309/8308、`knowbound-live-demo` 和 `.delivery/live-model.env`；本轮未启动该栈或调用供应商。普通 Mock、真实模型和可选教师测试的入口设计未更改。

## 未完成事项和合入判断

**Docker、数据库、真实 Runner 和完整 Mock 学习闭环的技术验证阻塞已解除，本地软件集成验收通过。** 可以进入 main 合入评审，但本任务没有执行合并，也不把这些测试当作完整生产发布验收。

仍未验证：

1. **依赖审计**：此前 npm ci 报告的 5 项漏洞（含 1 high）仍待核实。此次 npm audit 与直接查询 npm 官方 bulk advisories 接口均在有界等待后超时，结果已记录；未擅自升级依赖或宣称审计干净。若依赖审计是合入门禁，此项仍阻塞最终放行，应在可访问官方审计接口的环境复核。
2. **真实付费模型**：没有本次明确授权、可用凭据和费用范围，未进行 DeepSeek/千问实际调用；共享/个人切换及错误路径已有替身测试，不能据此宣称供应商验收通过。这不阻塞本地 Mock 验收。
3. **公网教师测试**：未启用隧道、未邀请教师、未修改邮箱白名单；ADR 0011 仍待确认。本地代理/访问保护的既有验证保留。
4. **教学与外部存储**：教师 gold 标注、真实模型对比、学生试点均未执行；外部持久向量、缓存、模型引用适配器未实现，因此外部存储物理擦除未验证。数据库内的删除与相同查询反查已实际通过。

本轮修改文件仅为 Gate 测试夹具、主交接报告、本报告与补跑证据；运行时数据库/API/配置/ADR 无变更。根工作树的 README、未跟踪文档、PDF 和 artifacts 保留不动。
