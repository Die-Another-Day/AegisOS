#!/usr/bin/env bash
# Run AegisOS v5 in QEMU — GRAPHICAL display mode.
# Usage: ./run-qemu-gui.sh [image] [memory-MB]
#   ./run-qemu-gui.sh aegis-v5.img 2048
# This does NOT change the guest's default boot: the guest still boots
# to the CLI + web console on http://127.0.0.1:8000. The difference is
# only the HOST display: this script gives QEMU a real window (gtk/sdl)
# instead of -nographic, so that when you run `aegis-gui` inside the
# guest, the sway desktop actually appears in that window.
#   Inside the guest: log in as analyst / secure, then run:
#     aegis-gui            # sway + shell
#     aegis-gui --fullscreen
#     aegis-gui --stop     # back to CLI
# Display: AEGIS_DISPLAY=gtk (default), sdl, or vnc=:1
# Quit QEMU: close the QEMU window, or Ctrl-Alt-Q in the gtk window.
set -euo pipefail
IMG="${1:-$(cd "$(dirname "$0")" && pwd)/aegis-v5.img}"
MEM="${2:-2048}"
DISP="${AEGIS_DISPLAY:-gtk}"
[ -f "$IMG" ] || { echo "image not found: $IMG" >&2; exit 1; }
echo "AegisOS v5 GUI mode: display=$DISP, RAM=${MEM}MB"
echo "Guest boots to CLI first. Log in as analyst / secure, then run: aegis-gui"
# GPU: AEGIS_GL=1 uses virtio-GPU with host GL (better for sway);
# default is std VGA, which sway drives via software rendering
# (WLR_RENDERER_ALLOW_SOFTWARE=1 is set by aegis-gui).
if [ "${AEGIS_GL:-0}" = "1" ]; then
  GPU_ARGS=(-device virtio-vga-gl -display "$DISP,gl=on")
else
  GPU_ARGS=(-vga std -display "$DISP")
fi
exec qemu-system-x86_64 \
  -m "$MEM" -machine pc -cpu qemu64 \
  -drive file="$IMG",format=raw,if=ide \
  -netdev user,id=net0,hostfwd=tcp::18000-:8000,hostfwd=tcp::18080-:8080,hostfwd=tcp::12222-:2222 \
  -device e1000,netdev=net0 \
  "${GPU_ARGS[@]}" \
  -serial stdio -monitor none
