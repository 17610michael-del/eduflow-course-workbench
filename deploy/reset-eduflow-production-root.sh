#!/usr/bin/env bash
set -euo pipefail

# One-shot, guarded production reset for the 193 EduFlow host.
CONFIRMATION="CONFIRM-PRODUCTION-RESET"
APP_DIR=/data/kltst/homework/app
DATA_DIR=/data/kltst/homework/data
DATABASE="$DATA_DIR/app.db"
UPLOAD_DIR="$DATA_DIR/uploads"
SERVER_FILES="$DATA_DIR/server-files"
WORKBENCH_DB=/data/kltst/homework/services/deepseek-hapi/workbench.db
HAPI_ENV_DIR=/etc/eduflow-hapi
BACKUP_BASE=/var/backups/eduflow-launch-reset
WSST_UID=1010
WSST_GID=1014
PUBLIC_DOMAIN_SUFFIX=47.96.100.122.nip.io
DELETE_USERS=(michaelk kentnf student01 student02 student03 student04 student05 assistant01 assistant02)

usage() {
  echo "用法：sudo $0 $CONFIRMATION" >&2
}

die() {
  echo "RESET_FAILED: $*" >&2
  exit 1
}

if [[ "$EUID" -ne 0 ]]; then
  die "请由用户在 193 终端中使用 sudo 执行；不要把密码发到聊天中。"
fi
if [[ "${1:-}" != "$CONFIRMATION" || "$#" -ne 1 ]]; then
  usage
  exit 2
fi

[[ -d "$APP_DIR" ]] || die "正式应用目录不存在：$APP_DIR"
[[ -f "$DATABASE" ]] || die "正式数据库不存在：$DATABASE"
[[ ! -L "$DATABASE" ]] || die "拒绝处理符号链接数据库：$DATABASE"
[[ -f "$APP_DIR/.env" ]] || die "正式环境文件不存在：$APP_DIR/.env"
[[ -x "$APP_DIR/venv/bin/python" ]] || die "正式 Python 虚拟环境不存在"
[[ -f "$APP_DIR/deploy/reset-eduflow-production.py" ]] || die "数据库重置工具尚未部署"
[[ -x /data/kltst/homework/services/hapi/native/hapi ]] || die "HAPI 原生程序不存在"
[[ -s /etc/eduflow-ai/deepseek.env ]] || die "DeepSeek 环境文件不存在"
getent passwd kltst >/dev/null || die "kltst Linux 账号不存在"
[[ "$(id -u kltst)" == "1001" ]] || die "kltst UID 不再是 1001，停止执行"
getent group teacher >/dev/null || die "teacher 组不存在"
[[ ! -L "$UPLOAD_DIR" ]] || die "拒绝清理符号链接上传目录：$UPLOAD_DIR"

for username in "${DELETE_USERS[@]}"; do
  if getent passwd "$username" >/dev/null; then
    uid_number=$(id -u "$username")
    home_dir=$(getent passwd "$username" | cut -d: -f6)
    [[ "$uid_number" -ge 1000 ]] || die "拒绝删除系统 UID：$username=$uid_number"
    [[ "$home_dir" == "/home/$username" ]] || die "账号家目录超出允许范围：$username=$home_dir"
    mountpoint --quiet "$home_dir" && die "拒绝删除挂载点家目录：$home_dir"
    mountpoint --quiet "/data/$username" && die "拒绝删除挂载点数据目录：/data/$username"
  fi
done

if getent passwd wsst >/dev/null; then
  [[ "$(id -u wsst)" == "$WSST_UID" ]] || die "现有 wsst UID 不是 $WSST_UID"
else
  getent passwd "$WSST_UID" >/dev/null && die "UID $WSST_UID 已被占用"
  if find /home /data -uid "$WSST_UID" -print -quit 2>/dev/null | grep -q .; then
    die "UID $WSST_UID 仍拥有文件"
  fi
fi
if getent group wsst >/dev/null; then
  [[ "$(getent group wsst | cut -d: -f3)" == "$WSST_GID" ]] || die "现有 wsst GID 不正确"
elif getent group "$WSST_GID" >/dev/null; then
  die "计划使用的 GID $WSST_GID 已被占用"
