# ADR 0011：受控教师测试入口

- 状态：待用户确认；不启动公网隧道
- 日期：2026-10-21

## 决策草案

优先采用用户提出的方案一。复用现有合成演示栈和账号，不新增角色、数据表或模型供应商。仅在显式教师测试模式中，让现有 Web 的 Vite preview 将 `/api/` 代理到固定的 `http://api:8000`，前端构建使用相对地址 `/api`。普通交付入口保持原配置。

通过 cloudflared Quick Tunnel 暂时开放本机 Web 5209 端口。必须明确指定教师邮箱白名单，禁止通配邮箱；旧 cloudflared 不支持 `--allowed-mail` 时停止，不降级为匿名公开。教师先通过邮箱验证码，再使用应用账号登录；邮箱验证不授予应用教师权限。

不公开 PostgreSQL、Runner Controller 或 Docker Socket。API 仍经现有服务端认证和课程权限检查。代码由真实隔离 Runner 执行，模型继续使用已标注的确定性 Mock。教师不能查看学生私人草稿或完整个人记忆。

复用现有 `-FreshData`：切换到新合成数据卷并保留旧卷，不执行数据库删除。测试结束按 Ctrl+C 关闭前台隧道；Docker 栈可另行停止。临时域名改变会使浏览器本地草稿与登录状态按来源隔离，不能承诺跨域恢复。

## 依据和限制

Cloudflare 官方 Quick Tunnels 文档（2026-10-21 核实）：支持重复的 `--allowed-mail`，不需要域名或 Cloudflare 账号；不保证可用性，不支持 SSE，最多 200 个在途请求。当前 API 使用 JSON 请求，不引入流式接口。

https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/

方案二后续需单独设计确定性执行预览适配器与醒目标识，不能在真实 Runner 故障时伪造编译结果。方案四是未来完整测试的迁移方向；当前不注册 Oracle 或购买 VPS。

## 影响

新增可选 Compose 覆盖、教师测试启动脚本；现有 launcher 增加显式模式开关。数据库、OpenAPI、教师数据访问边界、Runner 沙箱和统计指标均不变。公网启用须用户确认本 ADR，并提供真实允许访问的邮箱。

## 补充（2026-10-21，实现阶段；状态仍为待用户确认）

1. 编号：原文件为 0009，与 `0009-live-model-providers.md` 冲突，已改为 0011。
2. 两种入口并存，由教师自选，见 `docs/teacher-guide.md`：
   - 方式一：教师在自己电脑安装 Docker Desktop，双击 `start-teacher-local.cmd`，使用普通演示栈，不使用隧道构建，不隐式重置数据。
   - 方式二：本决策的隧道入口，教师只用浏览器；当前未开通，因为尚无受邀教师邮箱。
3. 教师测试模式下 Web 代理屏蔽 API 交互文档：`/docs`、`/redoc`、`/openapi*`。匹配前先解码、小写并折叠重复斜杠，无法解码按屏蔽处理；被屏蔽的路径不会转发到上游。
4. 代理超时由 30 秒提高到 125 秒，以容纳真实模型调用（设置上限 120 秒）。Cloudflare 边缘自身可能有更短的超时，尚未实测，不能承诺。
5. 脚本兼容系统自带的 Windows PowerShell 5.1：`Invoke-WebRequest` 使用 `-UseBasicParsing`，避免对 IE 引擎的依赖；新增脚本以带 BOM 的 UTF-8 保存。启动器测试在 5.1 下通过，PowerShell 7 路径未在本机验证（本机未安装）。
6. **约束（必须保留）：公网教师测试模式下不得开放网页模型配置接口。** 该类接口（见 `workbuddy/feat-live-model-provider-ee29053d`）当前存在“复用已保存密钥时未比较 `base_url`”的外泄路径（代码阅读结论，尚未修复）。在其修复并经用户确认前，不合并该分支，也不在公网模式下暴露。
7. 教师包仅由已提交文件生成（`git archive`），并拒绝任何被提交的密钥或依赖目录；不含 `.delivery`、`.env`、`node_modules`。
