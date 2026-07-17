#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="/opt/xianyuxian"
TARGET_DOMAIN=""
ARCHIVE=""

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

latest_archive() {
  find "$SCRIPT_DIR/private" -maxdepth 1 -type f -name 'xianyuxian-license-backup-*.tar.gz' -print \
    | LC_ALL=C sort \
    | tail -n 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      [[ $# -ge 2 ]] || die "--domain 需要参数"
      TARGET_DOMAIN="$2"
      shift 2
      ;;
    --root)
      [[ $# -ge 2 ]] || die "--root 需要参数"
      INSTALL_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      echo "用法: sudo ./restore-debian.sh [备份包] [--domain test.example.com] [--root /opt/xianyuxian]"
      exit 0
      ;;
    *)
      [[ -z "$ARCHIVE" ]] || die "只能指定一个备份包"
      ARCHIVE="$1"
      shift
      ;;
  esac
done

[[ "$EUID" -eq 0 ]] || die "请使用 root 或 sudo 执行"
ARCHIVE="${ARCHIVE:-$(latest_archive)}"
[[ -n "$ARCHIVE" && -f "$ARCHIVE" ]] || die "未找到备份包"
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"

for command_name in docker curl tar sha256sum; do
  command -v "$command_name" >/dev/null || die "缺少命令: $command_name"
done
docker compose version >/dev/null 2>&1 || die "缺少 Docker Compose v2 插件"

if [[ -n "$TARGET_DOMAIN" && ! "$TARGET_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  die "域名格式无效"
fi

[[ ! -e "$INSTALL_ROOT/current" ]] || die "$INSTALL_ROOT/current 已存在，为防止覆盖已停止"
for volume in current_postgres_data current_caddy_data current_caddy_config; do
  if docker volume inspect "$volume" >/dev/null 2>&1; then
    die "Docker 卷 $volume 已存在，为防止覆盖已停止"
  fi
done

echo "[1/8] 校验备份完整性…"
"$SCRIPT_DIR/verify-backup.sh" "$ARCHIVE"

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
tar -xzf "$ARCHIVE" -C "$TEMP_DIR"
BUNDLE_DIR="$TEMP_DIR/xianyuxian-license-backup"

BACKUP_ID="$(awk -F= '$1 == "CREATED_AT" {print $2}' "$BUNDLE_DIR/backup-info.env")"
[[ "$BACKUP_ID" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "备份时间标识无效"
RELEASE_DIR="$INSTALL_ROOT/releases/$BACKUP_ID/license_server"

echo "[2/8] 安装发布快照和密钥…"
mkdir -p "$INSTALL_ROOT/releases/$BACKUP_ID" "$INSTALL_ROOT/secrets" "$INSTALL_ROOT/backups"
cp -a "$BUNDLE_DIR/license_server" "$RELEASE_DIR"
install -m 600 "$BUNDLE_DIR/secrets/license.env" "$INSTALL_ROOT/secrets/license.env"
ln -s "$INSTALL_ROOT/secrets/license.env" "$RELEASE_DIR/.env"
cp -a "$BUNDLE_DIR/database/license.dump" "$INSTALL_ROOT/backups/license-$BACKUP_ID.dump"
chown -R root:root "$INSTALL_ROOT/releases/$BACKUP_ID"
chown root:root "$INSTALL_ROOT/backups/license-$BACKUP_ID.dump"
chmod 600 "$INSTALL_ROOT/backups/license-$BACKUP_ID.dump"

if [[ -n "$TARGET_DOMAIN" ]]; then
  sed -i -E "s|^LICENSE_DOMAIN=.*$|LICENSE_DOMAIN=$TARGET_DOMAIN|" "$INSTALL_ROOT/secrets/license.env"
  sed -i -E "s|^LICENSE_PUBLIC_BASE_URL=.*$|LICENSE_PUBLIC_BASE_URL=https://$TARGET_DOMAIN|" "$INSTALL_ROOT/secrets/license.env"
fi

ln -s "$RELEASE_DIR" "$INSTALL_ROOT/current"
docker compose -p current -f "$INSTALL_ROOT/current/docker-compose.yml" config -q

echo "[3/8] 恢复 Caddy 证书与配置卷…"
docker volume create current_caddy_data >/dev/null
docker volume create current_caddy_config >/dev/null
docker run --rm --entrypoint sh \
  -v current_caddy_data:/restore \
  -v "$BUNDLE_DIR/docker-volumes:/backup:ro" \
  caddy:2.10-alpine -c 'tar -xzf /backup/caddy-data.tar.gz -C /restore'
docker run --rm --entrypoint sh \
  -v current_caddy_config:/restore \
  -v "$BUNDLE_DIR/docker-volumes:/backup:ro" \
  caddy:2.10-alpine -c 'tar -xzf /backup/caddy-config.tar.gz -C /restore'

echo "[4/8] 启动 PostgreSQL…"
docker compose -p current -f "$INSTALL_ROOT/current/docker-compose.yml" up -d postgres
for attempt in $(seq 1 40); do
  if docker compose -p current -f "$INSTALL_ROOT/current/docker-compose.yml" exec -T postgres \
    pg_isready -U license_user -d license_db >/dev/null 2>&1; then
    break
  fi
  [[ "$attempt" -lt 40 ]] || die "PostgreSQL 健康检查超时"
  sleep 2
done

echo "[5/8] 导入授权数据库…"
docker compose -p current -f "$INSTALL_ROOT/current/docker-compose.yml" exec -T postgres \
  pg_restore -U license_user -d license_db --clean --if-exists --no-owner --exit-on-error \
  < "$INSTALL_ROOT/backups/license-$BACKUP_ID.dump"

echo "[6/8] 构建并启动授权 API 和管理面板…"
docker compose -p current -f "$INSTALL_ROOT/current/docker-compose.yml" up -d --build

DOMAIN="${TARGET_DOMAIN:-$(awk -F= '$1 == "LICENSE_DOMAIN" {print $2}' "$INSTALL_ROOT/secrets/license.env")}"
[[ -n "$DOMAIN" ]] || die "无法读取 LICENSE_DOMAIN"

echo "[7/8] 等待 HTTPS 健康检查…"
HEALTHY=0
for attempt in $(seq 1 30); do
  if curl -kfsS --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/health/ready" | grep -q 'ready'; then
    HEALTHY=1
    break
  fi
  sleep 2
done
[[ "$HEALTHY" -eq 1 ]] || die "HTTPS 健康检查失败，请检查 docker compose logs"

echo "[8/8] 恢复完成"
docker compose -p current -f "$INSTALL_ROOT/current/docker-compose.yml" ps
echo
echo "管理面板: https://$DOMAIN"
echo "如果这是正式迁移，现在可以将 Cloudflare 源站 IP 切换到这台机器。"
