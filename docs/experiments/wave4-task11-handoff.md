# Task 11 交接与验收入口

分支 `codex/wave4-task11-delivery`，独立工作树 `.worktrees/wave4-task11-delivery`，起点 `73bd2b4c6defdc139179c3b17c657773cfc2250a`。用户先确认计划，后以“这些都是你来决定”委托两项待决策，ADR 0007/0008 已接受。根 main 和用户材料不参与暂存；禁止合并、rebase、push、PR、分支或 worktree 删除。

## 完成范围与修改

- 锁定已有 Python 依赖与 wheel hash、基础镜像摘要、既有前端 lock；完整健康检查、固定 loopback 入口、随机演示凭据与一键构建启动。入口为 scripts/start-delivery.ps1。
- 真实合成课程/演员/练习/批准知识种子及无限次确定性 Mock；API/SQL/Runner 为真实适配器。frontend/e2e/delivery-real.spec.ts 完成 15 步，backend/scripts/delivery_probe.py 以只读事务核对权威状态。
- 采用 ADR 0007 服务端随机请求编号，忽略所有客户端关联文本，保留资源创建 provenance；原安全案例操作不删除，Task 11 独立实际映射关闭政策条件。
- ADR 0008 新增显式 attempts API，复用原检查服务和现有 SQL；前端修复重试关联及完成学习后新一轮诊断。无自动写入记忆或伪造 repair 行。
- 专用 knowbound-wave4-test 项目、六库、端口、带标签网络/卷和目标白名单；历史 Wave 3 默认选择保留。scripts/verify-delivery.ps1 串行执行完整矩阵，记录器与 manifest/index 拒绝无证据的通过声明。
- 有限 Runner 实验五场景、三轮、并发1/2，共45次；实时事件与资源观测、零残留核对，原2秒拓扑断言不放宽。worker31/controller12 在当前源码烘焙的加固测试镜像中运行。
- README、demo-script、operations、security-report、evaluation-report 与本交接说明区分软件、合成和真实教学结果。

全部修改清单可用 `git diff --name-status 73bd2b4c6defdc139179c3b17c657773cfc2250a HEAD` 复核；只涉及本任务文件。高冲突影响：Compose、.env.example、根 ignore、构建配置、OpenAPI 及 Task6 fragment 已集中协调。前端仍只依赖 OpenAPI DTO。

## 数据库 / API / 配置影响

无新迁移、表或角色；唯一迁移 head 仍0007_teacher_analytics_reviews。新增合成 demo 库 wave4_demo、独立回归六库 wave4_task6/task7/task10/router/migration/browser；不会重用日常或 Wave3 数据库。测试可重置其专用数据；旧合成卷与历史失败证据保留。

OpenAPI 从40 operation增加至41，新增 POST /diagnoses/{diagnosis_id}/attempts，仅 submission_id，204；现有所有权、当前课程关系、课程/练习一致和已执行检查保持。公开 HTTP X-Request-ID 改为服务端32hex，当前 error/header/audit一致；数据库 schema不变。

演示项目 knowbound-wave4-demo：Web5209/API8208；回归 PG55440/controller8209/Web5219/fixtureAPI8217/8218。演示 PG/controller不公开；所有源码只在无网络一次性沙箱执行。凭据在忽略的 .delivery/demo.env，MODEL_PROVIDER disabled，演示工厂显式注入 Mock；不使用真实凭据或付费服务。

## 验证、失败保留和最终判据

统一入口：

```powershell
pwsh -NoProfile -File ./scripts/verify-delivery.ps1 -Python 'C:/Users/lenovo/Desktop/cs competition/.venv/Scripts/python.exe' -EvidenceDirectory '<全新授权外置目录>'
```

每条真实命令、cwd、UTC、退出码、HEAD、工作树状态、日志/报告hash存在同名目录command.json。全部通过后才生成evidence-index.json，内含最终完整提交号、实际通过数、原220安全节点包含证明、164逐案例结果、54SQL向量、45Runner结果与全文件hash。浏览器15步计时、只读SQL、运行时版本和截图各有独立证据。候选模式明确标candidate，不能替代实际最终HEAD的完整重跑。最终还须一个新的只读复核Agent；其结论及最后分支/HEAD/clean状态写入同一外置交接，不为填入自身hash再修改源文件。

开发证据在忽略的 .superpowers/sdd/2026-10-12-wave4-task11-delivery/。已保留环境/关联ID/attempts/启动/种子的RED→GREEN；Gate首轮9/1后10通过；彩排首次错误提示文字失败后15步通过；全后端首次988通过、旧契约1失败、临时目录31错误；事件事后截断导致实验观测失败后实时采集45/45通过；恢复会话Docker未运行、静默命令日志缺失及网络迁移失败均保留，没有算成通过。拒绝建议后仍沿用上一诊断的页面缺陷也已先复现再修复，组件43项通过；候选matrix-4读到修复前的新增失败测试，未完成完整矩阵，不作最终依据。最终结果由实际索引确认，不沿用历史928或任何未执行数字。

## 未完成条件、风险与下一任务依赖

### 最终 Gate I-1 修复：资源来源请求编号

2026-10-14 独立 Gate 发现提交和执行结果读取将正文 request_id 替换为当前读取请求编号，与 ADR 0007 不一致。修复后两类 DTO 均返回持久化资源的创建/执行来源编号；响应头、当前错误和当前审计继续使用本次服务端编号。没有数据库迁移、权限、OpenAPI 结构、配置或依赖变更。

回归覆盖学生本人和授权教师分别连续读取两类资源，核对来源编号保持不变、每次响应头生成不同的服务端编号、客户端标记不回显且保存值不被修改。修复前五项断言实际失败；修复及完整交付验证的命令、JUnit、退出码和哈希保存在新的外置证据目录，旧 Head 的通过记录不能代替修复提交的最终验证。此次修复不改变下述未验证条件。

WG-CORRELATION-POLICY：已决策与实现，只有最终008实际证据通过才关闭。WG-EXTERNAL-ERASURE：仍保留，当前部署未写入持久向量、Redis/其他缓存或外部模型引用，内存索引清理与SQL清理不证明不存在适配器的物理擦除；pgvector镜像/扩展不等于向量适配器。检索索引重启持久重建尚未实现。

Runner限定工作负载可以报告实际结果；历史并发编译失败根因和生产负载稳定性仍未证实。保留失败诊断，不称历史故障已修复。controller需可信Docker socket，生产隔离/网络/镜像治理仍须专门验收。

教师gold评测、真实模型对照、学生试点均尚未执行。后续需要许可数据、独立双标与裁决、冻结gold/协议、真实模型参数与完整失败记录、招募同意/撤回及数据治理。新增外部适配器、权限/架构或实验变更需先写ADR并获授权。当前交付仅支持受控本地合成比赛基线，不宣称真实教学效果、生产稳定性或外部物理擦除完全通过。
