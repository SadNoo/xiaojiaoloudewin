# xianyuxian Personal License Server

个人非商业授权中心的第一阶段可运行代码。它与原闲鱼业务服务隔离，负责授权码、设备绑定、远程吊销、离线票据、子管理员额度和客户端版本策略。

## 已实现

- 所有者 CLI 初始化和后台会话登录。
- 所有者创建、查看个人子管理员，默认额度 100。
- 永久、按天数、按自然月授权码；授权码明文只在创建响应中出现一次。
- 授权码 HMAC 索引 + scrypt 校验，不在数据库保存可直接使用的明文。
- 一机一码激活、设备上限拒绝、刷新凭证轮换。
- Ed25519 签名的短期访问凭证和 72 小时离线票据。
- 15 分钟心跳、授权/设备远程吊销、客户端主动停用。
- 稳定/测试版本、最低版本、禁止版本和强制更新字段。
- Ed25519 签名的版本清单，客户端可用同一发布公钥验证。
- 管理操作与客户端授权事件审计。
- SQLite 本地开发和 PostgreSQL 生产连接。
- Dockerfile、Debian VPS Docker Compose 基础配置和自动化测试。
- 同源个人授权管理页：授权码、绑定设备、子管理员和版本策略管理。

TOTP 和数据库迁移属于后续增强项；Windows 客户端授权 SDK 位于 `desktop_client/`。

## 本地启动

要求 Python 3.11+。

```bash
cd license_server
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

python -m app.cli generate-env
python -m app.cli bootstrap-owner --username owner

uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8090
```

开发环境接口文档：`http://127.0.0.1:8090/docs`。

`.env` 包含数据库 HMAC 密钥和 Ed25519 签名私钥，已加入 `.gitignore`。丢失签名私钥会使客户端无法验证新票据；必须通过安全渠道备份，禁止提交 Git。

## 测试

```bash
cd license_server
. .venv/bin/activate
pytest -q
```

## 关键 API

### 管理 API

- `POST /admin/v1/session`
- `POST /admin/v1/admins`
- `GET /admin/v1/admins`
- `POST /admin/v1/licenses`
- `GET /admin/v1/licenses`
- `POST /admin/v1/licenses/{id}/revoke`
- `GET /admin/v1/activations`
- `POST /admin/v1/activations/{id}/revoke`
- `POST /admin/v1/releases`

### 客户端 API

- `POST /v1/licenses/activate`
- `POST /v1/licenses/refresh`
- `POST /v1/licenses/heartbeat`
- `GET /v1/licenses/status`
- `POST /v1/licenses/deactivate`
- `GET /v1/releases/latest`
- `GET /v1/public-key`

## 生产部署提示

1. 将 `.env.example` 复制为 `.env`，生成真实随机密钥并设置 PostgreSQL 密码。
2. `LICENSE_PUBLIC_BASE_URL` 填写实际管理二级域名。
3. 仅通过 Caddy/Nginx 暴露 HTTPS 443，不直接暴露 API 容器端口。
4. 数据库、签名私钥和 HMAC 密钥必须备份；签名私钥与数据库备份分开保存。
5. 当前第一版用 `create_all` 初始化结构，正式生产升级前需加入 Alembic migration。

仓库已提供 `Caddyfile`，默认从 `.env` 读取 `LICENSE_DOMAIN`，并将 `/v1/`、`/admin/v1/` 和 `/health/` 反向代理到内部 API 容器。
