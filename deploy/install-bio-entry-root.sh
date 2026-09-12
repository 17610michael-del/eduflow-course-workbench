#!/usr/bin/env bash
# Prepare (but do NOT start) the 生信（研）8081 and 生信（本）8082 instances.
set -euo pipefail

APP_DIR="/data/kltst/homework/app"

[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo "请使用 sudo 执行此脚本" >&2; exit 1; }

install_instance() {
  local name="$1" data_dir="$2"
  local service_source="$APP_DIR/deploy/homework-${name}.service"
  local nginx_source="$APP_DIR/deploy/nginx-homework-${name}.conf"
  [[ -f "$data_dir/.env" ]] || { echo "缺少 $data_dir/.env" >&2; exit 1; }
  [[ -f "$service_source" && -f "$nginx_source" ]] || { echo "缺少 $name 部署模板" >&2; exit 1; }

  install -d -m 0750 -o kltst -g kltst "$data_dir" "$data_dir/uploads" "$data_dir/server-files"
  chown kltst:kltst "$data_dir/.env"
  chmod 0600 "$data_dir/.env"

  local stamp
  stamp="$(date +%Y%m%dT%H%M%S)"
  [[ ! -e "/etc/systemd/system/homework-${name}.service" ]] \
    || cp -a "/etc/systemd/system/homework-${name}.service" "/etc/systemd/system/homework-${name}.service.$stamp.bak"
  [[ ! -e "/etc/nginx/sites-available/homework-${name}" ]] \
    || cp -a "/etc/nginx/sites-available/homework-${name}" "/etc/nginx/sites-available/homework-${name}.$stamp.bak"
  install -m 0644 "$service_source" "/etc/systemd/system/homework-${name}.service"
  install -m 0644 "$nginx_source" "/etc/nginx/sites-available/homework-${name}"
}

install_instance bio /data/kltst/homework/data-bio
install_instance bio-u /data/kltst/homework/data-bio-u

systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/homework-bio.service
systemd-analyze verify /etc/systemd/system/homework-bio-u.service

# Temporarily include both sites for syntax validation, then return to the
# pre-activation state. No service is enabled, started, restarted, or reloaded.
for name in bio bio-u; do
  LINK="/etc/nginx/sites-enabled/homework-${name}"
  LINK_EXISTED=0
  [[ ! -e "$LINK" && ! -L "$LINK" ]] || LINK_EXISTED=1
  if [[ "$LINK_EXISTED" -eq 0 ]]; then
    ln -s "/etc/nginx/sites-available/homework-${name}" "$LINK"
  fi
  if ! nginx -t; then
    [[ "$LINK_EXISTED" -eq 1 ]] || rm -f "$LINK"
    exit 1
  fi
  [[ "$LINK_EXISTED" -eq 1 ]] || rm -f "$LINK"
done

echo "BIO_ENTRIES_INSTALLED_NOT_STARTED"
echo "激活步骤："
echo "  sudo ln -sfn /etc/nginx/sites-available/homework-bio /etc/nginx/sites-enabled/homework-bio"
echo "  sudo ln -sfn /etc/nginx/sites-available/homework-bio-u /etc/nginx/sites-enabled/homework-bio-u"
echo "  sudo systemctl enable --now homework-bio homework-bio-u"
echo "  sudo systemctl restart homework"
echo "  sudo nginx -t && sudo systemctl reload nginx"
