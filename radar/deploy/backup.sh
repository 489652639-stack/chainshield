#!/usr/bin/env bash
set -euo pipefail
# Online SQLite backup; never copy a live WAL database with plain cp.
dest="${1:?请指定新的备份目录}"
[ ! -e "$dest" ] || { echo '备份目录已存在，请指定新目录'; exit 1; }
umask 077
mkdir -p "$dest"
python3 - "$dest/radar.sqlite3" <<'PY'
import sqlite3,sys
with sqlite3.connect('/var/lib/chainshield/radar.sqlite3') as src,sqlite3.connect(sys.argv[1]) as dst:
    src.backup(dst)
    assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
PY
cp /etc/chainshield/radar.env "$dest/radar.env"
cp -a /opt/chainshield "$dest/source"
tar -czf "$dest.tar.gz" -C "$dest" .
chmod 600 "$dest.tar.gz"
printf '%s\n' '备份含访问密钥，请私下传到新服务器。先停止旧服务器再启动新服务器，避免双机重复扫描。'
