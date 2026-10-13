# 知界·仓颉学伴

面向《仓颉语言设计》的概念误区诊断系统，只有学生、教师两类角色。学生通过提交、隔离编译、诊断、递进提示、重试与理解解释完成学习闭环；长期记忆须本人确认，可纠正、拒绝和删除。教师默认只能查看授权范围内的正式作业、主动分享摘要和达到五人阈值的匿名统计。

## 一键比赛演示

需要 Windows PowerShell 7、已启动的 Docker Desktop Linux 引擎，以及首次拉取锁定镜像和依赖所需的网络。应用构建使用容器内 Python 3.12 / Node 22 和仓颉 1.2.0 STS cjnative；无需宿主 Python 虚拟环境、node_modules 或宿主仓颉工具链。

在仓库根目录运行：

```powershell
pwsh -NoProfile -File ./scripts/start-delivery.ps1
```

入口：[Web](http://127.0.0.1:5209)、[API 健康检查](http://127.0.0.1:8208/health)。专用项目名 `knowbound-wave4-demo`；不公开 PostgreSQL、controller 或 Docker socket。所有长期服务健康后命令才成功，sandbox 镜像辅助容器正常退出。

账号 `demo-teacher`、`demo-student-1` 至 `demo-student-6`。首次启动自动生成数据库、JWT 和演示账号凭据，保存于 Git 忽略的 `.delivery/demo.env`，账号密码为其中的 `DEMO_PASSWORD`。不把该文件提交或附在公开材料中。重复启动保留数据；`-FreshData` 选择新的空合成数据卷并保留旧卷。停止、状态检查：

```powershell
pwsh -NoProfile -File ./scripts/start-delivery.ps1 -Action Status
pwsh -NoProfile -File ./scripts/start-delivery.ps1 -Action Stop
```

完整操作见 [15 步演示脚本](docs/demo-script.md) 和 [运维说明](docs/operations.md)。普通开发配置参考 `.env.example`；其中示例凭据不用于比赛启动或生产。模型默认禁用；演示入口显式装配确定性 Mock，不调用付费模型。

## 验证

全量验证额外需要已安装项目测试依赖的 Python、Node/npm、Microsoft Edge。Python 版本范围来自 `backend/pyproject.toml`；交付时记录实际宿主版本。入口接受已有虚拟环境的绝对路径，不升级或在线解析 Python 依赖。前端使用现有 `package-lock.json` 执行 `npm ci`。

```powershell
pwsh -NoProfile -File ./scripts/verify-delivery.ps1 -Python 'C:/path/to/existing/venv/Scripts/python.exe' -EvidenceDirectory 'C:/path/to/new/task11-evidence-directory'
```

最终验证要求干净、已提交的工作树和全新的证据目录。`-Candidate` 只用于开发候选检查，不能充当最终交付证据。脚本使用 `knowbound-wave4-test` 专用 PostgreSQL 端口 55440、controller 8209、浏览器 API 8217/8218、Web 5219，初始化六个 `wave4_*` 合成数据库。测试会重置这些专用测试数据，演示库与日常/Wave 3 库分离。证据包含完整命令、时间、退出码、源提交、JUnit、彩排结果、资源与容器事件、逐用例安全映射及 SHA256 索引。失败立即停止，旧记录保留。

宿主只运行受信测试编排和发送 JSON。worker 31 项、controller 12 项在新构建的加固 Linux 测试容器中运行；不要在宿主直接执行 `runner/tests` 全目录，也不要用无参数 `pytest`（配置含 worker 测试路径）。后端单独运行 `python -m pytest tests`，需要上述专用数据库环境；缺少环境的 skip 不构成交付通过。

## 结果与限制

软件测试、合成演示和真实教学成效分别记录于 [安全报告](docs/security-report.md)、[评测报告](docs/evaluation-report.md)、[Task 11 交接](docs/experiments/wave4-task11-handoff.md)。最终结果以实际最终提交对应的外置 `evidence-index.json` 为准，不沿用 Wave 3 的通过数。

当前所有演员、提交和统计都是合成数据，模型为明确标注的确定性 Mock。教师 gold、真实模型对照和学生试点均尚未执行。持久向量、外部缓存和模型引用适配器尚未实现，当前部署不向这类副本写入私人记忆；已安装 pgvector 不代表物理擦除已验证。有限 Runner 实验不能证明历史并发故障根因或生产稳定性。仅用于受控本地比赛演示，后续评测和生产条件见报告。
