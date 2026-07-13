# Debian VPS 部署与验收报告

## 部署结果

- 管理地址：`https://xianyuxian.dskjahf.xyz`
- 源站：Debian 13，`177.0.143.19`
- 部署目录：`/opt/xianyuxian/current`
- 私密配置：`/opt/xianyuxian/secrets/license.env`（仅 root 可读）
- 数据库：PostgreSQL 17，Docker 内网访问，不暴露公网端口
- 入口：Caddy 2.10，仅暴露 80/443
- Cloudflare：Universal SSL 橙色代理
- 源站证书：Caddy 自动签发和续期 Let's Encrypt 证书

## 已启用服务

- `api`：FastAPI 授权接口和管理接口
- `postgres`：授权、管理员、设备、版本和审计数据
- `caddy`：HTTPS、静态管理页、反向代理和安全响应头
- 原有 `sadnov2fw` 容器保持不变

## 服务器资源调整

服务器内存约 1GB。部署时创建并启用了 2GB `/swapfile`，设置 `vm.swappiness=10`，并写入开机自动启用配置。

## 管理页能力

- 所有者和子管理员登录
- 创建永久、按天、按自然月授权码
- 一机一码设备绑定查询和远程吊销
- 所有者创建子管理员，默认有效授权额度 100
- 稳定版/测试版版本策略发布
- 授权码明文仅在创建成功时显示一次

## 验收记录

- 本地自动化测试：15 项全部通过
- `GET /health/ready`：返回 `{"status":"ready"}`
- Cloudflare 边缘 HTTPS：证书校验通过，HTTP 200
- VPS 源站 HTTPS：绕过 Cloudflare 直连校验通过，HTTP 200
- 登录页、控制台概览、授权码、设备、子管理员、版本控制页面：浏览器检查通过
- 浏览器控制台：无错误
- 安全响应头：HSTS、CSP、X-Content-Type-Options、X-Frame-Options 已启用

## 运维命令

```bash
cd /opt/xianyuxian/current
docker compose ps
docker compose logs --tail=200 api caddy postgres
docker compose restart
```

`.env` 中包含数据库密码、HMAC 密钥和 Ed25519 私钥，禁止发送、提交 Git 或复制到客户端。客户端只内置 `/v1/public-key` 返回的 Ed25519 公钥。
