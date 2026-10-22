# 登录页布局修复交接（2026-10-22）

## 原因与完成范围

演示模式下，`DemoNotice` 是 `.login-page` 的首个网格子元素。原两列自动排布把它放到左上，介绍区被排到右侧，表单掉到第二行。无插件 Edge、1920×1080 下复现：介绍区在 x=1296、y=0，表单在 x=0、y=972。

按用户“直接修复”的授权，保留原配色、字体、文案和登录逻辑，只修复布局：顶部声明独占整行，桌面介绍左侧、表单右侧；720px 以下保持声明、介绍、表单纵向排列。未显示声明时，空行自动折叠。

## 本任务文件

- `frontend/src/styles.css`：明确 notice／intro／panel 网格区域，声明紧凑显示并允许长文本换行，保留手机纵向布局。
- `frontend/e2e/learning-loop.spec.ts`：新增 7 个视口回归，覆盖两栏对齐、声明宽度、标题不裁切、无横向溢出、按钮可见及用户名→密码→登录的键盘顺序。原有其他任务测试均保留。
- 本交接文档。已有 README、诊断格式和中文输出改动、其他用户文件未撤销或提交。

## 验证

- 先新增失败测试：演示模式下 1366×768、1920×1080、2560×1440、1280×720 四项因介绍与表单相隔约 843—979px 而失败，三个手机／窄屏用例通过。
- 修复后 1366px 测试发现声明宽度为 1365.984375px；允许 1px 的正常浏览器亚像素取整误差，不放宽错行、可访问性、溢出或标题裁切要求。
- frontend 下 `npm test`：78 通过；`npm run build`：通过。
- 设置 `VITE_SYNTHETIC_DEMO=true`、`VITE_MODEL_LABEL=DeepSeek - layout-test`，在 frontend 运行 `npm run test:e2e`：24 通过，16.7 秒，退出码 0。声明明确保留“非教学试点结果”，不提交真实登录或模型请求。
- 设置 `VITE_SYNTHETIC_DEMO=false`、空 `VITE_MODEL_LABEL`，在 frontend 独立执行 `npm run test:e2e`：24 通过，16.0 秒，退出码 0。连续启动第二轮时曾留下本轮 Vite 进程占用 5199；核验命令行后仅清理该临时预览进程，再独立重跑，没有设置 `reuseExistingServer` 或修改断言绕过。
- 独立只读审查：无 Critical／Important／Minor 发现。额外浏览器检查 721×600、800×600、1024×768、683×384、320×568、640×360、1366×768，通过；浏览器内临时移除声明确认无空白声明行。683px 为缩放等效 CSS 宽度，不声称测试了浏览器实际缩放或其他浏览器引擎。
- `git diff --check`：通过。

## 本地更新及截图

核验 `knowbound-live-demo-web-1` 项目／任务标签及 5309/8308 端口后，沿用现有 env 和模型名称执行：

```text
docker compose --env-file .delivery/live-model.env -p knowbound-live-demo -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.live-model.yml build web
docker compose --env-file .delivery/live-model.env -p knowbound-live-demo -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.live-model.yml up -d --no-deps --no-build --wait --wait-timeout 60 web
```

执行前从原配置生成相同的非敏感 `MODEL_LABEL`，没有输出密钥。网页镜像构建、健康等待退出码 0；仅重建网页，API、Runner、PostgreSQL 未重启。Mock 5209 未重建。

实际 5309 页面：1920×1080 下声明高39px，左右两区均从 y=39 开始，登录按钮底部约731px；390px 下纵向排布、可滚动到登录按钮。已查看实际页面截图：`.delivery/login-layout-fixed-1920.png`、`.delivery/login-layout-fixed-390.png`。API 8308 `/health` 保持 `ok`。

## 接口、配置和限制

无数据库迁移、API、角色权限、认证、Compose、环境变量文件、依赖或模型调用改动；未提交或推送 GitHub。此次是 CSS 和浏览器回归，本轮未重跑后端全量或原生 Runner 测试，不将既有结果当成本轮运行结果。

用户在 `http://127.0.0.1:5309/` 按 Ctrl+F5 强制刷新即可加载新 CSS；不需要重新登录账号或改变缩放来规避此缺陷。
