#!/usr/bin/env bash
set -euo pipefail
src="${1:?请指定已解压的备份目录}"
[ -f "$src/radar.sqlite3" ] && [ -f "$src/radar.env" ] && [ -d "$src/source/radar" ]
python3 - "$src/radar.sqlite3" <<'PY'
import sqlite3,sys
with sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True) as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
PY
[ ! -e /var/lib/chainshield/radar.sqlite3 ] || { echo '目标服务器已有数据库，拒绝覆盖'; exit 1; }
install -d /opt/chainshield /etc/chainshield
cp -a "$src/source/." /opt/chainshield/
RADAR_INSTALL_START=0 bash /opt/chainshield/radar/deploy/install.sh
systemctl stop chainshield-radar
rm -f /var/lib/chainshield/radar.sqlite3 /var/lib/chainshield/radar.sqlite3-wal /var/lib/chainshield/radar.sqlite3-shm
install -o chainshield -g chainshield -m 600 "$src/radar.sqlite3" /var/lib/chainshield/radar.sqlite3
install -m 600 "$src/radar.env" /etc/chainshield/radar.env
systemctl start chainshield-radar
printf '%s\n' '模拟状态恢复完成；请更新HTTPS域名解析并验证手机连接。'
