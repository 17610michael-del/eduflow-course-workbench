#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${APP_ROOT:-/opt/eduflow}"
BACKUP_DIR="${BACKUP_DIR:-$APP_ROOT/backup}"
mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/$(date +%F).tar.gz" -C "$APP_ROOT" data
find "$BACKUP_DIR" -type f -name '*.tar.gz' -mtime +30 -delete