fi

install -d -m 0700 -o root -g root "$BACKUP_BASE"
estimated_bytes=$(stat -c %s "$DATABASE")
estimated_bytes=$((estimated_bytes * 2))
for path in "$UPLOAD_DIR" "$HAPI_ENV_DIR"; do
  if [[ -e "$path" ]]; then
    size=$(du -sb -- "$path" | cut -f1)
    estimated_bytes=$((estimated_bytes + size))
  fi
done
for username in "${DELETE_USERS[@]}"; do
  for path in "/home/$username" "/data/$username"; do
    if [[ -e "$path" ]]; then
      size=$(du -sb -- "$path" | cut -f1)
      estimated_bytes=$((estimated_bytes + size))
    fi
  done
done
for path in /home/kltst/.hapi-hub /home/kltst/.hapi-runner /home/kltst/.config/eduflow-hapi \
            /home/wsst/.hapi-hub /home/wsst/.hapi-runner /home/wsst/.config/eduflow-hapi; do
  if [[ -e "$path" ]]; then
    size=$(du -sb -- "$path" | cut -f1)
    estimated_bytes=$((estimated_bytes + size))
  fi
done
if [[ -e "$WORKBENCH_DB" ]]; then
  size=$(stat -c %s "$WORKBENCH_DB")
  estimated_bytes=$((estimated_bytes + size))
fi
required_bytes=$((estimated_bytes * 2 + 268435456))
available_bytes=$(df --output=avail -B1 "$BACKUP_BASE" | tail -n 1 | tr -d ' ')
[[ "$available_bytes" =~ ^[0-9]+$ && "$available_bytes" -ge "$required_bytes" ]] \
  || die "备份分区空间不足：需要至少 $required_bytes 字节，可用 $available_bytes 字节"
curl --silent --fail --max-time 5 http://127.0.0.1:8000/login >/dev/null \
  || die "重置前 EduFlow 登录页不可用"

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="$BACKUP_BASE/$timestamp"
[[ ! -e "$BACKUP_DIR" ]] || die "备份目录已存在：$BACKUP_DIR"
install -d -m 0700 -o root -g root "$BACKUP_DIR"
homework_stopped=0
on_exit() {
  status=$?
  trap - EXIT
  if [[ "$status" -ne 0 ]]; then
    if [[ "$homework_stopped" -eq 1 ]]; then
      systemctl restart homework.service 2>/dev/null || true
      for username in kltst "${DELETE_USERS[@]}"; do
        if getent passwd "$username" >/dev/null && [[ -f "$HAPI_ENV_DIR/$username.env" ]]; then
          systemctl is-enabled --quiet "eduflow-hapi-hub@$username.service" \
            && systemctl restart "eduflow-hapi-hub@$username.service" 2>/dev/null || true
          systemctl is-enabled --quiet "eduflow-hapi-runner@$username.service" \
            && systemctl restart "eduflow-hapi-runner@$username.service" 2>/dev/null || true
        fi
      done
    fi
    echo "RESET_ABORTED backup=$BACKUP_DIR homework_restart_attempted=$homework_stopped" >&2
  fi
  exit "$status"
}
trap on_exit EXIT

echo "RESET_PHASE=record-and-stop"
{
  hostname
  date -u --iso-8601=seconds
  systemctl is-enabled homework.service 2>/dev/null || true
  systemctl is-active homework.service 2>/dev/null || true
  for username in kltst "${DELETE_USERS[@]}"; do
    getent passwd "$username" || true
  done
} >"$BACKUP_DIR/pre-reset-state.txt"
chmod 0600 "$BACKUP_DIR/pre-reset-state.txt"
"$APP_DIR/venv/bin/python" "$APP_DIR/deploy/reset-eduflow-production.py" \
  --database "$DATABASE" --backup "$BACKUP_DIR/preflight-unused.db"
[[ ! -e "$BACKUP_DIR/preflight-unused.db" ]] || die "数据库干跑意外创建了备份文件"
systemctl list-unit-files 'homework.service' 'eduflow-hapi-*.service' \
  'eduflow-project-agent@.service' 'eduflow-hangzhou-tunnel.service' \
  >"$BACKUP_DIR/systemd-unit-state.txt" 2>&1 || true
