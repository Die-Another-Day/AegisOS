#!/usr/bin/env python3
"""Graphical verification for AegisOS v5: boot in QEMU with virtio-GPU,
start sway + the shell, and capture REAL guest screenshots via the QEMU
monitor screendump (never rendered mockups).

SUPERSEDED by vt-gui-test-v5.py (2026-11-14). This script logs in on the
SERIAL console (ttyS0) and runs `setsid sway` there — sway needs a seat
and can only start from a VT login, so it dies on EVERY run with
"Unable to create backend" (libseat: Could not open target tty) while
this script still reported ok=True, because its markers only proved
serial echo. It is kept for reference only; use vt-gui-test-v5.py,
which drives tty1 and gates every shot on live process/window state.
A sway-alive check below makes this script FAIL loudly instead of
passing falsely if anyone runs it.

Usage: gui-test-v5.py <image> <logfile>
Saves: screenshots/01-lock-screen.png, 02-desktop.png,
       03-desktop-sunset.png (after `aegis-wallpaper sunset` + shell restart),
       04-launcher.png, plus logs/gui-test-v5.log.
The lock screen is captured as-is; unlocking for the desktop shot is done
by ending the lock process (aegis-gui --lock-and-desktop then starts the
desktop shell) — the password path is exercised separately by the lock
screen's own sudo-based check, not by this script.
"""
import os, pty, re, select, shutil, socket, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG, LOG = sys.argv[1], sys.argv[2]
# v5 fix: QEMU boots the disk read-write, so booting the shipped image
# directly mutates it (previous runs' wallpaper/lab state persisted).
# Always boot a COPY; the shipped image is never written by a test.
TEST_IMG = IMG + ".test"
print(f"[gui-test] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
SHOTS = HERE / "screenshots"
SHOTS.mkdir(exist_ok=True)
MON_SOCK = "/tmp/aegis-v5-mon.sock"
for p in (MON_SOCK,):
    try: os.unlink(p)
    except OSError: pass
logf = open(LOG, "wb", buffering=0)

def emit(b):
    logf.write(b); sys.stdout.buffer.write(b); sys.stdout.buffer.flush()

master, slave = pty.openpty()
q = subprocess.Popen(
    ["qemu-system-x86_64", "-m", "2048", "-machine", "pc", "-cpu", "qemu64",
     "-drive", f"file={IMG},format=raw,if=ide",
     "-netdev", "user,id=net0,hostfwd=tcp::18000-:8000",
     "-device", "e1000,netdev=net0",
     "-device", "virtio-vga",
     "-display", "vnc=:1",
     "-serial", "stdio", "-monitor", f"unix:{MON_SOCK},server,nowait"],
    stdin=slave, stdout=slave, stderr=slave, close_fds=True)
os.close(slave)
buf = b""

def wait_for(pat, timeout, label):
    global buf
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([master], [], [], 5)
        if r:
            try: data = os.read(master, 65536)
            except OSError: break
            if not data: break
            emit(data); buf += data
            if re.search(pat, buf):
                print(f"\n[gui-test] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[gui-test] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[gui-test] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label):
    """Send a unique marker and wait for it, draining all pending serial output into the log."""
    _drain_n[0] += 1
    m = f"DRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    return wait_for(m.encode(), 60, f"drain {label}")

def screendump(name):
    """Ask the QEMU monitor for a screendump; convert PPM -> PNG with Pillow."""
    ppm = f"/tmp/aegis-shot-{name}.ppm"
    png = str(SHOTS / f"{name}.png")
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(20); s.connect(MON_SOCK)
        time.sleep(0.5)
        try: s.recv(65536)
        except socket.timeout: pass
        s.sendall(f"screendump {ppm}\n".encode())
        time.sleep(2)
        try:
            resp = s.recv(65536)
            emit(f"\n[gui-test] monitor reply for {name}: {resp!r}\n".encode())
        except socket.timeout:
            pass
        s.close()
    except Exception as e:
        emit(f"\n[gui-test] screendump {name} FAILED: {e}\n".encode()); return None
    time.sleep(1)
    try:
        from PIL import Image
        im = Image.open(ppm)
        im.save(png)
        print(f"[gui-test] screenshot saved: {png} {im.size}", flush=True)
        return png
    except Exception as e:
        emit(f"\n[gui-test] convert {name} FAILED: {e}\n".encode()); return None

ok = True
ok &= wait_for(rb"aegis login:", 600, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
    send("export AEGIS_TEST_UNLOCK=1\n")
    send("echo MARK_DIAG; systemctl is-enabled aegis-labapp.service aegis-ssh-lab.service; systemctl show -p WantedBy,RequiredBy aegis-labapp.service aegis-ssh-lab.service; systemctl is-active aegis-labapp.service aegis-ssh-lab.service; ss -tlnp 2>/dev/null | grep -E ':2222|:8080' || echo NO_LAB_LISTENERS; ls /dev/dri/ 2>&1; ls /run/user/1000/ 2>&1\n")
    drain("diag")
    send("setsid sway -c ~/.config/sway/config > /tmp/sway.log 2>&1 < /dev/null & echo SWAY_PID=$!\n")
    time.sleep(30)
    # Loud-fail gate (superseded script): sway cannot start from a serial
    # login, so a missing sway process must fail the run, not pass it.
    send("pgrep -a sway; echo SWAY_CHECK_DONE\n")
    if not wait_for(rb"sway -c /home/analyst/.config/sway/config", 30, "sway alive"):
        ok = False
        print("[gui-test] sway did not start (expected: this script is superseded by vt-gui-test-v5.py)", flush=True)
    send("echo MARK_GUI_LOCK; cat /tmp/sway.log; echo ---; ls /run/user/1000/sway-ipc.* 2>/dev/null; pgrep -a sway; pgrep -af aegis-shell\n")
    drain("lock")
    screendump("01-lock-screen")
    send("pkill -f 'aegis-shell --lock'; echo LOCK_KILLED\n")
    time.sleep(15)
    send("echo MARK_GUI_DESKTOP; pgrep -af 'aegis-shell|sway'; tail -n 20 /tmp/sway.log\n")
    drain("desktop")
    screendump("02-desktop")
    send("export SWAYSOCK=$(ls /run/user/1000/sway-ipc.*.sock | head -1); echo SWAYSOCK=$SWAYSOCK\n")
    send("aegis-wallpaper sunset; echo WALLPAPER_RC=$?; grep accent ~/.config/aegis/theme.json\n")
    drain("wallpaper")
    send("swaymsg exec 'aegis-gui --restart-shell'; echo RESTART_SENT\n")
    time.sleep(12)
    screendump("03-desktop-sunset")
    send("swaymsg exec 'aegis-shell --launcher'; echo LAUNCHER_SENT\n")
    time.sleep(10)
    screendump("04-launcher")
    send("echo MARK_GUI_DONE; pkill -f 'aegis-shell --launcher' 2>/dev/null; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[gui-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
