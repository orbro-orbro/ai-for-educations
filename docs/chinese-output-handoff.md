# 简体中文输出约定交接（2026-10-22）

## 完成范围

用户确认将解释性内容统一为中文。本次仅调整模型高优先级指令与诊断类别、证据类型的页面名称，不做自动翻译服务或语言识别，不额外调用付费模型。

- 诊断 `root_cause`、提示 `content`、理解验证 `feedback/evidence_summary` 和模型撰写的证据 `summary` 使用简体中文，输入或课程材料为英文时也适用。
- JSON 字段、枚举值、概念 ID、引用标识、路径、源码和引用的编译器原文保持原值。中文解释可保留技术术语；后端仍以真实记录重建证据摘要，不能为了中文显示改写编译器原文。
- 两种真实模型传输共用一套约定，覆盖诊断、分级提示和理解验证。DeepSeek/Qwen 及 OpenAI-compatible 接入使用相应已有传输，不新增供应商。
- 学生与教师共用四类名称：概念理解、解题策略、操作步骤、表达方式；学生证据标题使用“编译器诊断／规则匹配／已审核课程知识”。底层枚举不变，教师统计中未识别的类型保留原值。
- 不翻译历史诊断、不改长期记忆。新约定对后续生成生效，旧英文记录保持原样。

## 本任务文件

- 新增 `backend/app/model_gateway/instructions.py`：共用中文叙述规则。
- 修改 `backend/app/model_gateway/openai_chat_completions.py`、`openai_responses.py`：在原高优先级指令中追加规则，保留 JSON、证据与安全约束。
- 新增 `backend/tests/model_gateway/test_output_language.py`：2 种传输 × 3 种操作，捕获真实外发 HTTP payload，验证语言指令、输入不改写及中文响应结构兼容。
- 新增 `frontend/src/components/diagnosisLabels.ts`：两端共用类别名称映射。
- 修改 `frontend/src/student/DiagnosisPanel.tsx`、`frontend/src/teacher/CourseDashboard.tsx`：仅显示名称中文化，不更改摘要或 API 字段。
- 修改 `frontend/tests/student-flow.test.tsx`、`frontend/tests/teacher-privacy.test.tsx`：四类名称、证据标题、英文原始证据与概念 ID 保留。
- 修改 `frontend/e2e/learning-loop.spec.ts`：补学生桌面和教师手机端中文显示断言。
- 本交接文档。

原有格式修复、README、其他用户文档与未提交文件均保留。本任务没有提交或推送 GitHub。

## 验证命令与结果

先新增失败测试：后端 6 项因外发指令缺少简体中文约定失败；学生显示 4 项、教师显示 4 项因仍显示英文类别失败。实现后验证：

1. `python -B -m pytest -c backend/pyproject.toml backend/tests/model_gateway/test_output_language.py backend/tests/model_gateway/test_openai_chat_completions.py backend/tests/model_gateway/test_openai_responses.py backend/tests/diagnostics -q -p no:cacheprovider --tb=short`：123 通过。
2. 使用现有集成工作树 `scripts/use-delivery-test-environment.ps1` 核验独立测试容器、加载测试配置，再运行 `python -B -m pytest -c backend/pyproject.toml backend/tests -q -p no:cacheprovider --tb=short --basetemp <工作区内全新 .delivery/chinese-output-pytest-随机标识>`：1164 通过、163 项既有弃用警告，无跳过，358.23 秒，退出码 0。
3. frontend 下 `npm test`：78 通过；`npm run build`：通过。
4. frontend 下 `npm run test:e2e`：17 通过，15.6 秒，退出码 0。首次新增的 `teacher sees only anonymous signals on a phone viewport` 定位失败；实际可访问快照显示手机端单元格名称为“类型 概念理解”（CSS 既有前缀），按完整名称调整定位后全部通过，未更改页面或隐私断言。
5. `git diff --check`：通过；公共 OpenAPI、Compose、依赖清单及锁文件未修改。
6. 按代码审查技能完成独立只读复核：无 Critical／Important／Minor 发现；审查未代替实际测试，未改工作区。

## 本地环境更新

使用原命令 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-live-demo.ps1` 更新 5309/8308 大模型版；沿用现有数据和密钥。

首次 API 镜像重建因下载依赖包的哈希与锁文件不符失败，构建保护生效，原 API 保持运行。未修改锁文件、哈希、版本或关闭校验，按相同严格命令重试后成功构建并完成健康等待，退出码 0。

最终只读检查：8308 `/health` 为 `ok`，5309 网页正常；实际提供的 JavaScript bundle 包含全部七种中文类别／证据标题。容器内两种模型传输均导入同一个简体中文输出约定，未发起模型请求。只更新大模型环境 5309/8308，Mock 5209/8208 未重建。

## API、数据、配置与风险

无数据库迁移、公共 API、角色权限、环境变量、Compose、依赖或外发 DTO 变更。测试写入仅限已核验的专用合成测试库；生产式演示数据不清空。不向真实模型提交测试请求，不额外产生模型费用。

自动化测试证明语言指令被发送、协议不被翻译、界面映射正确，不证明外部模型的中文遵循率或教学准确率。未增加逐字段中文强制识别或自动翻译重试，避免误拒绝代码、路径或原始证据及额外费用。旧记录不回填翻译，验证新生成中文需用户重新提交或请求新提示，正常使用会产生 API 费用。

上一任务记录的 Windows 原生 Runner 3 项运行异常不是本任务修改范围；本轮执行的是全部后端测试及浏览器回归，未宣称原生 Runner 测试通过。详见 `docs/diagnosis-format-fix-handoff.md`。
