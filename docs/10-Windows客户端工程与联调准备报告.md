# Windows 客户端工程与联调准备报告

> 客户端版本：0.1.0  
> 支持平台：Windows 10 22H2 / Windows 11 x64

## 当前工程结果

- Windows 入口：`desktop_client/windows_app.py`
- 授权 API：`https://xianyuxian.dskjahf.xyz`
- 桌面技术：Python 3.12 + pywebview 6.2.1 + Edge WebView2
- 打包技术：PyInstaller 6.21 onedir
- 安装程序：Inno Setup 6，每用户安装，不要求管理员权限
- 本地 API：仅监听 `127.0.0.1:18765`
- 本地数据：`%LOCALAPPDATA%\xianyuxian`
- 构建脚本：`packaging/windows/build.ps1`
- CI：`.github/workflows/windows-client.yml`

## 已完成能力

1. 原生 Windows 窗口和 React 管理界面。
2. 单实例控制，避免重复启动本地 API 和业务任务。
3. 系统托盘；关闭窗口保持运行，托盘退出时安全停止心跳和业务任务。
4. 首次联网授权、一机一码、DPAPI 凭证、72 小时离线宽限和 15 分钟心跳。
5. 远程吊销、客户端版本禁止、最低版本和升级下载地址。
6. 首次本地管理员初始化，无需 Python CLI。
7. 本地密码 Scrypt 存储；旧数据库登录后自动升级密码哈希。
8. 数据库、日志、图片、授权凭证均写入当前用户 LocalAppData。
9. Playwright Chromium 和 Node.js 随安装目录部署。
10. 安装程序检测 WebView2，缺失时通过微软 Evergreen Bootstrapper 静默安装。
11. Windows 打包后自检 MachineGuid、DPAPI、Node.js、HTTPS 授权 API 和 Ed25519 公钥一致性。

## 本地验证

- Python 编译检查通过。
- TypeScript 类型检查通过。
- React 生产构建通过。
- 自动化测试 22 项通过。
- PyInstaller spec 数据文件选择和敏感密钥扫描通过。

macOS 不能生成或运行原生 Windows PyInstaller 产物，因此 `.exe` 和安装程序的最终构建必须在 Windows x64 或 Windows GitHub Actions runner 完成。

## Windows 构建命令

```powershell
.\packaging\windows\build.ps1 -Version 0.1.0
```

预期产物：

```text
dist\xianyuxian\xianyuxian.exe
dist\installer\xianyuxian-setup-0.1.0-x64.exe
```

## 联调测试顺序

1. 全新 Windows 用户安装并启动，检查 WebView2、Node.js 和 Chromium。
2. 使用 `--self-test` 结果确认 MachineGuid、DPAPI、线上公钥一致。
3. 在云端创建一枚“部署联调”临时授权码。
4. 客户端首次激活，确认管理后台出现一台设备。
5. 重启客户端，确认在线刷新成功且无需再次输入授权码。
6. 断网启动，确认进入离线宽限并显示截止时间。
7. 恢复网络，确认 60 秒内恢复在线状态。
8. 云端吊销设备，确认下一次心跳停止自动化任务并保留本地数据。
9. 重新创建授权并测试主动解绑、同码第二设备拒绝。
10. 发布最低版本策略，确认旧版进入强制更新页并显示下载入口。
11. 验证扫码登录、关键词回复、订单同步、卡券发货各一条端到端路径。
12. 卸载客户端，确认安装文件删除但 LocalAppData 用户数据不被误删。

## 发布前仍需 Windows 实机确认

- Defender/SmartScreen 对未签名个人安装包的提示。
- WebView2 窗口缩放、中文输入法、托盘和多显示器表现。
- Playwright Chromium 启动和人工验证码窗口。
- 安装包大小、首次启动时长和 8GB 内存机器的资源占用。
- 安装、覆盖升级、卸载和保留数据行为。
