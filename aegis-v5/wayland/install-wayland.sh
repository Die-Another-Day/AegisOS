#!/bin/bash
# install-wayland.sh — install the AegisOS v5 Wayland desktop from this folder.
# Run inside the guest (as root) from the payload dir, or by setup-v5.sh.
# Installs: sway config, shell + colour pipeline, wallpapers, lock background.
set -euo pipefail
P="$(cd "$(dirname "$0")" && pwd)"
LIB=/usr/local/lib/aegis-shell
mkdir -p "$LIB" /usr/share/aegis/wallpapers /home/analyst/.config/aegis
cp "$P/wayland/aegis-shell.py" "$P/wayland/aegis-colours.py" "$LIB/"
cp "$P/wayland/aegis-wallpaper" /usr/local/bin/aegis-wallpaper
chmod 755 "$LIB/aegis-shell.py" "$LIB/aegis-colours.py" /usr/local/bin/aegis-wallpaper
ln -sf "$LIB/aegis-shell.py" /usr/local/bin/aegis-shell
ln -sf "$LIB/aegis-colours.py" /usr/local/bin/aegis-colours
cp "$P/wayland/wallpapers/"*.png /usr/share/aegis/wallpapers/
mkdir -p /home/analyst/.config/sway
cp "$P/wayland/sway-config" /home/analyst/.config/sway/config
cp /usr/share/aegis/wallpapers/aegis-starfield.png /home/analyst/.config/aegis/wallpaper.png
python3 "$LIB/aegis-colours.py" /home/analyst/.config/aegis/wallpaper.png --out /home/analyst/.config/aegis
chmod 755 /usr/share/aegis /usr/share/aegis/wallpapers /usr/local/lib/aegis-shell 2>/dev/null || true
chmod 644 /usr/share/aegis/wallpapers/*.png 2>/dev/null || true
chown -R analyst:analyst /home/analyst/.config
echo "Wayland desktop installed: sway + aegis-shell + wallpapers + theme"
