#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PRIVATE_DIR="$SCRIPT_DIR/private"
VPS_HOST="${VPS_HOST:-177.0.143.19}"
VPS_USER="${VPS_USER:-root}"
VPS_PORT="${VPS_PORT:-22}"
SSH_KEY="${SSH_KEY:-$PROJECT_ROOT/xianyuxian.pem}"
BACKUP_ID="${BACKUP_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
REMOTE_TMP="/tmp/xianyuxian-license-backup-$BACKUP_ID"
REMOTE="$VPS_USER@$VPS_HOST"

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

for command_name in ssh tar shasum; do
  command -v "$command_name" >/dev/null || die "缺少本地命令: $command_name"
done
[[ -f "$SSH_KEY" ]] || die "SSH 私钥不存在: $SSH_KEY"

mkdir -p "$PRIVATE_DIR"
LOCAL_TEMP="$(mktemp -d)"
STAGE="$LOCAL_TEMP/xianyuxian-license-backup"
mkdir -p "$STAGE/license_server" "$STAGE/secrets" "$STAGE/database" "$STAGE/docker-volumes"

SSH_ARGS=(ssh -i "$SSH_KEY" -p "$VPS_PORT" -o StrictHostKeyChecking=no -o PasswordAuthentication=no -o IdentitiesOnly=yes)

cleanup() {
  rm -rf "$LOCAL_TEMP"
}
trap cleanup EXIT

echo "[1/5] 在 VPS 上生成一致性快照并通过单连接下载…"
"${SSH_ARGS[@]}" "$REMOTE" "set -e; \
  rm -rf '$REMOTE_TMP'; \
  mkdir -p '$REMOTE_TMP'; \
  docker exec current-postgres-1 pg_dump -Fc -U license_user -d license_db > '$REMOTE_TMP/license.dump'; \
  docker exec -i current-postgres-1 pg_restore --list < '$REMOTE_TMP/license.dump' >/dev/null; \
  tar --exclude='.env' --exclude='.venv*' --exclude='data' --exclude='__pycache__' --exclude='.pytest_cache' -czf '$REMOTE_TMP/license-server.tar.gz' -C /opt/xianyuxian/current .; \
  tar -czf '$REMOTE_TMP/caddy-data.tar.gz' -C /var/lib/docker/volumes/current_caddy_data/_data .; \
  tar -czf '$REMOTE_TMP/caddy-config.tar.gz' -C /var/lib/docker/volumes/current_caddy_config/_data .; \
  cp /opt/xianyuxian/secrets/license.env '$REMOTE_TMP/license.env'; \
  chmod 600 '$REMOTE_TMP/license.dump' '$REMOTE_TMP/license.env'; \
  tar -czf - -C '$REMOTE_TMP' .; \
  rm -rf '$REMOTE_TMP'" > "$LOCAL_TEMP/vps-snapshot.tar.gz"

echo "[2/5] 解包数据库、密钥、源码和 Caddy 卷…"
mkdir -p "$LOCAL_TEMP/vps-snapshot"
tar -xzf "$LOCAL_TEMP/vps-snapshot.tar.gz" -C "$LOCAL_TEMP/vps-snapshot"
mv "$LOCAL_TEMP/vps-snapshot/license.dump" "$STAGE/database/license.dump"
mv "$LOCAL_TEMP/vps-snapshot/license.env" "$STAGE/secrets/license.env"
mv "$LOCAL_TEMP/vps-snapshot/caddy-data.tar.gz" "$STAGE/docker-volumes/caddy-data.tar.gz"
mv "$LOCAL_TEMP/vps-snapshot/caddy-config.tar.gz" "$STAGE/docker-volumes/caddy-config.tar.gz"
tar -xzf "$LOCAL_TEMP/vps-snapshot/license-server.tar.gz" -C "$STAGE/license_server"

echo "[3/5] 写入备份元数据…"
GIT_COMMIT="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
cat > "$STAGE/backup-info.env" <<EOF
BACKUP_FORMAT_VERSION=1
CREATED_AT=$BACKUP_ID
SOURCE_HOST=$VPS_HOST
SOURCE_DOMAIN=xianyuxian.dskjahf.xyz
GIT_COMMIT=$GIT_COMMIT
EOF

echo "[4/5] 生成包内和外层 SHA-256…"
(
  cd "$STAGE"
  find . -type f ! -name SHA256SUMS -print | LC_ALL=C sort | while IFS= read -r file; do
    shasum -a 256 "$file"
  done > SHA256SUMS
)

ARCHIVE_NAME="xianyuxian-license-backup-$BACKUP_ID.tar.gz"
ARCHIVE_PATH="$PRIVATE_DIR/$ARCHIVE_NAME"
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE_PATH" -C "$LOCAL_TEMP" xianyuxian-license-backup
(
  cd "$PRIVATE_DIR"
  shasum -a 256 "$ARCHIVE_NAME" > "$ARCHIVE_NAME.sha256"
)
chmod 600 "$ARCHIVE_PATH" "$ARCHIVE_PATH.sha256"

echo "[5/5] 本地备份校验…"
"$SCRIPT_DIR/verify-backup.sh" "$ARCHIVE_PATH"
echo
echo "[DONE] $ARCHIVE_PATH"
