#!/usr/bin/env python3
"""VT graphical verification for AegisOS v5 (replaces the broken serial
sway start in gui-test-v5.py).

Why this script exists: sway needs a seat — it must run on a real virtual
terminal. gui-test-v5.py logged in on the SERIAL console (ttyS0) and ran
`setsid sway` there, so sway died with "Unable to create backend"
(libseat: Could not open target tty) on EVERY run, including Nov 12, while
still reporting ok=True because its markers only proved serial echo.
The Nov 12 real screenshots came from a one-off vt test (script lost,
logs/vt-gui-test-v5-pixman.log survives); this is that recipe, checked in.

Method (reconstructed from the Nov 12 vt log, verified 2026-11-14):
- boot a COPY of the image in QEMU (virtio-vga, VNC display, serial stdio,
  QMP monitor socket) — the shipped image is never written by a test.
- log in on the SERIAL console as analyst (command channel only).
- write /tmp/inject.py and run it as root: it opens /dev/tty1 and injects
  keystrokes via TIOCSTI — login on tty1, then start the GUI the way a
  real user does: `AEGIS_TEST_UNLOCK=1 aegis-gui` with NO WLR_RENDERER
  set, so the run proves the pixman default baked into aegis-gui.
- gate every step on the real process state (sway alive, --lock alive,
  --desktop alive); a dead GUI fails the run instead of screenshotting
  the tty1 login prompt.
- unlock by ending the lock process (aegis-gui --lock-and-desktop then
  starts the desktop shell) — the password path is exercised separately
  by the lock screen's own sudo-based check, not by this script.
- screenshots via QMP screendump: 01-lock-screen, 02-desktop,
  03-desktop-sunset (after `aegis-wallpaper sunset` + shell restart),
  04-launcher.

Usage: vt-gui-test-v5.py <image> <logfile>
"""
import os, pty, re, select, shutil, socket, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".test"
print(f"[vt-test] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
SHOTS = HERE / "screenshots"
SHOTS.mkdir(exist_ok=True)
MON_SOCK = "/tmp/aegis-v5-vt-mon.sock"
QMP_SOCK = "/tmp/aegis-v5-vt-qmp.sock"
for p in (MON_SOCK, QMP_SOCK):
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
     "-device", "qemu-xhci",
     "-device", "usb-tablet",
     "-display", "vnc=:1",
     "-serial", "stdio", "-monitor", f"unix:{MON_SOCK},server,nowait",
     "-qmp", f"unix:{QMP_SOCK},server,nowait"],
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
                print(f"\n[vt-test] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[vt-test] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[vt-test] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label):
    """Send a unique marker and wait for it, draining pending serial output."""
    _drain_n[0] += 1
    m = f"VTDRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    return wait_for(m.encode(), 60, f"drain {label}")

def mouse_move(x, y):
    """Move the pointer to ABSOLUTE output coordinates via QMP
    input-send-event (usb-tablet, 0..32767 axis range).
    v5.0.3: the cursor must be VISIBLE in the screenshots — park it
    somewhere it cannot hide behind a widget, then screenshot.
    (HMP mouse_move is RELATIVE and is ignored by the absolute
    usb-tablet, so it cannot place the pointer — QMP abs events are
    the correct call: {"type": "abs", "data": {"axis": "x",
    "value": ...}}.)"""
    import json as _json
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(20); s.connect(QMP_SOCK)
        f = s.makefile("rw", buffering=1, encoding="utf-8")
        f.readline()  # greeting
        f.write(_json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush()
        f.readline()  # return
        ax = int(x / 1280 * 32767)
        ay = int(y / 800 * 32767)
        f.write(_json.dumps({"execute": "input-send-event", "arguments": {"events": [
            {"type": "abs", "data": {"axis": "x", "value": ax}},
            {"type": "abs", "data": {"axis": "y", "value": ay}}]}}) + "\n"); f.flush()
        resp = f.readline()
        s.close()
        print(f"[vt-test] mouse moved to {x},{y} (abs {ax},{ay}): {resp.strip()}", flush=True)
        time.sleep(1.5)
    except Exception as e:
        emit(f"\n[vt-test] mouse_move FAILED: {e}\n".encode())

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
            emit(f"\n[vt-test] monitor reply for {name}: {resp!r}\n".encode())
        except socket.timeout:
            pass
        s.close()
    except Exception as e:
        emit(f"\n[vt-test] screendump {name} FAILED: {e}\n".encode()); return None
    time.sleep(1)
    try:
        from PIL import Image
        im = Image.open(ppm)
        im.save(png)
        print(f"[vt-test] screenshot saved: {png} {im.size}", flush=True)
        return png
    except Exception as e:
        emit(f"\n[vt-test] convert {name} FAILED: {e}\n".encode()); return None

def shell_has(pat, label, timeout=60):
    """Run a check on the serial shell; True only if the pattern appears."""
    global buf
    buf = b""
    send(f"pgrep -af 'sway|aegis-shell'; echo CHECK_{label}\n")
    return wait_for(pat, timeout, f"check {label}")

ok = True
ok &= wait_for(rb"aegis login:", 900, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
    # Fresh-boot lab state, from this same boot (mirrors gui-test MARK_DIAG).
    send("echo MARK_DIAG; systemctl is-enabled aegis-labapp.service aegis-ssh-lab.service; systemctl show -p WantedBy,RequiredBy aegis-labapp.service aegis-ssh-lab.service; systemctl is-active aegis-labapp.service aegis-ssh-lab.service; ss -tlnp 2>/dev/null | grep -E ':2222|:8080' || echo NO_LAB_LISTENERS; ls /dev/dri/ 2>&1\n")
    ok &= drain("diag")
if ok:
    # Layer-shell import check first: do_desktop() refuses to start when
    # the GtkLayerShell typelib is missing, so prove the import works in
    # the guest before blaming the GUI for a missing desktop.
    send("python3 -c \"import gi; gi.require_version('Gtk','3.0'); gi.require_version('GtkLayerShell','0.1'); from gi.repository import GtkLayerShell; print('LAYER_OK')\"\n")
    ok &= drain("layer")
if ok:
    # Injector: type into tty1 (real VT login + real user GUI start).
    # No WLR_RENDERER here on purpose: aegis-gui must supply its pixman
    # default from the image itself (the owed re-verification).
    send("cat > /tmp/inject.py <<'PYEOF'\n")
    send("import fcntl, os, termios, time\n")
    send("def typ(s, d=0.08):\n")
    send("    fd = os.open(\"/dev/tty1\", os.O_RDWR)\n")
    send("    for ch in s:\n")
    send("        fcntl.ioctl(fd, termios.TIOCSTI, ch.encode())\n")
    send("        time.sleep(d)\n")
    send("    os.close(fd)\n")
    send("typ(\"analyst\\n\")\n")
    send("time.sleep(2)\n")
    send("typ(\"secure\\n\")\n")
    send("time.sleep(3)\n")
    # Redirect sway + shell output to /tmp/gui.log on tty1 so a failed
    # start can be diagnosed from the serial console afterwards.
    send("typ(\"AEGIS_TEST_UNLOCK=1 aegis-gui > /tmp/gui.log 2>&1\\n\")\n")
    send("print(\"INJECTED\")\n")
    send("PYEOF\n")
    ok &= drain("inject-written")
if ok:
    send("echo secure | sudo -S python3 /tmp/inject.py\n")
    ok &= wait_for(rb"INJECTED", 120, "injector ran")
if ok:
    time.sleep(40)
    # Real gates: sway AND the lock shell must be alive, with a sway IPC sock.
    ok &= shell_has(rb"sway -c /home/analyst/.config/sway/config", "sway-alive")
    ok &= shell_has(rb"aegis-shell --lock", "lock-alive")
    if ok:
        # Window gate: the lock PROCESS being alive is not enough — wait
        # until sway actually shows the lock window before screenshotting.
        send("export SWAYSOCK=$(ls /run/user/1000/sway-ipc.*.sock | head -1); for i in $(seq 1 12); do swaymsg -t get_tree 2>/dev/null | grep -q 'AegisOS lock' && break; sleep 5; done; swaymsg -t get_tree 2>/dev/null | grep -o '\"title\": \"[^\"]*\"' | sort | uniq -c; echo TREE_DONE\n")
        ok &= drain("lock-tree")
    if ok:
        send("swaymsg -t get_outputs 2>&1 | head -n 20; echo ---GUILOG---; cat /tmp/gui.log 2>&1 | head -n 40\n")
        ok &= drain("lock")
if ok:
    mouse_move(560, 625)  # on the lock-screen password row
    screendump("01-lock-screen")
    send("pkill -f 'aegis-shell --lock'; echo LOCK_KILLED\n")
    time.sleep(12)
    ok &= shell_has(rb"aegis-shell --desktop", "desktop-alive")
    time.sleep(5)
    send("echo MARK_VT_DESKTOP; pgrep -af 'aegis-shell|sway'; echo ---GUILOG-TAIL---; tail -n 60 /tmp/gui.log 2>&1\n")
    ok &= drain("desktop")
if ok:
    mouse_move(640, 400)  # centre of the starfield desktop
    screendump("02-desktop")
    send("export SWAYSOCK=$(ls /run/user/1000/sway-ipc.*.sock | head -1); echo SWAYSOCK=$SWAYSOCK\n")
    send("aegis-wallpaper sunset; echo WALLPAPER_RC=$?; grep accent ~/.config/aegis/theme.json\n")
    ok &= drain("wallpaper")
    send("swaymsg exec 'aegis-gui --restart-shell'; echo RESTART_SENT\n")
    time.sleep(12)
    ok &= shell_has(rb"aegis-shell --desktop", "desktop-after-restart")
    # Shot 03 must show the sunset, not the grey frame while the new
    # swaybg is still loading: wait until a swaybg process exists, then
    # give it time to present under load before screenshotting.
    if ok:
        ok &= shell_has(rb"swaybg -o \* -i", "swaybg-alive")
        time.sleep(8)
if ok:
    mouse_move(640, 400)
    screendump("03-desktop-sunset")
    send("swaymsg exec 'aegis-shell --launcher'; echo LAUNCHER_SENT\n")
    time.sleep(10)
    ok &= shell_has(rb"aegis-shell --launcher", "launcher-alive")
if ok:
    mouse_move(640, 400)
    screendump("04-launcher")
    send("echo MARK_VT_DONE; pkill -f 'aegis-shell --launcher' 2>/dev/null; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[vt-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
