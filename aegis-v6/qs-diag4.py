#!/usr/bin/env python3
"""Diagnostic #4: boot a COPY of the v6 image, start aegis-gui on tty1,
then poll process state + guest memory + OOM evidence every 30 s for
6 minutes, to learn WHEN (if ever) `qs -c aegis` appears after GUI start.

Usage: qs-diag4.py <image> <logfile>
"""
import os, pty, re, select, shutil, subprocess, sys, time

IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".diag4"
print(f"[qs-diag4] booting a copy: {TEST_IMG}", flush=True)
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
     "-qmp", "unix:/tmp/aegis-v6-diag4-qmp.sock,server,nowait"],
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
                print(f"\n[qs-diag4] MATCH {label}\n", flush=True)
                return True
    print(f"\n[qs-diag4] TIMEOUT {label}: {pat}\n", flush=True)
    return False

def drain(label, timeout=30):
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
    print(f"\n[qs-diag4] MATCH drain {label}\n", flush=True)
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
    t0 = time.time()
    for i in range(12):  # 12 x 30 s = 6 min
        time.sleep(30)
        elapsed = int(time.time() - t0)
        send(f"echo ---POLL-T+{elapsed}s---; date +%s; pgrep -af 'Hyprland|quickshell|hyprlock|swww|qs|aegis-autostart|hypridle'; free -m | head -2; echo ---OOM---; dmesg 2>/dev/null | grep -i 'out of memory\\|killed process' | tail -3; echo ---POLL-DONE---\n")
        drain(f"poll-{i}", 25)
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
print(f"[qs-diag4] done ok={ok} qemu_rc={q.returncode}", flush=True)
sys.exit(0 if ok else 1)
