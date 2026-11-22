#!/usr/bin/env python3
"""qs-diag8 — diagnose the AegisOS v6 desktop-shell bar defect (live session).

Questions to answer, in order:
  A. What does the FULL qs log (log.log, not just log.qslog tail) say
     after unlock? Any QML error/warning naming Bar.qml / shell.qml?
  B. Do the launcher / right-click menu surfaces even get CREATED
     (hyprctl layers namespaces aegis:launcher / aegis:desktopmenu)?
  C. DISCRIMINATING TEST: after `aegis-gui --restart-shell` the fresh qs
     is created with locked=false, so the bar PanelWindow is created
     VISIBLE from the start. If the bar appears then, the bug is the
     "created hidden, shown later" lifecycle; if not, it is not.
  D. MINIMAL TEST: a second qs instance showing only a solid red
     PanelWindow (created visible). If red shows, layer-shell
     PanelWindows render fine in general and the bug is Bar-specific.
  E. Chrome: is the chrome process even running after dispatch, and
     does a window appear within 120 s?

Method: same QEMU VT harness as vt-diag7.py (test copy only, serial
command channel, TIOCSTI injection on tty1, QMP keys/mouse/screendump).
Usage: qs-diag8.py <image> <logfile>
"""
import os, pty, re, select, shutil, socket, subprocess, sys, time, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".test"
print(f"[diag8] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
SHOTS = HERE / "screenshots-diag8"
SHOTS.mkdir(exist_ok=True)
MON_SOCK = "/tmp/aegis-v6-diag8-mon.sock"
QMP_SOCK = "/tmp/aegis-v6-diag8-qmp.sock"
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
                print(f"\n[diag8] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[diag8] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[diag8] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label):
    _drain_n[0] += 1
    m = f"D8DRAIN{_drain_n[0]}_{label}"
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
        emit(f"\n[diag8] qmp FAILED: {e}\n".encode()); return None

def mouse_move(x, y):
    ax = int(x / 1280 * 32767); ay = int(y / 800 * 32767)
    r = qmp([{"type": "abs", "data": {"axis": "x", "value": ax}},
             {"type": "abs", "data": {"axis": "y", "value": ay}}])
    print(f"[diag8] mouse moved to {x},{y}: {r}", flush=True)
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
    print(f"[diag8] typed {len(text)} chars", flush=True)

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
            emit(f"\n[diag8] monitor reply for {name}: {resp!r}\n".encode())
        except socket.timeout:
            pass
        s.close()
    except Exception as e:
        emit(f"\n[diag8] screendump {name} FAILED: {e}\n".encode()); return None
    time.sleep(1)
    try:
        from PIL import Image
        im = Image.open(ppm)
        im.save(png)
        print(f"[diag8] screenshot saved: {png} {im.size}", flush=True)
        return png
    except Exception as e:
        emit(f"\n[diag8] convert {name} FAILED: {e}\n".encode()); return None

def shell_has(pat, label, timeout=60):
    global buf
    buf = b""
    send(f"pgrep -af 'Hyprland|quickshell|hyprlock|swww|qs'; echo CHECK_{label}\n")
    return wait_for(pat, timeout, f"check {label}")

def hyprctl(cmd, label, timeout=60):
    global buf
    buf = b""
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); "
         f"hyprctl {cmd}; echo HYPR_{label}_DONE\n")
    return wait_for(f"HYPR_{label}_DONE".encode(), timeout, f"hyprctl {label}")

SESS = "export XDG_RUNTIME_DIR=/run/user/1000; export WAYLAND_DISPLAY=wayland-1; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); "

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
        ok &= hyprctl("clients", "clients")
