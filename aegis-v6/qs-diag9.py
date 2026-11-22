#!/usr/bin/env python3
"""qs-diag9 — time-series + clean-restart test for the v6 bar defect.

Q1 (time): after a plain unlock, does the bar/launcher/menu render on
their own if we just wait? Screenshots every 2 min up to ~12 min, with
the qs pid recorded each time.
Q2 (clean restart): if still missing at ~12 min, kill qs BY PID and
start a fresh `qs -c aegis` (verify the pid CHANGES), wait, unlock,
screenshot. Does the bar render in the fresh shell?
Q3: in whichever shell ends up working, do launcher / right-click menu /
Chrome render?

Method: same QEMU VT harness as vt-diag7.py (test copy only).
Usage: qs-diag9.py <image> <logfile>
"""
import os, pty, re, select, shutil, socket, subprocess, sys, time, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".test"
print(f"[diag9] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
SHOTS = HERE / "screenshots-diag9"
SHOTS.mkdir(exist_ok=True)
MON_SOCK = "/tmp/aegis-v6-diag9-mon.sock"
QMP_SOCK = "/tmp/aegis-v6-diag9-qmp.sock"
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
                print(f"\n[diag9] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[diag9] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[diag9] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label):
    _drain_n[0] += 1
    m = f"D9DRAIN{_drain_n[0]}_{label}"
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
        emit(f"\n[diag9] qmp FAILED: {e}\n".encode()); return None

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
    print(f"[diag9] typed {len(text)} chars", flush=True)

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
            emit(f"\n[diag9] monitor reply for {name}: {resp!r}\n".encode())
        except socket.timeout:
            pass
        s.close()
    except Exception as e:
        emit(f"\n[diag9] screendump {name} FAILED: {e}\n".encode()); return None
    time.sleep(1)
    try:
        from PIL import Image
        im = Image.open(ppm)
        im.save(png)
        print(f"[diag9] screenshot saved: {png} {im.size}", flush=True)
        return png
    except Exception as e:
        emit(f"\n[diag9] convert {name} FAILED: {e}\n".encode()); return None

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

def timestamped_shot(name):
    # Print guest clock + qs pid, then take the shot. Lets us measure
    # exactly when the bar first appears and which qs process owns it.
    send(f"date '+DIAG9-TIME %T'; echo -n 'DIAG9-QSPID '; pgrep -x qs | tr '\\n' ' '; echo; echo ---SHOT-{name}---\n")
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
        ok &= hyprctl("clients", "clients")
if ok:
    mouse_move(560, 625)
    mouse_click("left")
    screendump("01-lock-screen")
    type_text("secure\n")
    time.sleep(10)
    ok &= shell_has(rb"qs -c aegis", "shell-after-unlock")
    if ok:
        # --- Q1: time series, no other interaction ---
        timestamped_shot("02-desktop-t0")
        for mins, name in [(2, "03-desktop-t2"), (4, "04-desktop-t4"),
                           (6, "05-desktop-t6"), (8, "06-desktop-t8"),
                           (10, "07-desktop-t10")]:
            time.sleep(120)
            timestamped_shot(name)
        # Structured qs log: warnings/errors (log.qslog is the real log;
        # log.log is only ~6 lines and has nothing).
        send("echo ---DIAG9-QSLOG-WARN---; for f in /run/user/1000/quickshell/by-id/*/log.qslog; do echo \"== $f ==\"; wc -l \"$f\"; grep -a -i \"warn\\|error\\|fail\" \"$f\" | grep -av \"egl\\|dri2\\|glamor\\|kms_swrast\\|xkbcomp\\|keycode\\|locale\" | head -50; done; echo ---DIAG9-QSLOG-WARN-DONE---\n")
        ok &= drain("qslog-warn")
        # --- Q2: clean restart BY PID (verify pid changes) ---
        send("echo ---DIAG9-RESTART---; OLDQS=$(pgrep -x qs); echo \"OLDQS=$OLDQS\"; kill $OLDQS; sleep 3; pgrep -x qs || echo QS_DEAD; echo ---DIAG9-RESTART-DONE---\n")
        ok &= drain("restart-kill")
        send(SESS + "nohup qs -c aegis > /tmp/qs2.log 2>&1 & echo QS2_SENT\n")
        ok &= drain("qs2-sent")
        time.sleep(150)
        send("echo ---DIAG9-QS2-PID---; echo -n 'NEWQS='; pgrep -x qs | tr '\\n' ' '; echo; echo ---DIAG9-QS2-PID-DONE---\n")
        ok &= drain("qs2-pid")
        ok &= shell_has(rb"qs -c aegis", "shell-after-restart2", timeout=120)
        if ok:
            # Fresh qs starts unlocked; lock it via IPC, then unlock by PAM.
            send(SESS + "qs -c aegis ipc call aegis lock; echo LOCK2_SENT\n")
            ok &= drain("lock2")
            time.sleep(5)
            mouse_move(560, 625)
            screendump("08-lock-after-restart2")
            type_text("secure\n")
            time.sleep(10)
            timestamped_shot("09-desktop-after-restart2")
            # --- Q3: launcher / menu / chrome in the (hopefully) working shell ---
            send(SESS + "qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER2_SENT\n")
            ok &= drain("launcher2")
            time.sleep(5)
            screendump("10-launcher")
            send(SESS + "qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER2_CLOSED\n")
            ok &= drain("launcher2-closed")
            mouse_move(640, 400)
            mouse_click("right")
            time.sleep(3)
            screendump("11-rightclick-menu")
            mouse_click("left")
            send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl dispatch exec google-chrome; echo CHROME_SENT\n")
            ok &= drain("chrome")
            time.sleep(90)
            send("echo ---DIAG9-CHROME---; pgrep -af chrome | head -5; echo ---; export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl clients 2>&1 | head -20; echo ---DIAG9-CHROME-DONE---\n")
            ok &= drain("chrome-check")
            screendump("12-chrome")
if ok:
    send("echo MARK_DIAG9_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[diag9] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
