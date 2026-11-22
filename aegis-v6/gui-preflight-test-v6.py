#!/usr/bin/env python3
"""Serial-console preflight test for AegisOS v6.0.0 (aegis-gui guard).

Boots a COPY of the image in QEMU with no graphical display attached
(-display none, serial stdio) and runs aegis-gui from the serial console,
where Hyprland can never start (no VT/seat).

Expected on a FIXED image:
  * `aegis-gui` and `aegis-gui --lock` print the clear preflight message
    fast (well under the old ~12 s libseat wait), exit 1, and produce
    ZERO libseat spam and ZERO tracebacks.
  * `aegis-gui --stop` and `aegis-gui --help` still work from the serial
    console (exit 0) — they are non-GUI modes.
  * `aegis-gui --restart-shell` is preflight-blocked the same way
    (exit 1, no-display message) — there is no session to restart.

Usage: gui-preflight-test-v6.py <image> <logfile>
"""
import os, pty, re, select, shutil, subprocess, sys, time
from pathlib import Path

IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".test"
print(f"[preflight-test] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
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
     "-display", "none", "-serial", "stdio", "-monitor", "none"],
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
                print(f"\n[preflight-test] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[preflight-test] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[preflight-test] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label, timeout=120):
    _drain_n[0] += 1
    m = f"PFDRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    return wait_for(m.encode(), timeout, f"drain {label}")

def check(pat, label):
    global buf
    if re.search(pat, buf):
        print(f"[preflight-test] CHECK PASS {label}", flush=True); return True
    print(f"[preflight-test] CHECK FAIL {label}: {pat}", flush=True); return False

ok = True
ok &= wait_for(rb"aegis login:", 600, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
    send("echo MARK_PF_ENV; tty; echo ---; which aegis-gui; aegis-gui --help | head -3\n")
    ok &= drain("env")
if ok:
    # Main case: plain aegis-gui from the serial console. Must fail fast
    # with the preflight message, exit 1, no libseat output.
    send("echo MARK_PF_GUI; START=$(date +%s); aegis-gui 2>&1; echo GUI_RC=$?; END=$(date +%s); echo GUI_SECS=$((END-START))\n")
    ok &= drain("gui")
    ok &= check(rb"no graphical display here", "gui preflight message")
    ok &= check(rb"GUI_RC=1", "gui exit 1")
    ok &= check(rb"GUI_SECS=[0-9]\b", "gui fast (single-digit seconds)")
    ok &= check(rb"GUI_SECS=0|GUI_SECS=1|GUI_SECS=2", "gui under 3 s")
    # NB: the preflight message itself mentions the word "libseat", so
    # look for real libseat error output, not the bare word.
    if re.search(rb"\[libseat\]|Could not open target tty|Failed to start a DRM session", buf):
        print("[preflight-test] CHECK FAIL gui produced libseat spam", flush=True); ok = False
    else:
        print("[preflight-test] CHECK PASS gui zero libseat spam", flush=True)
    if re.search(rb"Traceback", buf):
        print("[preflight-test] CHECK FAIL gui traceback", flush=True); ok = False
    else:
        print("[preflight-test] CHECK PASS gui zero tracebacks", flush=True)
if ok:
    # --lock is a GUI mode too: same preflight behaviour.
    send("echo MARK_PF_LOCK; START=$(date +%s); aegis-gui --lock 2>&1; echo LOCK_RC=$?; END=$(date +%s); echo LOCK_SECS=$((END-START))\n")
    ok &= drain("lock")
    ok &= check(rb"no graphical display here", "lock preflight message")
    ok &= check(rb"LOCK_RC=1", "lock exit 1")
if ok:
    # Controls: non-GUI modes must still work from the serial console.
    send("echo MARK_PF_STOP; aegis-gui --stop; echo STOP_RC=$?\n")
    ok &= drain("stop")
    ok &= check(rb"GUI stopped", "stop works")
    ok &= check(rb"STOP_RC=0", "stop exit 0")
if ok:
    send("echo MARK_PF_HELP; aegis-gui --help >/dev/null; echo HELP_RC=$?\n")
    ok &= drain("help")
    ok &= check(rb"HELP_RC=0", "help exit 0")
if ok:
    # --restart-shell is preflight-blocked too: without a Hyprland
    # session it fails fast with the no-display message (exit 1)
    # and the login shell continues (no exec).
    send("echo MARK_PF_RESTART; aegis-gui --restart-shell 2>&1; echo RESTART_RC=$?\n")
    ok &= drain("restart-shell")
    ok &= check(rb"no graphical display here", "restart shell message")
    ok &= check(rb"RESTART_RC=1", "restart shell exit 1")
if ok:
    # The session never ended (restart-shell is guarded, not exec), so
    # just power off from the still-logged-in shell.
    send("echo MARK_PF_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[preflight-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
