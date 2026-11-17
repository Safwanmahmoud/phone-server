#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot runs this when the phone starts (installed to ~/.termux/boot/).
#
# Termux:Boot doesn't load termux-exec, the library that makes "#!/usr/bin/env node"
# scripts work on Android (there is no /usr/bin/env). Without it `pm2` is "not found",
# so PM2 is run through node directly, and termux-exec is loaded for everything PM2
# starts (npm and other tools use the same kind of script).
PREFIX=/data/data/com.termux/files/usr
export PREFIX PATH="$PREFIX/bin:$PATH"
[ -f "$PREFIX/lib/libtermux-exec-ld-preload.so" ] && export LD_PRELOAD="$PREFIX/lib/libtermux-exec-ld-preload.so"

LOG="$HOME/.phone-server/logs/boot.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') phone started"

termux-wake-lock
sshd
node "$PREFIX/lib/node_modules/pm2/bin/pm2" resurrect && echo "PM2 processes restored" || echo "pm2 resurrect failed ($?)"
