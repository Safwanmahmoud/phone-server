#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot runs this when the phone starts (installed to ~/.termux/boot/).
termux-wake-lock
sshd
pm2 resurrect