chmod 0600 "$BACKUP_DIR/systemd-unit-state.txt"
install -d -m 0700 -o root -g root "$BACKUP_DIR/systemd-units"
for unit_path in /etc/systemd/system/homework.service \
                 /etc/systemd/system/eduflow-hapi-hub@.service \
                 /etc/systemd/system/eduflow-hapi-runner@.service \
                 /etc/systemd/system/eduflow-project-agent@.service \
                 /etc/systemd/system/eduflow-hangzhou-tunnel.service; do
  [[ -e "$unit_path" ]] && cp -a -- "$unit_path" "$BACKUP_DIR/systemd-units/"
done

server_file_count_before=0
if [[ -d "$SERVER_FILES" ]]; then
  server_file_count_before=$(find "$SERVER_FILES" -type f -printf . | wc -c)
fi

systemctl stop homework.service
homework_stopped=1
for username in kltst "${DELETE_USERS[@]}"; do
  systemctl stop "eduflow-hapi-runner@$username.service" 2>/dev/null || true
  systemctl stop "eduflow-hapi-hub@$username.service" 2>/dev/null || true
  systemctl stop "eduflow-project-agent@$username.service" 2>/dev/null || true
done
systemctl disable eduflow-project-agent@kltst.service 2>/dev/null || true
pkill -TERM -u kltst -f 'gunicorn.*0\.0\.0\.0:3066.*subsystems\.deepseek_hapi\.app:app' 2>/dev/null || true
sleep 2
pkill -KILL -u kltst -f 'gunicorn.*0\.0\.0\.0:3066.*subsystems\.deepseek_hapi\.app:app' 2>/dev/null || true
if ss -ltn | grep -q ':3066 '; then
  die "3066 进程未停止"
fi

echo "RESET_PHASE=backup"
install -m 0600 -o root -g root "$APP_DIR/.env" "$BACKUP_DIR/app.env"
[[ -d "$UPLOAD_DIR" ]] && tar -czpf "$BACKUP_DIR/uploads.tar.gz" --acls --xattrs --numeric-owner "$UPLOAD_DIR"
if [[ -e "$WORKBENCH_DB" ]]; then
  "$APP_DIR/venv/bin/python" - "$WORKBENCH_DB" "$BACKUP_DIR/workbench.db.sqlite-backup" <<'PY'
import pathlib
import sqlite3
import sys

source_path, backup_path = map(pathlib.Path, sys.argv[1:])
source = sqlite3.connect(source_path)
backup = sqlite3.connect(backup_path)
source.backup(backup)
backup.close()
source.close()
check = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
result = check.execute("PRAGMA integrity_check").fetchone()[0]
check.close()
if result != "ok":
    raise SystemExit(f"workbench backup integrity check failed: {result}")
backup_path.chmod(0o600)
PY
fi
[[ -d "$HAPI_ENV_DIR" ]] && cp -a -- "$HAPI_ENV_DIR" "$BACKUP_DIR/eduflow-hapi"

archive_paths=()
for username in "${DELETE_USERS[@]}"; do
  if getent passwd "$username" >/dev/null; then
    home_dir=$(getent passwd "$username" | cut -d: -f6)
    [[ -e "$home_dir" ]] && archive_paths+=("$home_dir")
  fi
  [[ -e "/data/$username" ]] && archive_paths+=("/data/$username")
done
for path in /home/kltst/.hapi-hub /home/kltst/.hapi-runner /home/kltst/.config/eduflow-hapi \
            /home/wsst/.hapi-hub /home/wsst/.hapi-runner /home/wsst/.config/eduflow-hapi; do
  [[ -e "$path" ]] && archive_paths+=("$path")
done
if [[ "${#archive_paths[@]}" -gt 0 ]]; then
  tar -czpf "$BACKUP_DIR/user-directories.tar.gz" --acls --xattrs --numeric-owner "${archive_paths[@]}"
  tar -tzf "$BACKUP_DIR/user-directories.tar.gz" >/dev/null
