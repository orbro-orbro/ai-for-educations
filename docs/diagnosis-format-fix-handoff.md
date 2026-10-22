# 诊断输出格式修复交接（2026-10-22）

## 范围与结果

修复 DeepSeek 能返回 JSON、但网关输出定义与业务校验不一致的问题。分类不再允许任意字符串，代码位置必须使用 `file/start_line/end_line`。模型提示与业务候选对象共用结构定义，同时保持本地源码范围、课程知识、证据引用及可信摘要重建校验。

前端遇到诊断 404 后，重新通过现有 API 核验提交访问权。仅当提交仍可访问且状态为 `needs_review` 时显示“诊断暂不可用”，保留编译反馈及请求编号。无法访问提交时仍使用统一拒绝提示，不根据单独的 404 推断资源存在。重新读取仅执行 GET，不重新生成诊断。

本次没有调用真实模型；不保证第三方模型每次都遵循格式或提供正确教学判断。不修复既有失败提交，也不增加重新调用模型的接口。

## 修改文件

- `backend/app/model_gateway/base.py`：严格输出契约；保留既有网关导出和公共 OpenAPI 组件名。
- `backend/app/diagnostics/schema.py`：复用结构定义，原业务证据校验不变。
- `frontend/src/student/ExercisePage.tsx`：区分已授权提交的诊断缺失与资源不可访问。
- `backend/tests/diagnostics/test_schema.py`：检查实际外发 schema、有效响应到本地证据绑定、13 种非法结构。
- `frontend/tests/student-flow.test.tsx`：诊断缺失、只读重查、撤权后的 403/404 回归。
- `frontend/e2e/learning-loop.spec.ts`：真实浏览器中验证提示、编译结果保留及撤权后重新核验。
- 本交接文档。

## 验证记录

1. 修改前相关后端测试 164 通过，前端测试 67 通过。
2. 新测试先失败：后端 14 项、前端 3 项，分别暴露缺失结构约束、错误权限提示及未重新核验访问权。
3. `python -B -m pytest -c backend/pyproject.toml backend/tests/diagnostics backend/tests/model_gateway backend/tests/contracts/test_task6_openapi.py backend/tests/contracts/test_wave3_runtime_openapi.py -q -p no:cacheprovider`：229 通过。
4. `npm test`（frontend）：70 通过。
5. `npm run build`（frontend）：通过；Docker Web 镜像内构建也通过。
6. `npm run test:e2e`（frontend）：17 通过。Windows 下测试服务器收尾等待，核验进程身份后仅结束本轮 Vite 和测试 API，最终命令退出码 0。
7. 只读审查额外比较 `Diagnosis.model_json_schema()` 与 HEAD：完全一致，候选对象字段结构一致，模块导入无循环。
8. 全部后端：使用原集成工作树中现存的 `scripts/use-delivery-test-environment.ps1` 核验测试环境并加载配置，再执行 `python -B -m pytest -c backend/pyproject.toml backend/tests -q -p no:cacheprovider --tb=short --basetemp <工作区内全新 .delivery/diagnosis-fix-pytest-随机标识>`：1158 通过、163 项既有弃用警告，353.50 秒，退出码 0；无跳过。工作区根目录没有该测试脚本预期的 `test.env`，因此使用现有集成工作树中的配置，不复制或输出凭据。
9. `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-live-demo.ps1`：镜像重建及健康等待通过，退出码 0。仅更新本地大模型版 5309/8308，Mock 5209/8208 未重建。API `/health` 返回 `ok`，网页 HTTP 200；实际容器内 schema 包含四种分类及 `file/start_line/end_line`，实际提供的网页 bundle 含新提示。
10. 用现有演示学生只读查询先前失败提交：仍为 `needs_review`，诊断 GET 仍为统一 404；确认原记录保留且没有自动重新生成。未打印登录密码或令牌。

## 环境问题与限制

- 首次契约测试的 `test_gate_services_are_reachable_over_loopback` 使用默认 55430 端口失败；改用项目现有 `use-delivery-test-environment.ps1`，核验并使用独立 `knowbound-wave4-test` 测试环境。
- 首次根目录前端缺少已在锁文件声明的 Node 类型及 Playwright。执行 `npm ci --offline --no-audit --no-fund` 后测试、构建通过；没有更改依赖清单或锁文件。
- 首次默认全量 pytest（含 Runner）结果为 1159 通过、47 项临时目录设置错误、3 项失败。47 项均因系统 `Temp/pytest-of-lenovo` 无访问权限；后续全部后端重跑改用工作区内全新 `--basetemp`，不降低断言。
- 未修改的 Windows 原生 Runner 失败项：`test_execute_compiles_and_runs_minimal_cangjie_program`、`test_execute_terminates_infinite_loop_at_request_timeout`、`test_execute_caps_excessive_output`。原生执行退出码为 `3221225477`，未在本任务中调整 Runner 或仓颉工具链；不宣称默认含原生 Runner 的全量命令通过。
- 既有 Starlette/httpx、Alembic 弃用警告保留，未为消除警告扩大依赖变更。

## 数据库、API、配置及交付

无数据库迁移、公共接口、角色权限、Compose、环境变量、依赖版本或模型外发数据范围变更。测试写入仅限已核验的专用合成测试数据库。保留原工作区 README 和其他用户文档，未提交或推送 GitHub。

本地运行服务采用镜像内代码，不能仅刷新浏览器就更新旧镜像；本次已完成大模型环境的重建与更新。既有失败提交不会自动调用模型，请在 `http://127.0.0.1:5309/` 强制刷新后重新提交以验证真实模型响应，可能产生正常 API 费用。
