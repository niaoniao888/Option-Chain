#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
BACKUP_DIR=${OPTIONS_BACKUP_DIR:-"$PROJECT_DIR/backups"}
COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-options-panel}
export COMPOSE_PROJECT_NAME
cd "$PROJECT_DIR"

die() { printf '%s\n' "错误：$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "缺少命令：$1"; }
compose() { docker compose "$@"; }
unsafe_state() {
    ids=$(compose ps --all -q options-panel 2>/dev/null || true)
    [ -z "$ids" ] && return 1
    for id in $ids; do
      state=$(docker inspect --format '{{.State.Status}}' "$id")
      case "$state" in running|restarting|paused) return 0 ;; esac
    done
    return 1
}
require_stopped() { unsafe_state && die "主服务仍在运行、重启或暂停；请先执行 $0 stop" || true; }
health() { compose exec -T options-panel python -c "import os,urllib.request; from options_panel.config import normalize_base_path; p=normalize_base_path(os.environ.get('OPTIONS_BASE_PATH','')); urllib.request.urlopen('http://127.0.0.1:8780'+p+'/healthz',timeout=5).read()"; }

check() {
    need docker
    docker info >/dev/null 2>&1 || die "Docker daemon 不可用或当前用户无权限"
    docker compose version >/dev/null 2>&1 || die "需要 Docker Compose v2"
    [ -f .env ] || die "缺少 .env；先执行 cp .env.example .env 并填写真实域名"
    compose config --quiet
    printf '%s\n' "环境检查通过（配置内容未输出）。"
}

case "${1:-}" in
  check) check ;;
  start)
    check
    compose up -d --build --remove-orphans
    attempts=0
    until health >/dev/null 2>&1; do
      attempts=$((attempts + 1)); [ "$attempts" -lt 40 ] || die "服务未在限定时间内通过 healthz"
      sleep 2
    done
    printf '%s\n' "服务已启动；请按 .env 中的端口和 OPTIONS_BASE_PATH 访问。"
    ;;
  status) compose ps; health && printf '%s\n' "healthz: 200" ;;
  logs) compose logs --tail "${2:-200}" options-panel ;;
  stop) compose stop --timeout 300 options-panel ;;
  backup)
    check; require_stopped; mkdir -p "$BACKUP_DIR"
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    name="options-panel-data-$stamp.tar.gz"
    temporary="$BACKUP_DIR/.$name.tmp"
    if compose run --rm --no-deps -T options-panel \
      python -m options_panel.runtime_archive backup /app/runtime/us-equities/data - > "$temporary"; then
      mv "$temporary" "$BACKUP_DIR/$name"
    else
      rm -f "$temporary"; exit 1
    fi
    printf '%s\n' "备份已创建：$BACKUP_DIR/$name"
    ;;
  restore)
    [ "$#" -eq 2 ] || die "用法：$0 restore /绝对路径/备份.tar.gz"
    check; require_stopped
    archive=$(readlink -f -- "$2")
    [ -f "$archive" ] || die "备份文件不存在：$2"
    mkdir -p "$BACKUP_DIR"
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    safety="pre-restore-$stamp.tar.gz"
    temporary="$BACKUP_DIR/.$safety.tmp"
    if compose run --rm --no-deps -T options-panel \
      python -m options_panel.runtime_archive backup /app/runtime/us-equities/data - > "$temporary"; then
      mv "$temporary" "$BACKUP_DIR/$safety"
    else
      rm -f "$temporary"; exit 1
    fi
    compose run --rm --no-deps -T options-panel \
      python -m options_panel.runtime_archive restore - /app/runtime/us-equities/data < "$archive"
    printf '%s\n' "恢复完成；恢复前备份：$BACKUP_DIR/$safety。数据卷保留，服务仍停止。"
    ;;
  *)
    printf '%s\n' "用法：$0 {check|start|status|logs [行数]|stop|backup|restore 备份.tar.gz}" >&2
    exit 2
    ;;
esac
