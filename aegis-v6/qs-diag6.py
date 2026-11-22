#!/usr/bin/env python3
"""Diagnostic #6: boot a COPY of the v6 image, start aegis-gui on tty1,
wait, then read Quickshell's own log (log.qslog) to see where qs stalls,
and test whether `qs -c aegis ipc call aegis lock` (WITH -c) reaches the
server — distinguishing "IPC broken (wrong config name)" from "qs stuck".

Usage: qs-diag6.py <image> <logfile>
"""
import os, pty, re, select, shutil, subprocess, sys, time

IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".diag6"
print(f"[qs-diag6] booting a copy: {TEST_IMG}", flush=True)
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
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
     "-serial", "stdio", "-monitor", "none",
     "-qmp", "unix:/tmp/aegis-v6-diag6-qmp.sock,server,nowait"],
    stdin=slave, stdout=slave, stderr=slave, close_fds=True)
os.close(slave)
buf = b""

def send(s):
    os.write(master, s.encode())

def wait_for(pat, timeout, label):
    global buf
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([master], [], [], 1)
        if r:
            try:
                d = os.read(master, 65536)
            except OSError:
                break
            if not d:
                break
            buf += d
            emit(d)
            if re.search(pat, buf):
                print(f"\n[qs-diag6] MATCH {label}\n", flush=True)
                return True
    print(f"\n[qs-diag6] TIMEOUT {label}: {pat}\n", flush=True)
    return False

def drain(label, timeout=60):
    global buf
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([master], [], [], 1)
        if r:
            try:
                d = os.read(master, 65536)
            except OSError:
                break
            if not d:
                break
            buf += d
            emit(d)
    print(f"\n[qs-diag6] MATCH drain {label}\n", flush=True)
    return True

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
    send("echo ---PGREP6---; pgrep -af 'Hyprland|quickshell|hyprlock|swww|qs'; echo ---QSLOG-FILES---; ls -la /run/user/1000/quickshell/by-id/*/log.qslog 2>&1; echo ---QSLOG-TAIL---; tail -n 120 /run/user/1000/quickshell/by-id/*/log.qslog 2>&1 | head -n 120\n")
    ok &= drain("qslog", 90)
if ok:
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); echo ---LAYERS6---; hyprctl layers 2>&1 | head -30; echo ---IPC-WITH-C---; timeout 90 qs -c aegis ipc call aegis lock 2>&1; echo IPC_WITH_C_RC=$?; echo ---LAYERS-AFTER-LOCK---; hyprctl layers 2>&1 | head -30\n")
    ok &= drain("ipc-with-c", 150)
send("echo secure | sudo -S poweroff\n")
time.sleep(8)
try:
    q.terminate()
except Exception:
    pass
try:
    q.wait(timeout=20)
except Exception:
    q.kill()
logf.close()
print(f"[qs-diag6] done ok={ok} qemu_rc={q.returncode}", flush=True)
sys.exit(0 if ok else 1)
