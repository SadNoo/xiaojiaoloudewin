#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

latest_archive() {
  find "$SCRIPT_DIR/private" -maxdepth 1 -type f -name 'xianyuxian-license-backup-*.tar.gz' -print \
    | LC_ALL=C sort \
    | tail -n 1
}

ARCHIVE="${1:-$(latest_archive)}"
[[ -n "$ARCHIVE" && -f "$ARCHIVE" ]] || die "未找到备份包，请先运行 refresh-from-vps.sh"
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"

command -v tar >/dev/null || die "缺少 tar"
if command -v sha256sum >/dev/null; then
  HASH_COMMAND=(sha256sum)
elif command -v shasum >/dev/null; then
  HASH_COMMAND=(shasum -a 256)
else
  die "缺少 sha256sum 或 shasum"
fi

if [[ -f "$ARCHIVE.sha256" ]]; then
  EXPECTED="$(awk '{print $1}' "$ARCHIVE.sha256")"
  ACTUAL="$("${HASH_COMMAND[@]}" "$ARCHIVE" | awk '{print $1}')"
  [[ "$EXPECTED" == "$ACTUAL" ]] || die "备份包 SHA-256 不匹配"
  echo "[OK] 外层 SHA-256: $ACTUAL"
fi

if tar -tzf "$ARCHIVE" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  die "备份包包含不安全路径"
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
tar -xzf "$ARCHIVE" -C "$TEMP_DIR"
BUNDLE_DIR="$TEMP_DIR/xianyuxian-license-backup"
[[ -d "$BUNDLE_DIR" ]] || die "备份包结构无效"
[[ -f "$BUNDLE_DIR/SHA256SUMS" ]] || die "缺少包内 SHA256SUMS"

if command -v sha256sum >/dev/null; then
  (cd "$BUNDLE_DIR" && sha256sum -c SHA256SUMS)
else
  (cd "$BUNDLE_DIR" && shasum -a 256 -c SHA256SUMS)
fi

for required in \
  backup-info.env \
  license_server/docker-compose.yml \
  license_server/Dockerfile \
  license_server/app/main.py \
  license_server/web/index.html \
  secrets/license.env \
  database/license.dump \
  docker-volumes/caddy-data.tar.gz \
  docker-volumes/caddy-config.tar.gz; do
  [[ -f "$BUNDLE_DIR/$required" ]] || die "备份缺少 $required"
done

for env_name in \
  POSTGRES_PASSWORD \
  LICENSE_DOMAIN \
  LICENSE_HMAC_SECRET \
  LICENSE_SIGNING_PRIVATE_KEY \
  LICENSE_PUBLIC_BASE_URL; do
  if ! awk -F= -v key="$env_name" '$1 == key && length(substr($0, index($0, "=") + 1)) > 0 {found=1} END {exit !found}' \
    "$BUNDLE_DIR/secrets/license.env"; then
    die "license.env 缺少非空配置: $env_name"
  fi
done

tar -tzf "$BUNDLE_DIR/docker-volumes/caddy-data.tar.gz" >/dev/null
tar -tzf "$BUNDLE_DIR/docker-volumes/caddy-config.tar.gz" >/dev/null

if command -v pg_restore >/dev/null; then
  pg_restore --list "$BUNDLE_DIR/database/license.dump" >/dev/null
fi

echo
echo "[OK] 备份包结构、关键配置和所有文件校验通过"
sed -n '1,20p' "$BUNDLE_DIR/backup-info.env"