else
  : >"$BACKUP_DIR/no-user-directories-present"
fi

{
  for username in kltst wsst "${DELETE_USERS[@]}"; do
    getent passwd "$username" || true
  done
  getent group teacher || true
  getent group assistant || true
} >"$BACKUP_DIR/account-records.txt"
chmod 0600 "$BACKUP_DIR/account-records.txt"

echo "RESET_PHASE=create-wsst"
if ! getent group wsst >/dev/null; then
  groupadd --gid "$WSST_GID" wsst
fi
if ! getent passwd wsst >/dev/null; then
  useradd --create-home --uid "$WSST_UID" --gid "$WSST_GID" --shell /bin/bash wsst
fi
usermod --append --groups teacher wsst
usermod --append --groups assistant kltst
gpasswd --delete kltst teacher >/dev/null 2>&1 || true
passwd --lock wsst >/dev/null
install -d -m 0750 -o wsst -g wsst /data/wsst
[[ "$(id -u wsst)" == "$WSST_UID" && "$(id -g wsst)" == "$WSST_GID" ]] \
  || die "wsst UID/GID 验证失败"

echo "RESET_PHASE=configure-login-boundary"
"$APP_DIR/venv/bin/python" - "$APP_DIR/.env" <<'PY'
import os
import pathlib
import secrets
import sys

path = pathlib.Path(sys.argv[1])
updates = {
    "ALLOWED_USERS": "kltst,wsst",
    "TEACHERS": "wsst",
    "ASSISTANTS": "kltst",
    "DEGREE_USERS": "kltst",
    "BIOINFORMATICS_USERS": "",
    "BIOINFORMATICS_ASSISTANTS": "kltst",
    "COURSE_ONLY_SLUG": "degree",
    "SESSION_COOKIE_NAME": "eduflow_degree_session",
    "REMEMBER_COOKIE_NAME": "eduflow_degree_remember",
    "LOGIN_HINT_COOKIE_PREFIX": "degree_",
    "SEED_DEMO_DATA": "0",
    "DEEPSEEK_3066_MENU_ENABLED": "0",
    "HAPI_PORT_BASE": "32000",
    "HAPI_PUBLIC_URL_TEMPLATE": "https://hapi-{username}.47.96.100.122.nip.io/",
    "SECRET_KEY": secrets.token_hex(32),
    "PROJECT_AGENT_TOKEN_SECRET": secrets.token_hex(32),
}
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
output = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
    if key in updates:
        if key not in seen:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
    else:
        output.append(line)
for key, value in updates.items():
    if key not in seen:
        output.append(f"{key}={value}")
temporary = path.parent / (path.name + ".reset-tmp")
temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
temporary.replace(path)
PY
chown kltst:kltst "$APP_DIR/.env"
chmod 0600 "$APP_DIR/.env"

echo "RESET_PHASE=database"
"$APP_DIR/venv/bin/python" "$APP_DIR/deploy/reset-eduflow-production.py" \
  --database "$DATABASE" --backup "$BACKUP_DIR/app.db.sqlite-backup" --apply
chown kltst:kltst "$DATABASE"
chmod 0600 "$DATABASE"
rm -f -- "$DATABASE-wal" "$DATABASE-shm"

echo "RESET_PHASE=delete-old-accounts"
for username in "${DELETE_USERS[@]}"; do
  if ! getent passwd "$username" >/dev/null; then
    rm -rf -- "/data/$username"
    rm -f -- "$HAPI_ENV_DIR/$username.env"
    continue
  fi
  systemctl disable "eduflow-hapi-runner@$username.service" 2>/dev/null || true
  systemctl disable "eduflow-hapi-hub@$username.service" 2>/dev/null || true
  systemctl disable "eduflow-project-agent@$username.service" 2>/dev/null || true
  loginctl disable-linger "$username" 2>/dev/null || true
  loginctl terminate-user "$username" 2>/dev/null || true
  pkill -TERM -u "$username" 2>/dev/null || true
  sleep 1
  pkill -KILL -u "$username" 2>/dev/null || true
  crontab -r -u "$username" 2>/dev/null || true
  userdel --remove "$username"
  rm -rf -- "/data/$username"
  rm -f -- "$HAPI_ENV_DIR/$username.env"
  if getent group "$username" >/dev/null; then
    groupdel "$username" 2>/dev/null || true
  fi
  getent passwd "$username" >/dev/null && die "账号删除失败：$username"
