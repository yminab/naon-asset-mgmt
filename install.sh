#!/usr/bin/env bash
set -Eeuo pipefail
[ "$EUID" -eq 0 ]||{ echo 'sudo ./install.sh';exit 1;};HERE="$(cd "$(dirname "$0")"&&pwd)";APP=/opt/security-assets
read -r -p 'DB 사용자 [securityweb]: ' DB_USER;DB_USER=${DB_USER:-securityweb};read -r -s -p 'DB 비밀번호: ' DB_PASSWORD;echo;read -r -p '관리자 계정 [admin]: ' ADMIN;ADMIN=${ADMIN:-admin};read -r -p '관리자 이름 [관리자]: ' ADMIN_NAME;ADMIN_NAME=${ADMIN_NAME:-관리자};read -r -s -p '관리자 비밀번호: ' ADMIN_PW;echo;read -r -p '웹 포트 [5000]: ' PORT;PORT=${PORT:-5000}
apt-get update;apt-get install -y python3 python3-venv python3-pip mariadb-server mariadb-client ca-certificates;systemctl enable --now mariadb;mariadb -Nse "SHOW DATABASES LIKE 'security_assets'"|grep -q security_assets&&{ echo 'security_assets DB가 이미 있습니다. 신규 설치를 중단합니다.';exit 1;};mariadb < "$HERE/schema.sql";mariadb -e "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';GRANT SELECT,INSERT,UPDATE,DELETE ON security_assets.* TO '$DB_USER'@'localhost';FLUSH PRIVILEGES;"
id securityassets >/dev/null 2>&1||useradd --system --home "$APP" --shell /usr/sbin/nologin securityassets;mkdir -p "$APP";cp "$HERE/app.py" "$HERE/init_admin.py" "$HERE/requirements.txt" "$APP/";cp -a "$HERE/templates" "$HERE/static" "$APP/";python3 -m venv "$APP/.venv";"$APP/.venv/bin/pip" install -r "$APP/requirements.txt";SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))');umask 077;printf 'DB_USER=%s\nDB_PASSWORD=%s\nSECRET_KEY=%s\n' "$DB_USER" "$DB_PASSWORD" "$SECRET" >/etc/security-assets.env;export DB_USER DB_PASSWORD;"$APP/.venv/bin/python" "$APP/init_admin.py" "$ADMIN" "$ADMIN_NAME" "$ADMIN_PW";chown -R securityassets:securityassets "$APP";cat >/etc/systemd/system/security-assets.service <<EOF
[Unit]
Description=NAONWORKS Asset Management
After=mariadb.service
[Service]
User=securityassets
Group=securityassets
WorkingDirectory=$APP
EnvironmentFile=/etc/security-assets.env
ExecStart=$APP/.venv/bin/gunicorn --workers 2 --bind 0.0.0.0:$PORT app:app
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload;systemctl enable --now security-assets;sleep 2;systemctl is-active --quiet security-assets||{ journalctl -u security-assets -n 80 --no-pager;exit 1;};echo "설치 완료: http://$(hostname -I|awk '{print $1}'):$PORT"