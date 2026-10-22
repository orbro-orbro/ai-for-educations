# PR 9–11 集成执行计划

Goal: 保留源提交关系，将三个 PR 集成到 codex/pr9-11-integration，并验证交付边界。
Spec: ../specs/2026-10-01-knowbound-cangjie-design.md 和本次用户任务。
执行方式：本会话直接执行；用户已明确要求持续完成，不增加审批停点。

- [x] 查询 PR HEAD、main、工作树与依赖；不接触根目录用户修改。
- [x] 按 #9、#10、#11 合并；App/ExercisePage 保留模型面板、账号 key、草稿与理解状态。
- [x] 教师入口 ADR 改为 0011，保持待确认；真实模型 ADR 0009 与网页 ADR 0010 保留状态。
- [x] 先失败测试，再修复 DeliveryMock 启动与个人配置覆盖、运行时修改/恢复路径、PUT 预检。
- [x] 先失败测试，再限制空 Key 复用到相同端点，防止更换 base_url 时向另一端点发送保存的 Key。
- [x] 验证模型网关、权限、运行时契约、前端、浏览器与教师本地代理；区分替身与真实服务。
- [x] 有可用 Docker 时执行隔离 Runner、PostgreSQL、完整交付闭环；无法启动则记录实际故障，不运行宿主 runner/tests。
- [x] 更新入口、开关、存储隐私说明；提交、推送集成分支并提交交接。

Review focus: 固定 Mock 的所有配置路径；个人 Key 的请求归属；恢复环境的 provider；草稿作用域与存储异常；理解失败重试。
共享配置影响：live Compose 新增 MODEL_SETTINGS_ENABLED=1；.env.example 默认 0；不改变端口、卷、凭据、数据库迁移与 API schema。

执行结果：Docker 引擎不可用，真实容器/PG部分记录为阻塞；其余集成、失败复现、修复、验证和分支推送已完成，见交接报告。
