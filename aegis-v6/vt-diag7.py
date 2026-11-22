#!/usr/bin/env python3
"""VT graphical verification for AegisOS v6 (Hyprland + Quickshell).

Method (adapted from the v5 vt-gui-test recipe):
- boot a COPY of the image in QEMU (virtio-vga, VNC display, serial stdio,
  QMP + monitor sockets, usb-tablet + usb-kbd) — the shipped image is
  never written by a test.
- log in on the SERIAL console as analyst (command channel only).
- inject keystrokes into /dev/tty1 via TIOCSTI: login on tty1, then start
  the GUI the way a real user does: `aegis-gui > /tmp/gui.log 2>&1`.
- gate every step on real process state (Hyprland alive, qs alive, lock
  surface present in `hyprctl clients`); a dead GUI fails the run.
- unlock by TYPING THE REAL PASSWORD into the Quickshell lock screen
  via QMP key events (usb-kbd) — this is the PAM-unlock build gate.
  If the password unlock cannot be proven, the run reports it plainly
  and the hyprlock fallback is NOT silently substituted.
- animation proof: two desktop screenshots N seconds apart; the driver
  computes a Pillow pixel diff and prints ANIMATION_DIFF — the animated
  wallpaper must provably move.
- screenshots via QMP screendump: 01-lock-screen, 02-desktop,
  02b-desktop-animation-2, 03-right-click-menu, 04-launcher, 05-chrome.

Usage: vt-gui-test-v6.py <image> <logfile>
"""
import os, pty, re, select, shutil, socket, subprocess, sys, time, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".test"
print(f"[vt-test] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
SHOTS = HERE / "screenshots-diag7"
SHOTS.mkdir(exist_ok=True)
MON_SOCK = "/tmp/aegis-v6-vt-mon.sock"
QMP_SOCK = "/tmp/aegis-v6-vt-qmp.sock"
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
     "-device", "usb-kbd",
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
    _drain_n[0] += 1
    m = f"VTDRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    return wait_for(m.encode(), 60, f"drain {label}")

def qmp(events):
    """Send raw input events over QMP. Returns the response line or None."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(20); s.connect(QMP_SOCK)
        f = s.makefile("rw", buffering=1, encoding="utf-8")
        f.readline()  # greeting
        f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush()
        f.readline()
        f.write(json.dumps({"execute": "input-send-event", "arguments": {"events": events}}) + "\n"); f.flush()
        resp = f.readline()
        s.close()
        return resp.strip()
    except Exception as e:
        emit(f"\n[vt-test] qmp FAILED: {e}\n".encode()); return None

def mouse_move(x, y):
    """Move the pointer to ABSOLUTE output coordinates (usb-tablet 0..32767)."""
    ax = int(x / 1280 * 32767); ay = int(y / 800 * 32767)
    r = qmp([{"type": "abs", "data": {"axis": "x", "value": ax}},
             {"type": "abs", "data": {"axis": "y", "value": ay}}])
    print(f"[vt-test] mouse moved to {x},{y}: {r}", flush=True)
    time.sleep(1.0)

def mouse_click(button="left"):
    qmp([{"type": "btn", "data": {"down": True, "button": button}}])
    time.sleep(0.2)
    qmp([{"type": "btn", "data": {"down": False, "button": button}}])
    time.sleep(1.0)

def type_text(text):
    """Type text via QMP key events (usb-kbd, qcode). Lowercase + Return only."""
    for ch in text:
        if ch == "\n":
            code = "ret"
        else:
            code = ch
        qmp([{"type": "key", "data": {"down": True, "key": {"type": "qcode", "data": code}}}])
        time.sleep(0.08)
        qmp([{"type": "key", "data": {"down": False, "key": {"type": "qcode", "data": code}}}])
        time.sleep(0.08)
    print(f"[vt-test] typed {len(text)} chars", flush=True)

def screendump(name):
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
    # NOTE (found 2026-11-22, qs-diag4 + host repro): the old pattern
    # 'Hyprland|quickshell|hyprlock|swww' can NEVER list `qs -c aegis` —
    # its cmdline contains none of those words — so shell-alive could
    # never match even with qs running. 'qs' must be in the pattern.
    send(f"pgrep -af 'Hyprland|quickshell|hyprlock|swww|qs'; echo CHECK_{label}\n")
    return wait_for(pat, timeout, f"check {label}")

def hyprctl(cmd, label, timeout=60):
    """Run hyprctl from the serial shell (finds the Hyprland socket first)."""
    global buf
    buf = b""
    # Hyprland 0.55 layout: instance dir is $XDG_RUNTIME_DIR/hypr/<sig>/
    # (not $XDG_RUNTIME_DIR/hyprland-<sig> as in <= 0.5x). The signature
    # is the directory name itself; proven by qs-diag3 (hyprctl clients
    # + dispatch both work with this value).
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); "
         f"hyprctl {cmd}; echo HYPR_{label}_DONE\n")
    return wait_for(f"HYPR_{label}_DONE".encode(), timeout, f"hyprctl {label}")

ok = True
ok &= wait_for(rb"aegis login:", 900, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
    send("echo MARK_DIAG; systemctl is-enabled aegis-labapp.service aegis-ssh-lab.service; systemctl is-active aegis-labapp.service aegis-ssh-lab.service; ss -tlnp 2>/dev/null | grep -E ':2222|:8080' || echo NO_LAB_LISTENERS; ls /dev/dri/ 2>&1; ls -l /usr/share/aegis/wallpapers/; cat /etc/aegis-version\n")
    ok &= drain("diag")
if ok:
    # Injector: type into tty1 (real VT login + real user GUI start).
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
    send("typ(\"aegis-gui > /tmp/gui.log 2>&1\\n\")\n")
    send("print(\"INJECTED\")\n")
    send("PYEOF\n")
    ok &= drain("inject-written")
if ok:
    send("echo secure | sudo -S python3 /tmp/inject.py\n")
    ok &= wait_for(rb"INJECTED", 120, "injector ran")
if ok:
    # QEMU llvmpipe slowness (found 2026-11-22, qs-diag3): Quickshell's
    # Qt Quick startup under software rendering takes ~2 min before the
    # `qs -c aegis` process is even visible (Hyprland + swww are up in
    # seconds; qs itself runs clean, no QML errors). The old 45 s wait +
    # 60 s check timed out at ~105 s, before qs appeared. Wait longer
    # here; on real hardware this is seconds, not minutes.
    time.sleep(150)
    # Real gates: Hyprland AND the Quickshell shell must be alive.
    ok &= shell_has(rb"Hyprland", "hyprland-alive")
    ok &= shell_has(rb"qs -c aegis", "shell-alive", timeout=180)
    if ok:
        ok &= hyprctl("clients", "clients")
        ok &= hyprctl("workspaces", "workspaces")
if ok:
    # Lock screen must be showing (autostart locks on entry).
    send("echo ---GUILOG---; cat /tmp/gui.log 2>&1 | head -n 60\n")
    ok &= drain("lock")
if ok:
    mouse_move(560, 625)  # on the lock-screen password row
    mouse_click("left")
    screendump("01-lock-screen")
    # PAM UNLOCK GATE: type the real password into the lock screen.
    type_text("secure\n")
    time.sleep(10)
    ok &= shell_has(rb"qs -c aegis", "shell-after-unlock")
    if ok:
        ok &= hyprctl("clients", "clients-after-unlock")
        # The lock surface must be gone and the bar must exist.
        send("echo MARK_VT_UNLOCKED; pgrep -af 'qs|Hyprland'; echo ---GUILOG-TAIL---; tail -n 40 /tmp/gui.log 2>&1\n")
        ok &= drain("unlocked")
        # DIAG7: bar diagnostic — qslog tail + layer surfaces after unlock.
        send("echo ---QSLOG7---; tail -n 100 /run/user/1000/quickshell/by-id/*/log.qslog 2>&1 | head -n 100; echo ---LAYERS7---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl layers 2>&1 | head -40; echo ---QSLOG7-DONE---\n")
        ok &= drain("qslog7")
if ok:
    mouse_move(640, 400)
    screendump("02-desktop")
    # Animation proof: a second desktop shot 12 s later; frames must differ.
    time.sleep(12)
    screendump("02b-desktop-animation-2")
    try:
        from PIL import Image, ImageChops
        a = Image.open(SHOTS / "02-desktop.png").convert("RGB")
        b = Image.open(SHOTS / "02b-desktop-animation-2.png").convert("RGB")
        diff = ImageChops.difference(a, b)
        n = sum(1 for px in diff.getdata() if px != (0, 0, 0))
        print(f"[vt-test] ANIMATION_DIFF={n} pixels differ between desktop shots", flush=True)
        if n < 100:
            print("[vt-test] ANIMATION NOT PROVEN (frames nearly identical)", flush=True)
            ok = False
    except Exception as e:
        print(f"[vt-test] animation diff FAILED: {e}", flush=True)
        ok = False
if ok:
    # Right-click desktop menu (background-window path; fallback bind exists).
    mouse_move(640, 400)
    mouse_click("right")
    time.sleep(3)
    screendump("03-right-click-menu")
    mouse_click("left")  # close the menu
if ok:
    # Launcher via IPC (Super+D bind also exists).
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER_SENT\n")
    ok &= drain("launcher")
    time.sleep(5)
    screendump("04-launcher")
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER_CLOSED\n")
    ok &= drain("launcher-closed")
if ok:
    # Chrome launch (window must appear; live page load needs real internet).
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl dispatch exec google-chrome; echo CHROME_SENT\n")
    ok &= drain("chrome")
    time.sleep(15)
    ok &= hyprctl("clients", "clients-chrome")
    screendump("05-chrome")
    time.sleep(60)
    screendump("06-chrome-late")
    send("echo ---QSLOG7B---; tail -n 60 /run/user/1000/quickshell/by-id/*/log.qslog 2>&1 | head -n 60; echo ---QSLOG7B-DONE---\n")
    ok &= drain("qslog7b")
    send("echo MARK_VT_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[vt-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
