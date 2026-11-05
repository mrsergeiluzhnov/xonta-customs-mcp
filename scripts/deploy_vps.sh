#!/usr/bin/env bash
# Install or update Xonta Customs RU on the VPS as a systemd service on 127.0.0.1:8765.
# Run as root on the server:  bash deploy_vps.sh [path/to/tnved.xlsx]
# Then add deploy/nginx-mcp.xonta.ru.conf to the mcp.xonta.ru server block and reload nginx.
set -euo pipefail

APP=/opt/xonta-customs
SRC=${XONTA_CUSTOMS_SRC:-xonta-customs-mcp}   # PyPI name, or git+https://github.com/mrsergeiluzhnov/xonta-customs-mcp

id xonta >/dev/null 2>&1 || useradd -r -m -d "$APP" -s /usr/sbin/nologin xonta
mkdir -p "$APP/data" && chown -R xonta:xonta "$APP"

[ -x "$APP/venv/bin/python" ] || sudo -u xonta python3 -m venv "$APP/venv"
sudo -u xonta "$APP/venv/bin/pip" install -q --upgrade pip
sudo -u xonta "$APP/venv/bin/pip" install -q --upgrade "$SRC"

if [ "${1:-}" != "" ]; then
  # copy first: the xonta user may not be able to read files in /root
  ext="${1##*.}"
  install -o xonta -g xonta -m 640 "$1" "$APP/data/tariff-import.$ext"
  sudo -u xonta env XONTA_CUSTOMS_DATA="$APP/data" "$APP/venv/bin/xonta-customs-load-tariff" \
    "$APP/data/tariff-import.$ext" --source "$(basename "$1"), $(date +%F)"
fi

cat > /etc/systemd/system/xonta-customs.service <<EOF
[Unit]
Description=Xonta Customs RU MCP server
After=network-online.target

[Service]
User=xonta
WorkingDirectory=$APP
Environment=XONTA_CUSTOMS_DATA=$APP/data
Environment=ALLOWED_HOSTS=mcp.xonta.ru
EnvironmentFile=-$APP/docparse.env
ExecStart=$APP/venv/bin/xonta-customs-mcp --http --host 127.0.0.1 --port 8765
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now xonta-customs
systemctl restart xonta-customs
sleep 2
curl -sf http://127.0.0.1:8765/health && echo
curl -s http://127.0.0.1:8765/.well-known/mcp/server-card.json | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['serverInfo'], len(d['tools']), 'tools')"
"$APP/venv/bin/python" - <<'PY'
import os; os.environ.setdefault("XONTA_CUSTOMS_DATA", "/opt/xonta-customs/data")
from xonta_customs import store; print("tariff:", store.tariff_meta())
PY
