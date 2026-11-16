#!/data/data/com.termux/files/usr/bin/bash
# Installs or updates Phone Server on this phone. Safe to run again.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${PS_DATA:-$HOME/.phone-server}"
cd "$ROOT"

echo "→ Packages"
missing=()
for pkg in python git nodejs-lts ttyd caddy openssh; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]})); then
  yes | pkg install -y "${missing[@]}"
fi
command -v pm2 >/dev/null || npm install -g pm2

echo "→ Python environment"
[ -x .venv/bin/python ] || python -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

echo "→ Folders"
mkdir -p "$DATA/apps" "$DATA/logs"
chmod 700 "$DATA"
chmod +x scripts/*.sh

echo "→ Start on boot (used by the Termux:Boot app)"
mkdir -p "$HOME/.termux/boot"
install -m 700 scripts/boot.sh "$HOME/.termux/boot/start-phone-server"

echo "→ Services"
pm2 startOrRestart ecosystem.config.js --update-env >/dev/null
pm2 save --force >/dev/null
pm2 ls

if [ ! -f "$DATA/password.json" ]; then
  echo
  echo "No dashboard password yet. Set one with:"
  echo "  cd ~/phone-server && .venv/bin/python -m server.cli set-password"
fi
echo
echo "Dashboard: http://<phone>:${PS_PORT:-8080}"
