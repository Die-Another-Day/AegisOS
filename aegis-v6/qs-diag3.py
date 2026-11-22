#!/usr/bin/env python3
"""Diagnostic #3: boot a COPY of the v6 image, start aegis-gui on tty1,
then find Hyprland's 0.55 socket/log layout, list clients, and launch qs
inside the session via hyprctl dispatch exec with its output captured to
a file — so we finally see qs's real error (if any).

Usage: qs-diag3.py <image> <logfile>
"""
import os, pty, re, select, shutil, subprocess, sys, time

IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".diag3"
print(f"[qs-diag3] booting a copy: {TEST_IMG}", flush=True)
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
     "-qmp", "unix:/tmp/aegis-v6-diag3-qmp.sock,server,nowait"],
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
                print(f"\n[qs-diag3] MATCH {label}\n", flush=True)
                return True
    print(f"\n[qs-diag3] TIMEOUT {label}: {pat}\n", flush=True)
    return False

def drain(label, timeout=45):
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
    print(f"\n[qs-diag3] MATCH drain {label}\n", flush=True)
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
    time.sleep(45)
    send("echo ---HYPR-DIR---; ls -laR /run/user/1000/hypr/ 2>&1 | head -30; echo ---HYPR-LOG---; find /run/user/1000 /home/analyst/.cache /tmp -name 'hyprland.log' 2>/dev/null; echo ---PGREP3---; pgrep -af 'Hyprland|quickshell|hyprlock|swww|qs'\n")
    ok &= drain("hyprdir", 60)
if ok:
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); echo SIG=$HYPRLAND_INSTANCE_SIGNATURE; hyprctl clients 2>&1 | head -30; echo ---DISPATCH-QS---; hyprctl dispatch exec \"qs -c aegis > /tmp/qs-exec.log 2>&1\"; echo DISPATCH_RC=$?\n")
    ok &= drain("dispatch", 60)
if ok:
    time.sleep(20)
    send("echo ---PGREP-AFTER-DISPATCH---; pgrep -af 'Hyprland|quickshell|hyprlock|swww|qs'; echo ---QS-EXEC-LOG---; cat /tmp/qs-exec.log 2>&1 | head -n 80; echo ---HYPRLOG-TAIL---; tail -n 40 $(find /run/user/1000 -name 'hyprland.log' 2>/dev/null | head -1) 2>&1 | head -n 40\n")
    ok &= drain("after-dispatch", 60)
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
print(f"[qs-diag3] done ok={ok} qemu_rc={q.returncode}", flush=True)
sys.exit(0 if ok else 1)
