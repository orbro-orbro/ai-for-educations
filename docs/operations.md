# Task 11 本地运行与复核

## 环境和版本

启动依赖 PowerShell 7、Docker Desktop Linux 引擎和首次下载网络。构建不依赖宿主 venv/node_modules：API/controller 使用摘要锁定 Python 3.12 基础镜像，Web 使用摘要锁定 Node 22，PostgreSQL 使用 pgvector/pgvector 摘要，仓颉 SDK 固定 1.2.0 STS cjnative。Python requirements.lock 锁定原已有 Linux 3.12 依赖闭包及官方 wheel SHA256，安装带 `--require-hashes --no-deps --only-binary=:all:`，前端 `npm ci` 使用既有 lock。没有新增生产依赖或升级要求。

初次实测宿主 Docker 29.8.1、Compose 5.5.1、Python 3.14.6、Node 24.15.0、npm 11.12.1；容器 Python 3.12.11、Node 22.23.3、npm 10.9.9、PostgreSQL 17.11、cjc/cjpm 1.2.0。数据库镜像提供 vector 0.8.7，回归库启用该扩展；当前演示库未启用也未写入向量。最终完整版本以 `runtime-versions-health-*/output.log` 的实际输出为准，不能拿宿主版本替代容器版本。

## 启动、停止与配置

```powershell
pwsh -NoProfile -File ./scripts/start-delivery.ps1
pwsh -NoProfile -File ./scripts/start-delivery.ps1 -NoBuild
pwsh -NoProfile -File ./scripts/start-delivery.ps1 -Action Status
pwsh -NoProfile -File ./scripts/start-delivery.ps1 -Action Stop
```

正常入口 Web 5209、API 8208，均 loopback。项目 `knowbound-wave4-demo`，PostgreSQL 和 controller 仅内部网络，sandbox 无网络；API/Web/controller/PostgreSQL 都有健康检查。拒绝同名前缀的非本任务容器、数据卷或网络，拒绝冲突的继承环境，不覆盖既有凭据。`.delivery/demo.env` 首次生成随机密码和 JWT 密钥；普通 `.env.example` 的开发默认值不用于此入口。`RUNNER_TIMEOUT_SECONDS=15` 是 API 到 controller 的 HTTP 等待预算，任务自身截止仍由 Runner 请求与硬上限控制，不等于每任务运行 15 秒。

`-FreshData` 构建后强制重建本项目容器，选择新 UUID 合成 PostgreSQL 卷，并将选择记录在忽略文件 `.delivery/active-volume.yml`。旧卷保留，可用于追查失败，不删除日常/Wave 3/旧演示数据。后续普通启动继续使用该活动卷。此选项仅用于合成演示和冷启动验收，不能当真实数据清理操作。

## 模型配置（网页，教师与学生）

教师端「课程诊断台」的「模型接入」可在运行时切换 deepseek / qwen / 任意 OpenAI 兼容地址 / Mock / 停用，填写模型名、Base URL 与 Key，先「测试连接」再「保存并启用」，下一次诊断请求即生效。Key 只写入 API 容器内的 `MODEL_SETTINGS_PATH`（默认 `/var/lib/knowbound/model-settings.json`，权限 0600，原子替换），不回传浏览器、不写日志与审计；界面只显示后四位。同一接入方式下留空 Key 沿用已保存的值；切换接入方式必须重新填写。

学生端「我的模型接入」默认沿用教师配置，也可填入自己的 Key，只影响自己的诊断与提示：写入同一文件的 `users.<user_id>` 分区，其他学生和教师都读不到，也不改动共享配置。学生只能看到自己 Key 的后四位；继承教师配置时不显示教师的 Key 提示。保存后再次点「改用老师的配置」即删除个人分区、回到共享配置。接口为 `GET/PUT /model-settings` 与 `POST /model-settings/probe`，教师写该路径返回 `422`，共享配置只有 `/teacher/model-settings` 一个写入口。

停止/启动容器保留该文件，重建容器、重跑构建或 `-FreshData` 后失效，需要重新填写或改用 `.delivery/live-model.env`。`APP_ENV=production` 时读取仍可用，写入与测试返回 `409 MODEL_CONFIGURATION_MANAGED`，学生的个人配置同样只读。首次启动依旧要求 env 中存在可用 provider（live 入口 fail-fast，ADR 0009 未变）；合成 Mock 交付入口不会被已保存的真实模型配置覆盖。页面顶部横幅的模型标签来自构建时 `MODEL_LABEL`，运行时不随之更新，冲突时面板会给出提示，以面板为准。

个人配置在进程内缓存，按用户失效；当前部署为单 API 进程，多进程或多副本部署需要改为共享存储后再启用该能力。文件格式为 `{"version": 2, "shared": {...}, "users": {...}}`，版本 1 的扁平文件仍按共享配置读取，无需手工迁移。

## 初始化、迁移、备份和回滚

API 启动依次执行 Alembic upgrade head、受限合成种子、显式 demo 工厂。种子只接受 development 的内部 postgres:5432/wave4_demo，或 test 的 loopback:55440/wave4_browser；拒绝生产和其他库，重复执行保留密码、提交与学习事实。只预置合成账号/课程/练习/批准知识，不预置诊断、执行成功或自主修复行。

仍只有迁移 head `0007_teacher_analytics_reviews`，Task 11 没有新增迁移或数据库架构。回归数据库 task7 保持其历史 fixture 所需迁移目标；迁移专库用随机独立 schema 验证空库 upgrade、单 head、check、降 base 再升级、0006/0005 回滚和隐私文本不复原，均不触碰演示/日常库。

