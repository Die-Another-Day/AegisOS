#!/usr/bin/env python3
"""Cursor experiment for AegisOS v5.0.3.

Question: with WLR_NO_HARDWARE_CURSORS=1 (software cursors) the wlroots
"Failed to pick cursor format" error is gone, but is the pointer
actually VISIBLE? The vt-gui-test mouse_move used HMP mouse_move,
which is RELATIVE and may be ignored by the absolute usb-tablet.

This script boots a copy of the v5.0.3 image, starts the GUI on tty1,
then moves the pointer with QMP input-send-event ABSOLUTE coordinates
to the centre of the 1280x800 output and screendumps. It also checks
that WLR_NO_HARDWARE_CURSORS reached sway's environment.
Usage: cursor-exp-v503.py <image> <logfile>
"""
import json
import os, pty, re, select, shutil, socket, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".test"
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
SHOTS = HERE / "screenshots"
SHOTS.mkdir(exist_ok=True)
MON_SOCK = "/tmp/aegis-exp-mon.sock"
QMP_SOCK = "/tmp/aegis-exp-qmp.sock"
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
                print(f"\n[cursor-exp] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[cursor-exp] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[cursor-exp] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label):
    _drain_n[0] += 1
    m = f"EXDRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    return wait_for(m.encode(), 60, f"drain {label}")

def qmp(cmd):
    """One QMP command; returns the decoded reply dict (or None)."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(20); s.connect(QMP_SOCK)
        f = s.makefile("rw", buffering=1, encoding="utf-8")
        f.readline()  # greeting
        f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush()
        f.readline()  # return
        f.write(json.dumps(cmd) + "\n"); f.flush()
        line = f.readline()
        s.close()
        return json.loads(line) if line else None
    except Exception as e:
        emit(f"\n[cursor-exp] qmp FAILED: {e}\n".encode()); return None

def qmp_abs_move(frac_x, frac_y):
    """Move pointer to fraction of the output (0..1) via absolute events."""
    ax = int(frac_x * 32767)
    ay = int(frac_y * 32767)
    r = qmp({"execute": "input-send-event", "arguments": {"events": [
        {"type": "abs", "data": {"axis": "x", "value": ax}},
        {"type": "abs", "data": {"axis": "y", "value": ay}}]}})
    print(f"[cursor-exp] abs move to {frac_x},{frac_y} -> {ax},{ay}: {r}", flush=True)
    time.sleep(2)

def screendump(name):
    ppm = f"/tmp/aegis-exp-{name}.ppm"
    png = str(SHOTS / f"exp-{name}.png")
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(20); s.connect(MON_SOCK)
        time.sleep(0.5)
        try: s.recv(65536)
        except socket.timeout: pass
        s.sendall(f"screendump {ppm}\n".encode())
        time.sleep(2)
        try: s.recv(65536)
        except socket.timeout: pass
        s.close()
    except Exception as e:
        emit(f"\n[cursor-exp] screendump {name} FAILED: {e}\n".encode()); return None
    time.sleep(1)
    try:
        from PIL import Image
        im = Image.open(ppm); im.save(png)
        print(f"[cursor-exp] screenshot saved: {png} {im.size}", flush=True)
        return png
    except Exception as e:
        emit(f"\n[cursor-exp] convert {name} FAILED: {e}\n".encode()); return None

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
    send("typ(\"AEGIS_TEST_UNLOCK=1 aegis-gui > /tmp/gui.log 2>&1\\n\")\n")
    send("print(\"INJECTED\")\n")
    send("PYEOF\n")
    ok &= drain("inject-written")
if ok:
    send("echo secure | sudo -S python3 /tmp/inject.py\n")
    ok &= wait_for(rb"INJECTED", 120, "injector ran")
if ok:
    time.sleep(40)
    send("pgrep -af 'sway|aegis-shell'; echo ---ENV---; tr '\\0' '\\n' < /proc/$(pgrep -f 'sway -c' | head -1)/environ | grep -i wlr; echo ---CURSOR-ERR---; grep -ai cursor /tmp/gui.log | head; echo EXP_DONE\n")
    ok &= drain("env")
if ok:
    # Lock screen: park pointer on the password row (560/1280, 625/800).
    qmp_abs_move(560/1280, 625/800)
    screendump("cursor-lock")
    # Unlock to desktop, park pointer dead centre.
    send("pkill -f 'aegis-shell --lock'; echo LOCK_KILLED\n")
    time.sleep(12)
    qmp_abs_move(0.5, 0.5)
    screendump("cursor-desktop")
    send("echo MARK_EXP_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[cursor-exp] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
