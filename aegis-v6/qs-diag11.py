#!/usr/bin/env python3
"""qs-diag11 — verification of the bar fix on the REBUILT image
(SHA 3bd99819...), under the hard case: QEMU 1 vCPU, llvmpipe.

Fix under test: shell.qml keeps the bar + desktop background window
ALWAYS visible (first frame rendered at shell startup, before unlock),
and aegis-autostart starts qs BEFORE the animated wallpaper.
Expected: the bar is already on screen in the FIRST post-unlock shot
(t10s), and visible at the top of the lock screen (01) as a side effect.
Launcher/menu/Chrome get longer waits (60 s / 60 s / 120 s) for their
first frames under 1 vCPU. Usage: qs-diag11.py <image> <logfile>
"""
import os, pty, re, select, shutil, socket, subprocess, sys, time, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".test"
print(f"[diag11] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
SHOTS = HERE / "screenshots-diag11"
SHOTS.mkdir(exist_ok=True)
MON_SOCK = "/tmp/aegis-v6-diag11-mon.sock"
QMP_SOCK = "/tmp/aegis-v6-diag11-qmp.sock"
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
                print(f"\n[diag11] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[diag11] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[diag11] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label):
    _drain_n[0] += 1
    m = f"D10DRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    return wait_for(m.encode(), 90, f"drain {label}")

def qmp(events):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(20); s.connect(QMP_SOCK)
        f = s.makefile("rw", buffering=1, encoding="utf-8")
        f.readline()
        f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush()
        f.readline()
        f.write(json.dumps({"execute": "input-send-event", "arguments": {"events": events}}) + "\n"); f.flush()
        resp = f.readline()
        s.close()
        return resp.strip()
    except Exception as e:
        emit(f"\n[diag11] qmp FAILED: {e}\n".encode()); return None

def mouse_move(x, y):
    ax = int(x / 1280 * 32767); ay = int(y / 800 * 32767)
    qmp([{"type": "abs", "data": {"axis": "x", "value": ax}},
         {"type": "abs", "data": {"axis": "y", "value": ay}}])
    time.sleep(1.0)

def mouse_click(button="left"):
    qmp([{"type": "btn", "data": {"down": True, "button": button}}])
    time.sleep(0.2)
    qmp([{"type": "btn", "data": {"down": False, "button": button}}])
    time.sleep(1.0)

def type_text(text):
    for ch in text:
        code = "ret" if ch == "\n" else ch
        qmp([{"type": "key", "data": {"down": True, "key": {"type": "qcode", "data": code}}}])
        time.sleep(0.08)
        qmp([{"type": "key", "data": {"down": False, "key": {"type": "qcode", "data": code}}}])
        time.sleep(0.08)
    print(f"[diag11] typed {len(text)} chars", flush=True)

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
            emit(f"\n[diag11] monitor reply for {name}: {resp!r}\n".encode())
        except socket.timeout:
            pass
        s.close()
    except Exception as e:
        emit(f"\n[diag11] screendump {name} FAILED: {e}\n".encode()); return None
    time.sleep(1)
    try:
        from PIL import Image
        im = Image.open(ppm)
        im.save(png)
        print(f"[diag11] screenshot saved: {png} {im.size}", flush=True)
        return png
    except Exception as e:
        emit(f"\n[diag11] convert {name} FAILED: {e}\n".encode()); return None

def shell_has(pat, label, timeout=60):
    global buf
    buf = b""
    send(f"pgrep -af 'Hyprland|quickshell|hyprlock|swww|qs'; echo CHECK_{label}\n")
    return wait_for(pat, timeout, f"check {label}")

SESS = "export XDG_RUNTIME_DIR=/run/user/1000; export WAYLAND_DISPLAY=wayland-1; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); "

def timestamped_shot(name):
    send(f"date '+DIAG11-TIME %T'; echo ---SHOT-{name}---\n")
    drain(f"ts-{name}")
    screendump(name)

ok = True
ok &= wait_for(rb"aegis login:", 900, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
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
    time.sleep(150)
    ok &= shell_has(rb"Hyprland", "hyprland-alive")
    ok &= shell_has(rb"qs -c aegis", "shell-alive", timeout=180)
if ok:
    mouse_move(560, 625)
    mouse_click("left")
    screendump("01-lock-screen")
    type_text("secure\n")
    time.sleep(10)
    ok &= shell_has(rb"qs -c aegis", "shell-after-unlock")
    if ok:
        timestamped_shot("02-desktop-t10s")
        time.sleep(20)
        timestamped_shot("03-desktop-t30s")
        time.sleep(60)
        timestamped_shot("04-desktop-t90s")
        # Launcher + menu + Chrome in the (hopefully prompt) shell.
        send(SESS + "qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER_SENT\n")
        ok &= drain("launcher")
        time.sleep(60)
        screendump("05-launcher")
        send(SESS + "qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER_CLOSED\n")
        ok &= drain("launcher-closed")
        mouse_move(640, 400)
        mouse_click("right")
        time.sleep(60)
        screendump("06-rightclick-menu")
        mouse_click("left")
        send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl dispatch exec google-chrome; echo CHROME_SENT\n")
        ok &= drain("chrome")
        time.sleep(120)
        send("echo ---DIAG11-CHROME---; pgrep -af chrome | head -5; echo ---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl clients 2>&1 | head -20; echo ---DIAG11-CHROME-DONE---\n")
        ok &= drain("chrome-check")
        screendump("07-chrome")
if ok:
    send("echo MARK_DIAG11_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[diag11] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
