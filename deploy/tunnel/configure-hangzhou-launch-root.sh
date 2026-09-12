#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
CADDY_SOURCE="$SCRIPT_DIR/Caddyfile.hangzhou"
CADDY_TARGET=/etc/caddy/Caddyfile
AUTHORIZED_KEYS=/home/eduflow-tunnel/.ssh/authorized_keys
BACKUP_BASE=/var/backups/eduflow-hangzhou-launch
PERMITTED_PORTS=(18080 32001 32010 38080)

die() {
  echo "HANGZHOU_CONFIG_FAILED: $*" >&2
  exit 1
}

[[ "$EUID" -eq 0 ]] || die "请由 root 执行"
[[ -f "$CADDY_SOURCE" ]] || die "缺少 Caddy 配置候选文件"
[[ -f "$CADDY_TARGET" ]] || die "现有 Caddy 配置不存在"
[[ -f "$AUTHORIZED_KEYS" ]] || die "专用隧道 authorized_keys 不存在"
command -v caddy >/dev/null || die "caddy 命令不存在"
command -v ssh-keygen >/dev/null || die "ssh-keygen 命令不存在"
systemctl is-active --quiet caddy.service || die "caddy.service 当前未运行"
caddy validate --config "$CADDY_SOURCE" --adapter caddyfile >/dev/null

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="$BACKUP_BASE/$timestamp"
install -d -m 0700 -o root -g root "$backup_dir"
cp -a -- "$CADDY_TARGET" "$backup_dir/Caddyfile"
cp -a -- "$AUTHORIZED_KEYS" "$backup_dir/authorized_keys"
fingerprint_before=$(ssh-keygen -lf "$AUTHORIZED_KEYS")

restore_on_exit() {
  status=$?
  trap - EXIT INT TERM HUP
  if [[ "$status" -ne 0 ]]; then
    install -m 0644 -o root -g root "$backup_dir/Caddyfile" "$CADDY_TARGET" || true
    install -m 0600 -o eduflow-tunnel -g eduflow-tunnel \
      "$backup_dir/authorized_keys" "$AUTHORIZED_KEYS" || true
    systemctl reload caddy.service 2>/dev/null || true
    echo "HANGZHOU_CONFIG_ROLLED_BACK backup=$backup_dir" >&2
  fi
  exit "$status"
}
trap restore_on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

python3 - "$AUTHORIZED_KEYS" <<'PY'
import os
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
indexes = [
    index
    for index, line in enumerate(lines)
    if line.strip() and not line.lstrip().startswith("#") and "eduflow-hangzhou-tunnel" in line
]
if len(indexes) != 1:
    raise SystemExit(f"expected one EduFlow tunnel key, found {len(indexes)}")
index = indexes[0]
line = lines[index]
match = re.search(r"(?:^|\s)(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+)\s", line)
if not match:
    raise SystemExit("unable to locate SSH key type")
prefix = line[: match.start()].strip().rstrip(",")
key_and_comment = line[match.start() :].lstrip()
options = [item for item in prefix.split(",") if item and not item.startswith("permitlisten=")]
options.extend(
    f'permitlisten="127.0.0.1:{port}"' for port in (18080, 32001, 32010, 38080)
)
lines[index] = ",".join(options) + " " + key_and_comment
temporary = path.parent / (path.name + ".launch-tmp")
temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
temporary.replace(path)
PY
chown eduflow-tunnel:eduflow-tunnel "$AUTHORIZED_KEYS"
chmod 0600 "$AUTHORIZED_KEYS"

fingerprint_after=$(ssh-keygen -lf "$AUTHORIZED_KEYS")
[[ "$fingerprint_before" == "$fingerprint_after" ]] || die "隧道公钥指纹发生变化"

mapfile -t actual_permits < <(grep -oE 'permitlisten="127\.0\.0\.1:[0-9]+"' "$AUTHORIZED_KEYS" | sort -u)
expected_permits=()
for port in "${PERMITTED_PORTS[@]}"; do
  expected_permits+=("permitlisten=\"127.0.0.1:$port\"")
done
mapfile -t expected_permits < <(printf '%s\n' "${expected_permits[@]}" | sort -u)
[[ "${actual_permits[*]}" == "${expected_permits[*]}" ]] || die "PermitListen 集合验证失败"

install -m 0644 -o root -g root "$CADDY_SOURCE" "$CADDY_TARGET"
caddy validate --config "$CADDY_TARGET" --adapter caddyfile >/dev/null
systemctl reload caddy.service
systemctl is-active --quiet caddy.service || die "Caddy reload 后未运行"

trap - EXIT INT TERM HUP
echo "HANGZHOU_LAUNCH_CONFIG_OK backup=$backup_dir ports=${PERMITTED_PORTS[*]}"