if ok:
    mouse_move(560, 625)
    mouse_click("left")
    screendump("01-lock-screen")
    type_text("secure\n")
    time.sleep(10)
    ok &= shell_has(rb"qs -c aegis", "shell-after-unlock")
    if ok:
        ok &= hyprctl("clients", "clients-after-unlock")
        # --- DIAG8-A: full qs log + layers after unlock ---
        send("echo ---DIAG8A-LAYERS---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl layers 2>&1; echo ---DIAG8A-BYID---; ls -la /run/user/1000/quickshell/by-id/*/ 2>&1; echo ---DIAG8A-LOGFILES---; for f in /run/user/1000/quickshell/by-id/*/log.log; do echo \"== $f ==\"; wc -l \"$f\"; done\n")
        ok &= drain("diag8a-layers")
        send("echo ---DIAG8A-QSLOG-ERR---; for f in /run/user/1000/quickshell/by-id/*/log.log; do echo \"== $f ==\"; grep -a -i \"error\\|fail\\|TypeError\\|ReferenceError\\|Bar.qml\\|shell.qml\" \"$f\" | grep -av \"egl\\|dri2\\|glamor\\|kms_swrast\\|xkbcomp\\|keycode\" | head -80; done; echo ---DIAG8A-QSLOG-ERR-DONE---\n")
        ok &= drain("diag8a-qslog-err")
        send("echo ---DIAG8A-QSLOG-TAIL---; for f in /run/user/1000/quickshell/by-id/*/log.log; do echo \"== $f ==\"; tail -n 60 \"$f\"; done; echo ---DIAG8A-QSLOG-TAIL-DONE---\n")
        ok &= drain("diag8a-qslog-tail")
        send("echo ---DIAG8A-GUILOG---; tail -n 40 /tmp/gui.log 2>&1; echo ---DIAG8A-GUILOG-DONE---\n")
        ok &= drain("diag8a-guilog")
        screendump("02-desktop")
        # --- DIAG8-B: do launcher / menu surfaces get created? ---
        send(SESS + "qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER_SENT\n")
        ok &= drain("launcher")
        time.sleep(5)
        send("echo ---DIAG8B-LAYERS-LAUNCHER---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl layers 2>&1; echo ---DIAG8B-LAYERS-DONE---\n")
        ok &= drain("diag8b-layers-launcher")
        screendump("03-launcher")
        send(SESS + "qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER_CLOSED\n")
        ok &= drain("launcher-closed")
        mouse_move(640, 400)
        mouse_click("right")
        time.sleep(3)
        send("echo ---DIAG8B-LAYERS-MENU---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl layers 2>&1; echo ---DIAG8B-LAYERS-MENU-DONE---\n")
        ok &= drain("diag8b-layers-menu")
        screendump("04-rightclick-menu")
        mouse_click("left")
        # --- DIAG8-C: restart shell — fresh qs, bar created VISIBLE ---
        send(SESS + "nohup aegis-gui --restart-shell > /tmp/restart.log 2>&1 & echo RESTART_SENT\n")
        ok &= drain("restart-sent")
        time.sleep(150)
        ok &= shell_has(rb"qs -c aegis", "shell-after-restart", timeout=180)
        if ok:
            mouse_move(560, 625)
            screendump("05-lock-after-restart")
            type_text("secure\n")
            time.sleep(10)
            ok &= shell_has(rb"qs -c aegis", "shell-after-restart-unlock")
            send("echo ---DIAG8C-LAYERS---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl layers 2>&1; echo ---DIAG8C-LAYERS-DONE---\n")
            ok &= drain("diag8c-layers")
            screendump("06-desktop-after-restart")
        # --- DIAG8-D: minimal red PanelWindow in a second qs instance ---
        send("mkdir -p /tmp/qstest\n")
        send("cat > /tmp/qstest/shell.qml <<'QSEOF'\n")
        send("import QtQuick\n")
        send("import Quickshell\n")
        send("import Quickshell.Wayland\n")
        send("ShellRoot {\n")
        send("    PanelWindow {\n")
        send("        anchors { top: true; left: true; right: true }\n")
        send("        implicitHeight: 46\n")
        send("        color: \"#ff0000\"\n")
        send("        WlrLayershell.namespace: \"aegis:testbar\"\n")
        send("        Rectangle { anchors.fill: parent; color: \"#ff0000\" }\n")
        send("    }\n")
        send("}\n")
        send("QSEOF\n")
        ok &= drain("qstest-written")
        send(SESS + "qs -c /tmp/qstest > /tmp/qstest.log 2>&1 & echo QSTEST_SENT\n")
        ok &= drain("qstest-sent")
        time.sleep(20)
        send("echo ---DIAG8D-LAYERS---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl layers 2>&1; echo ---DIAG8D-QSTESTLOG---; cat /tmp/qstest.log 2>&1 | head -30; echo ---DIAG8D-DONE---\n")
        ok &= drain("diag8d")
        screendump("07-minimal-bar")
        send("pkill -f 'qs -c /tmp/qstest'; echo QSTEST_KILLED\n")
        ok &= drain("qstest-killed")
        # --- DIAG8-E: Chrome process + window ---
        send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl dispatch exec google-chrome; echo CHROME_SENT\n")
        ok &= drain("chrome")
        time.sleep(60)
        send("echo ---DIAG8E-CHROME-60---; pgrep -af chrome | head -5; echo ---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl clients 2>&1 | head -30; echo ---DIAG8E-CHROME-60-DONE---\n")
        ok &= drain("diag8e-60")
        screendump("08-chrome-60")
        time.sleep(60)
        send("echo ---DIAG8E-CHROME-120---; pgrep -af chrome | head -5; echo ---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl clients 2>&1 | head -30; echo ---DIAG8E-CHROME-120-DONE---\n")
        ok &= drain("diag8e-120")
        screendump("09-chrome-120")
if ok:
    send("echo MARK_DIAG8_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[diag8] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
