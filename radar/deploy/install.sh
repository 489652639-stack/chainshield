#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo '请用管理员权限执行'; exit 1; }
root="$(cd "$(dirname "$0")/../.." && pwd)"
python3 -c 'import sqlite3, ssl, urllib.request'
id chainshield >/dev/null 2>&1 || useradd --system --home /var/lib/chainshield --shell /usr/sbin/nologin chainshield
install -d -o chainshield -g chainshield -m 700 /var/lib/chainshield
install -d -m 755 /opt/chainshield /etc/chainshield
if [ "$root" != /opt/chainshield ]; then
  cp "$root/engine.py" "$root/runtime_policy.py" /opt/chainshield/
  cp -a "$root/radar" /opt/chainshield/
fi
if [ ! -f /etc/chainshield/radar.env ]; then
  umask 077
  python3 - <<'PY'
import secrets
from pathlib import Path
Path('/etc/chainshield/radar.env').write_text('TRADING_MODE=paper\nRADAR_TOKEN='+secrets.token_urlsafe(36)+'\n')
PY
fi
chmod 600 /etc/chainshield/radar.env
install -m 644 "$root/radar/deploy/radar.service" /etc/systemd/system/chainshield-radar.service
systemctl daemon-reload
systemctl enable chainshield-radar
if [ "${RADAR_INSTALL_START:-1}" = 1 ]; then systemctl start chainshield-radar; fi
printf '%s\n' '模拟服务已启动。请为8787回环端口配置HTTPS反代；手机填写HTTPS域名及/etc/chainshield/radar.env内访问密钥。不要向公网开放8787。'
