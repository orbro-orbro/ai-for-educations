# 本地改进交接（2026-10-21）

## 已完成

- 参考微分课件的本地连续学习体验，新增学生/课程/练习范围的草稿保存、恢复、失败提示和确认清除。
- 理解验证回调按真实 `understands` 更新轨迹，包括后续验证不通过时撤销已显示的通过进度。
- 新增可选教师测试同源 Web/API 入口、邮箱保护启动脚本和操作说明。沿用既有测试账号和保留旧卷的合成数据重置。
- 首次交付按用户要求仅保存在本地；2026-10-21 用户随后明确要求创建新分支并上传 GitHub。本次以 feature/teacher-test-drafts 分支交付，不修改 main，不创建 PR。

## 修改文件

- `README.md`
- `frontend/src/App.tsx`
- `frontend/src/student/StudentPage.tsx`
- `frontend/src/student/ExercisePage.tsx`
- `frontend/src/student/DiagnosisPanel.tsx`
- `frontend/src/student/useCodeDraft.ts`（新增）
- `frontend/vite.config.ts`
- `frontend/tests/student-flow.test.tsx`
- `frontend/tests/wave3-integration.test.tsx`（为直接使用练习页的测试补充明确的合成学生 ID）
- `frontend/tests/teacher-preview.test.mjs`（新增）
- `frontend/tests/draft-browser.test.mjs`（新增）
- `infra/compose/docker-compose.teacher-test.yml`（新增）
- `scripts/start-delivery.ps1`（新增可选 TeacherTest 参数）
- `scripts/start-teacher-test.ps1`（新增）
- `scripts/tests/test_teacher_launcher.py`（新增）
- `docs/adr/0009-teacher-test-access.md`（新增，待确认）
- `docs/teacher-test.md`、本交接（新增）

## 验证结果

新增草稿和理解进度用例在修改前 4 项失败；修改后前端测试 48/48 通过（包含后续清除草稿用例）。代理测试先因返回 HTML 而失败，添加代理后通过真实 HTTP GET/POST、查询参数、Authorization 传递和 Host 限制检查。启动器测试在脚本未实现时失败，完成后 3/3 通过。

最终按原 `package-lock.json` 使用 npm ci 安装：React 19.3.0、Vite 8.3.1、Vitest 5.0.3、TypeScript 7.0.2。之前临时使用 pnpm 的较新兼容版本已被替换；不交付 pnpm 锁文件，不修改原依赖清单。

最终命令（frontend 目录）：

```text
node node_modules/typescript/bin/tsc -b                   PASS
node node_modules/vite/bin/vite.js build                 PASS
node node_modules/vitest/vitest.mjs run                  48/48 PASS
node --test tests/teacher-preview.test.mjs               1/1 PASS
node --test tests/draft-browser.test.mjs                 1/1 PASS
```

仓库根目录：`python -m unittest discover -s scripts/tests -p test_teacher_launcher.py`，3/3 PASS。另直接调用原有 `test_delivery_launcher.py` 的两个无 pytest 依赖用例，外来容器拒绝与保留旧卷检查均通过。

浏览器验收使用无头 Edge、合成 API 替身。已检查页面截图，离线编辑后恢复联网并刷新，草稿保持且没有自动提交；没有浏览器运行时异常。这不是完整 SQL/真实 Runner 验收。

## 数据库、API 和配置影响

无数据库迁移，无 OpenAPI 修改，无新依赖，无教师数据读取权限扩张。新增可选 Compose 覆盖设置 Web 构建 `VITE_API_BASE_URL=/api`，运行时 `KNOWBOUND_TEACHER_TEST=1`、`KNOWBOUND_API_PROXY_TARGET=http://api:8000`。普通启动模式不使用该覆盖。

桌面目录最初从 GitHub 官方 main 源码 ZIP 导入，因为两次 git clone 连接超时。上传前已成功 fetch origin/main，并确认其文件树与导入基线完全一致；新分支直接从真实 origin/main 创建，保留上游历史，不上传本地导入提交。

## 未完成和依赖

未检测到 Docker 命令或默认 Docker Desktop 安装，cloudflared 亦未安装；未进行 Compose 实际启动、SQL 集成、真实 Runner、真实公网邮箱验证。因此不宣称教师测试部署已可用，也未生成公开网址。

仓库 AGENTS.md 规定「关键架构或权限变更必须先写 ADR，并获得用户确认。」公网启用前应确认 ADR 0009，并由用户提供具体教师邮箱。脚本已准备供审阅，目前不执行公网启用。

没有新增云流程预览执行适配器；方案二、学校/VPS 部署、真实学生独立账号发放、真实模型评测和真实教学试点留待相应条件具备后处理。
