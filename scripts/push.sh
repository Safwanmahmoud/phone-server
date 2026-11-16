#!/usr/bin/env bash
# Run on your computer: copies this working copy to the phone and runs the installer there.
# Usage: scripts/push.sh [ssh-host]    (default host: phone, from ~/.ssh/config)
set -euo pipefail

HOST="${1:-phone}"
cd "$(dirname "$0")/.."

echo "→ Copying to $HOST:~/phone-server"
git ls-files -z --cached --others --exclude-standard \
  | tar --null --ignore-failed-read -T - -czf - \
  | ssh "$HOST" 'mkdir -p ~/phone-server && tar -xzf - -C ~/phone-server'

echo "→ Installing"
ssh "$HOST" 'bash ~/phone-server/scripts/install.sh'
