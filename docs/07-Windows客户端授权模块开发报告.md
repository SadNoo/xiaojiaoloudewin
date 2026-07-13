# Windows 客户端授权模块开发报告

> 完成日期：2026-07-12  
> 代码目录：`desktop_client/licensing/`  
> 阶段状态：独立授权 SDK 已实现并通过跨平台测试；随后已接入原项目 `Start.py`，详见下一阶段报告。

## 已完成

- Windows `MachineGuid` 读取及不可逆设备 ID 派生，原始 GUID 不上传服务器。
- `%LOCALAPPDATA%/xianyuxian/license/credential.bin` 凭证路径。
- Windows DPAPI 当前用户级加密、原子保存和损坏检测。
- 授权 API 客户端，区分服务器不可达与服务端明确拒绝。
- 首次联网激活、刷新令牌轮换和启动在线验证。
- Ed25519 离线票据验签、用途、设备、期限、授权期限和最低版本检查。
- 72 小时离线宽限；仅网络/服务故障允许使用。
- 服务端 401/403/409/426 等明确结果不回退到离线模式。
- 本地时间回拨超过 5 分钟时拒绝离线启动并要求联网。
- 15 分钟在线心跳，离线状态每 60 秒尝试恢复联网。
- 心跳收到吊销、过期或强制更新后返回不可启动状态。
- 客户端主动解绑和本地凭证清除。
- `require_automation_license()` 启动门禁函数，供下一阶段接入闲鱼任务之前。
- 构建时固定 API 地址和 Ed25519 公钥，生产工厂不从用户可编辑 `.env` 读取信任根。

## 验证结果

- 客户端授权测试 7 项通过。
- 授权服务测试 6 项通过。
- 全项目授权相关测试：`13 passed`。
- Python 3.12 编译检查通过。
- 没有改动原闲鱼业务文件。

测试覆盖在线激活、加密存储、刷新轮换、心跳、远程拒绝、离线宽限、离线过期、时钟回拨、设备不匹配、最低版本和网络错误分类。

## Windows 环境待验证

当前开发环境为 macOS，以下项目必须在 Windows 10/11 x64 环境验证：

1. 64 位注册表 `MachineGuid` 读取。
2. `CryptProtectData`/`CryptUnprotectData` 的真实 DPAPI 往返。
3. 不同 Windows 用户不能解密彼此凭证。
4. 系统重启、改计算机名和正常 Windows 更新后设备 ID 保持稳定。
5. WebView2/Nuitka 或 PyInstaller 打包后 DPAPI 和 `httpx` 正常工作。
6. 杀软、Windows Defender 和每用户安装目录权限。

## 下一阶段接入点

在 `Start.py` 创建 `CookieManager` 以及启动任何闲鱼监听任务之前：

1. 创建 `LicenseManager`。
2. 调用 `startup_check()`。
3. 未激活时展示授权码输入页。
4. 只有 `decision.allows_automation == True` 才继续启动业务内核。
5. 启动 `HeartbeatWorker`；回调收到拒绝时停止创建新任务并安全关闭现有任务。
6. 在前端增加激活、离线倒计时、到期、吊销和强制升级状态页。
