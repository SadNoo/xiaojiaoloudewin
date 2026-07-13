# xianyuxian Windows 客户端

该目录包含 Windows 桌面入口和授权 SDK。客户端使用 pywebview + Microsoft Edge WebView2 承载 React 页面，本地 FastAPI 只监听 `127.0.0.1:18765`。本地 UI 先启动，授权通过后才创建 `CookieManager` 和闲鱼自动化任务；授权失效后自动停止任务并切换为只读模式。

## 已实现

- 从 Windows `MachineGuid` 派生不可逆设备 ID，不上传原始 MachineGuid。
- 使用当前 Windows 用户的 DPAPI 加密本地授权凭证。
- 首次联网激活、一机一码、刷新凭证轮换。
- 每次启动优先联网校验，服务器不可达时验证 72 小时离线票据。
- 明确过期、吊销、设备不匹配或版本拒绝时绝不回退到离线模式。
- Ed25519 离线票据验签、设备匹配、到期和最低版本检查。
- 简单时钟回拨检测；回拨超过 5 分钟时要求重新联网。
- 15 分钟心跳管理以及离线期间 60 秒重连。
- 客户端主动解绑和本地凭证清除。
- 启动门禁辅助函数 `require_automation_license()`。
- 原生 Windows 窗口、单实例和系统托盘；关闭窗口默认继续运行，托盘“退出”才停止任务。
- 业务数据库、日志、上传和授权凭证统一写入 `%LOCALAPPDATA%\xianyuxian`。
- 首次使用可在客户端内创建本地 `admin` 管理员，无需命令行。
- 本地密码使用带随机盐的 Scrypt；旧 SHA-256 密码首次登录后自动升级。
- 安装包携带 Playwright Chromium 和 Node.js，不要求用户单独安装开发环境。
- Inno Setup 检测并按需安装 WebView2 Evergreen Runtime。

## 生产配置

生产信任根已经写入 [build_config.py](build_config.py)：

```text
LICENSE_API_BASE_URL=https://xianyuxian.dskjahf.xyz
LICENSE_PUBLIC_KEY_BASE64=PZiG1O-uIWneaA4sYpi9SUQUhYbeA7nf9DVjyEdEwYE
APP_VERSION=0.1.0
RELEASE_CHANNEL=stable
```

公钥应在构建时固定为授权服务器 `/v1/public-key` 对应的公钥。生产工厂不会从用户可编辑的 `.env` 读取 API 地址或信任根；客户端也不能在首次激活时自动接受网络返回的新公钥，否则攻击者可以同时替换票据和信任根。

`LicenseClientConfig.from_env()` 仅供本地开发使用，可设置 `XIANYUXIAN_LICENSE_ALLOW_HTTP=1`；生产构建不得调用该入口。

## Windows 构建

要求 Windows 10/11 x64、Python 3.12、Node.js 22、pnpm 和 Inno Setup 6。在 PowerShell 中执行：

```powershell
.\packaging\windows\build.ps1 -Version 0.1.0
```

构建过程会重新生成 React 静态资源，安装 Python 依赖和 Playwright Chromium，打包 onedir 客户端，运行 MachineGuid、DPAPI、Node.js 和线上 Ed25519 公钥自检，然后生成：

```text
dist\installer\xianyuxian-setup-0.1.0-x64.exe
```

也可将代码推送到有权限的 GitHub 仓库后手动运行 `.github/workflows/windows-client.yml`。Windows 自检报告位于 `%LOCALAPPDATA%\xianyuxian\logs\windows-self-test.json`。

## 基本使用

```python
from desktop_client.licensing import (
    CredentialStore,
    LicenseClientConfig,
    LicenseManager,
    get_windows_device_identity,
)

from desktop_client.licensing import create_windows_license_manager

manager = create_windows_license_manager()

decision = manager.startup_check()
if not decision.allows_automation:
    # 显示激活页、升级页或拒绝原因，不启动闲鱼任务。
    print(decision.state, decision.message)
```

首次激活页面调用：

```python
decision = manager.activate(user_entered_license_code)
```

授权通过后启动 `HeartbeatWorker`；回调收到拒绝或强制更新时，应停止创建新的自动回复/发货任务，并安全结束正在提交的原子操作。

## 测试

测试使用可注入的保护器、时钟和模拟授权 API，因此可在 macOS/Linux 验证除真实 DPAPI 之外的全部状态机：

```bash
PYTHONPYCACHEPREFIX=/tmp/xianyuxian-pycache \
  license_server/.venv312/bin/pytest -q desktop_client/tests
```

真实 DPAPI、Windows `MachineGuid`、WebView2、Playwright 浏览器和安装/卸载必须在 Windows 10/11 x64 环境完成最终集成测试。
