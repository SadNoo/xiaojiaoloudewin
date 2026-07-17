# xianyuxian 授权服务可迁移备份

这个目录用于保留管理员面板和授权服务的可迁移快照。备份与业务客户端分开，适用于 Debian VPS 迁移、灾备恢复和隔离测试机部署。

## 目录结构

```text
beifen/
├── README.md
├── refresh-from-vps.sh       # 从当前 VPS 刷新完整备份
├── restore-debian.sh         # 在新 Debian 机器上恢复并启动
├── verify-backup.sh          # 不启动服务，只验证完整性
└── private/                  # 已被 Git 忽略
    ├── xianyuxian-license-backup-*.tar.gz
    └── xianyuxian-license-backup-*.tar.gz.sha256
```

## 备份包内容

- 当前 VPS 实际运行的 `license_server` 源码和管理面板。
- PostgreSQL custom-format 数据库快照。
- `license.env`：数据库密码、HMAC 密钥、Ed25519 签名私钥和域名配置。
- Caddy `data` 和 `config` 卷，包含源站 TLS 证书与 ACME 状态。
- `backup-info.env` 备份元数据和包内 `SHA256SUMS`。

刷新脚本会在 VPS 上用 `pg_restore --list` 预检数据库快照，并在本地校验外层与包内的全部 SHA-256。

## 安全要求

`private/*.tar.gz` 等价于授权服务器的 root 备份。获得它的人可以解密今后创建的授权码、签发新离线票据并读取管理员数据。

- 该目录已通过 `beifen/.gitignore` 忽略私密备份，不要使用 `git add -f`。
- 仅保存在加密磁盘或受控的私有存储中。
- 复制到新机器后执行 `chmod 600 private/*.tar.gz`。
- 不要通过聊天、邮件或公开网盘传输未加密的备份包。

## 一键恢复到新 Debian VPS

目标机器需要：

- Debian 12/13 x86-64。
- root shell。
- Docker Engine 和 `docker compose` 插件。
- `curl`、`tar` 和 `sha256sum`。
- 开放 TCP 80/443 和 UDP 443。

将整个 `beifen` 目录复制到新 VPS，然后执行：

```bash
cd beifen
sudo ./verify-backup.sh
sudo ./restore-debian.sh
```

脚本会自动选择 `private/` 中时间最新的备份。也可以指定备份：

```bash
sudo ./restore-debian.sh private/xianyuxian-license-backup-YYYYMMDDTHHMMSSZ.tar.gz
```

使用新的测试子域名：

```bash
sudo ./restore-debian.sh --domain test-license.example.com
```

`--domain` 会替换备份内的 `LICENSE_DOMAIN` 和 `LICENSE_PUBLIC_BASE_URL`。正式 Windows 客户端当前固定使用 `xianyuxian.dskjahf.xyz`；如果想让客户端连接新测试子域名，还需用新 API 地址重新构建测试版客户端。

## 域名迁移注意事项

- 真正无缝迁移时，保持 `xianyuxian.dskjahf.xyz` 不变，完成新 VPS 内部验收后再切换 Cloudflare 源站 IP。
- 不要让两台服务器长期同时接受生产请求，否则会产生两份分叉的设备绑定和审计数据。
- 恢复脚本遇到已有 `/opt/xianyuxian/current` 或同名 Docker 卷时会停止，不会自动覆盖现有数据。

## 刷新本地备份

在当前 Mac 项目根目录执行：

```bash
./beifen/refresh-from-vps.sh
```

默认连接 `root@177.0.143.19` 并使用项目根目录的 `xianyuxian.pem`。可通过环境变量覆盖：

```bash
VPS_HOST=203.0.113.10 VPS_USER=root SSH_KEY=~/.ssh/key ./beifen/refresh-from-vps.sh
```
