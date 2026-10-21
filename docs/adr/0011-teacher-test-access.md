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