done

echo "RESET_PHASE=clear-files-and-secrets"
if [[ -d "$UPLOAD_DIR" ]]; then
  find "$UPLOAD_DIR" -mindepth 1 -delete
else
  install -d -m 0750 -o kltst -g kltst "$UPLOAD_DIR"
fi
chown kltst:kltst "$UPLOAD_DIR"
chmod 0750 "$UPLOAD_DIR"
rm -f -- "$WORKBENCH_DB" "$WORKBENCH_DB-wal" "$WORKBENCH_DB-shm"
rm -rf -- /home/kltst/.hapi-hub /home/kltst/.hapi-runner /home/kltst/.config/eduflow-hapi
rm -rf -- /home/wsst/.hapi-hub /home/wsst/.hapi-runner /home/wsst/.config/eduflow-hapi
find "$HAPI_ENV_DIR" -maxdepth 1 -type f -name '*.env' -delete
rm -f -- "$HAPI_ENV_DIR/token-secret"

echo "RESET_PHASE=install-hapi"
HAPI_SERVER_HOST=10.98.103.193 HAPI_PORT_BASE=32000 HAPI_LISTEN_HOST=127.0.0.1 \
  HAPI_PUBLIC_DOMAIN_SUFFIX="$PUBLIC_DOMAIN_SUFFIX" \
  "$APP_DIR/deploy/hapi/install-hapi-runners-root.sh" kltst wsst

echo "RESET_PHASE=restart-and-verify"
systemctl daemon-reload
systemctl restart homework.service
systemctl is-active --quiet homework.service || die "homework.service 未启动"
systemctl is-active --quiet eduflow-hapi-hub@kltst.service || die "kltst Hub 未启动"
systemctl is-active --quiet eduflow-hapi-runner@kltst.service || die "kltst Runner 未启动"
systemctl is-active --quiet eduflow-hapi-hub@wsst.service || die "wsst Hub 未启动"
systemctl is-active --quiet eduflow-hapi-runner@wsst.service || die "wsst Runner 未启动"
curl --silent --fail --max-time 5 http://127.0.0.1:32001/ >/dev/null || die "kltst HAPI 32001 不可用"
curl --silent --fail --max-time 5 http://127.0.0.1:32010/ >/dev/null || die "wsst HAPI 32010 不可用"
homework_ready=0
for _ in $(seq 1 40); do
  if curl --silent --fail --max-time 2 http://127.0.0.1:8000/login >/dev/null; then
    homework_ready=1
    break
  fi
  sleep 0.5
done
[[ "$homework_ready" -eq 1 ]] || die "EduFlow 登录页不可用"
ss -ltn | grep -q ':3066 ' && die "3066 仍在监听"

server_file_count_after=0
if [[ -d "$SERVER_FILES" ]]; then
  server_file_count_after=$(find "$SERVER_FILES" -type f -printf . | wc -c)
fi
[[ "$server_file_count_before" == "$server_file_count_after" ]] \
  || die "server-files 文件数量发生变化"

for username in "${DELETE_USERS[@]}"; do
  getent passwd "$username" >/dev/null && die "旧账号仍存在：$username"
  [[ ! -e "/data/$username" ]] || die "旧数据目录仍存在：/data/$username"
done
[[ "$(id -u wsst)" == "$WSST_UID" ]] || die "wsst UID 最终验证失败"

find "$BACKUP_DIR" -type f ! -name SHA256SUMS -exec sha256sum {} + >"$BACKUP_DIR/SHA256SUMS"
chmod 0600 "$BACKUP_DIR/SHA256SUMS"
sync
trap - EXIT
echo "RESET_CORE_OK backup=$BACKUP_DIR"
echo "NEXT_REQUIRED: sudo passwd wsst"
echo "NEXT_REQUIRED: 更新杭州 Caddy/permitlisten 与反向隧道，仅保留 18080,32001,32010,38080"
