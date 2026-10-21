# 教师小范围测试

当前提供的是用户方案一的可选实现，启用前需确认 ADR 0011。未部署方案二的独立云预览，不把 Mock 描述为真实模型或编译结果。

## 本次教学体验改进

参考《2.3 微分课件-student.html》的分步引导和本地保存，补充按学生、课程、练习分开的源码草稿。每次编辑即时本地保存，刷新后恢复；保存失败明确提示。草稿不自动作为正式作业上传，不生成长期记忆。清除按钮只处理当前练习的本机草稿，并要求确认。

草稿保存在浏览器当前来源下，共用电脑用完应清除。换浏览器、设备或临时域名不能跨来源恢复；这不是服务端加密存储。提交和编译结果仍以服务端为准。理解验证未通过时，学习轨迹现在不会误报前进。

项目已有分层提示、修复关联、记忆确认、匿名统计和合成测试演员，本次复用这些功能。不会像参考课件一样让全班共用一个身份，或把学生私人过程默认交给教师。

## 前置条件

- Windows PowerShell 5.1（系统自带）或 PowerShell 7 均可；Docker Desktop，Linux 引擎已启动。
- cloudflared 已加入 PATH，且 `cloudflared tunnel --help` 包含 `--allowed-mail`。安装参考 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ 。脚本不会自行安装或修改系统代理。
- 首次构建需要下载容器镜像和项目锁定依赖；不是断网安装包。
- 已确认 `docs/adr/0011-teacher-test-access.md`，准备好允许访问的具体教师邮箱。

## 启动

在仓库根目录运行，替换为真实邮箱：

```powershell
powershell -NoProfile -File ./scripts/start-teacher-test.ps1 -AllowedEmail 'teacher@example.com'
```

多个邮箱请从 PowerShell 直接调用脚本并传数组：

```powershell
./scripts/start-teacher-test.ps1 -AllowedEmail @('teacher1@example.com','teacher2@example.com')
```

脚本会校验邮箱和客户端，复用交付脚本构建启动 Docker 栈，检查本机网页和 `/api/health`，然后在当前终端运行受邮箱保护的 Tunnel。分享终端显示的 `https://….trycloudflare.com` 地址。保留终端；按 Ctrl+C 终止隧道即结束公网访问。

老师先进行邮箱验证码验证，再使用应用账号登录。Cloudflare 邮箱验证与应用角色是两层独立检查。演示教师账号 `demo-teacher`，学生账号 `demo-student-1` 到 `demo-student-6`；生成的密码保存在 Git 忽略的 `.delivery/demo.env` 的 `DEMO_PASSWORD`，通过单独渠道交给受邀者，不公开发布该文件。

当前演示演员共用生成的演示密码，只用于受控合成测试，不可用于真实学生试点。真实试点前需单独处理账号发放和独立密码。

## 重置与停止

```powershell
./scripts/start-teacher-test.ps1 -AllowedEmail 'teacher@example.com' -FreshData
```

该命令选择新的合成数据卷；旧卷保留，不删除旧数据。它不会清除浏览器草稿或已导出的文件。

隧道退出后，本机 Docker 服务继续运行。停止本机服务：

```powershell
powershell -NoProfile -File ./scripts/start-delivery.ps1 -Action Stop -TeacherTest
```

不要同时运行普通启动与教师测试启动。教师测试总会重新构建相对 API 地址版本。回到原本本地比赛模式时运行普通 `start-delivery.ps1`（不要加 `-NoBuild`），以恢复普通构建。

## 网络边界与真实性

可选 Compose 只改变 Web 构建参数和运行时代理，端口数量不增加。公网路径仅 Web 与 `/api/`；固定 API 上游为容器 `api:8000`。PostgreSQL、Controller、Docker Socket 不挂到公网入口。原服务端角色与课程检查不变，不使用 CORS 通配符。

数据是合成数据，模型响应是确定性 Mock，编译反馈仍来自真实隔离 Runner；理解检查的 Mock 固定行为不能用于教学成效证明。Runner 不可用时保留真实错误状态，不伪造成功。

Cloudflare 官方说明：Quick Tunnel 无可用性保证、域名会变、不支持 SSE，最多 200 个在途请求。仅用于少量受邀教师测试；稳定完整部署优先学校服务器。云流程预览需另外实现明确标识的执行替身与独立数据隔离，不在本次自动启用。

https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/

## 开发验证

前端目录：`npm ci --ignore-scripts`、`npm run build`、`npm test`、`npm run test:node`（包含代理、API 文档屏蔽、超时配置和草稿浏览器测试；草稿测试会自行构建，不依赖上一次 `dist`）。浏览器测试需要已安装 Microsoft Edge，使用替身 API 验证草稿交互，不代表真实 Runner 端到端验证。

仓库根目录：`python -m unittest discover -s scripts/tests -p "test_teacher_*.py"`（启动器、教师本机启动器和教师包，均使用替身命令，在 Windows PowerShell 5.1 下运行）。该测试只运行替身命令，不打开隧道。完整 Docker/真实 Runner 验收继续使用原交付流程；缺少 Docker 不算通过。