备份先确认容器和卷的 Task 11 标签，停止本项目 API 写入，在忽略的 `.delivery/backups/` 使用 `docker exec knowbound-wave4-demo-postgres-1 pg_dump -U knowbound -d wave4_demo -Fc` 保存合成数据库备份；不得把输出或密码加入比赛公开包。恢复应到新合成卷后核对迁移版本与角色权限，再恢复 API。旧证据和旧卷继续保留。真实数据备份的加密、保留期、访问和删除治理需单独授权。

回滚应用优先恢复已验证镜像，先备份再评估兼容性，不在日常库试跑 downgrade。0007→0006 删除审核表，0006→0005 移除 token 撤销能力；后者必须更换 JWT 签名密钥并强制重新登录，不能把旧 key 继续投入使用。隐私清理不因回滚恢复正文；测试证明该条件，但不代表任意历史备份可安全恢复。比赛入口没有自动回滚或删除命令。

JWT 密钥轮换：停止本项目 API，安全更新 `.delivery/demo.env` 中 `AUTH_TOKEN_SECRET` 为新高熵密钥，重建 API，重新登录并验证旧 token 401。不要在日志、命令行参数、截图或报告中打印密钥。演示账号密码变更不会由重复 seed 自动覆盖，需显式授权的账号维护流程。

## 故障恢复与日志

|现象|检查与恢复|
|---|---|
|Docker pipe 不存在|启动本机已有 Docker Desktop，等待 Linux 引擎可用，再用新证据目录重跑；不能把未执行写成通过|
|端口占用/标签冲突|查看占用与标签，保留现场；仅处理已确认的本任务资源，不停止日常服务|
|API unhealthy|查看本项目 API 日志中的迁移/种子错误，核对活动卷、配置与课程；不打印完整环境或 Compose config|
|依赖下载失败|保留日志，恢复网络后按同一锁重试；不改成无版本或无 hash 安装|
|Runner unavailable/timeout|查内部 controller 健康、固定镜像身份、Docker 资源、原始诊断与残留；所有源码仍只在隔离容器执行|
|新修复无法关联|保留真实执行结果，点击关联重试；不直接插入 diagnosis_attempts 或统计行|
|记忆删除 pending|按本人删除凭证重试，保持不可检索，再做相同查询反查；不得凭 receipt 字段宣称外部物理擦除|
|重启后查询缺少已接受记忆|SQL 仍为权威，当前索引为内存且未实现持久重建；记录限制，不补建外部适配器|
|pytest 临时目录权限错误|使用全新证据目录及脚本指定 basetemp，禁用共享 pytest cache；不删除旧失败目录|

业务审计记录事件、主体/课程/目标元数据、结果、原因和服务端 request ID，不记录私人正文、模型原始提示或凭据。只对本项目查日志；公开材料只使用最小合成证据，不能导出完整数据库或 token。默认浏览器 trace/video 关闭，截图在登录后生成。

## 最终验证与证据

在干净已提交工作树、新 PowerShell 进程运行：

```powershell
pwsh -NoProfile -File ./scripts/verify-delivery.ps1 -Python 'C:/path/to/existing/venv/Scripts/python.exe' -EvidenceDirectory 'C:/path/to/new/task11-final-evidence'
```

测试 Python 需已具备项目测试依赖，前端需已有 Node/npm/Edge。脚本绝不把 worker 测试放到宿主；构建测试镜像时只复制现有纯 Python pytest 工具，无新增下载。回归项目使用新的带任务标签网络/卷，保留早期测试卷；六库白名单由初始化器检查。不要设置 DATABASE_URL 盖过独立迁移配置。

脚本逐条记录以下真实命令类别；每条完整参数、cwd、UTC 起止、退出码、HEAD、工作树状态和输出 hash 均在同名目录 command.json 中，实际结果索引由成功执行后生成。任一步失败不生成成功总索引：

|类别|验收内容|
|---|---|
|demo-cold-build-start / restart / runtime|锁定构建、新空卷、幂等重启、健康和容器版本|
|frontend-lock-install|npm ci，既有锁安装|
|delivery-browser / delivery-readonly-sql|15 步真实浏览器彩排与只读 PostgreSQL 权威核对|
|test-compose / services / environment|独立项目启动、六库初始化、迁移目标|
|backend-full / runtime-openapi|显式 tests 全目录、无 skip，单 head 与回滚、原安全节点/54 SQL 向量、41 operation 运行时契约|
|frontend-components / types-build|组件、类型检查和生产构建|
|default-browser / gate-browser / gate-readonly-sql|原默认 16、Gate 10 和 Gate SQL 探针|
|runner-test-tools / test-build / worker / controller|当前源码烘焙加固测试镜像，原 worker 31/controller 12|
|runner-topology-and-stability|原 2 秒拓扑 4 项及 45 次有限实验，资源与实时事件清理|
|evaluation / historical-manifest / task11-manifest|数据结构、原历史清单不改写、最终 164 条实际逐节点映射及 raw/LF hash|
|git checks / evidence-index|diff 格式、无冲突、干净 HEAD、全命令退出和报告 hash 一致|

开发 `-Candidate` 结果明确标候选。最终源码提交后必须全量重跑到授权外置目录；此后任何源码修改都会使上一轮证据失效。最终真实结果及完整提交号在 `evidence-index.json` 和外置交接记录中。历史失败记录保存在 Task 11 忽略账本中，历史 Wave 3 文件保持原样。
