#!/data/data/com.termux/files/usr/bin/bash
# Web terminal. ttyd listens on a Unix socket only, never on the network;
# Caddy checks the dashboard sign-in before proxying to it.
SOCK="${PS_DATA:-$HOME/.phone-server}/ttyd.sock"
rm -f "$SOCK"
cd "$HOME" || exit 1
exec ttyd \
  --interface "$SOCK" \
  --base-path /terminal \
  --writable \
  --check-origin \
  -t fontSize=14 \
  -t 'fontFamily=ui-monospace, "JetBrains Mono", "Cascadia Code", Menlo, Consolas, monospace' \
  -t 'theme={"background":"#0a0c10","foreground":"#d4d9e3","cursor":"#3dd6b0"}' \
  -t titleFixed="Phone terminal" \
  bash -l
