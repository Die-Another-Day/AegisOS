#!/usr/bin/env python3
"""Bootstrap test for AegisOS v5.0.2.

Boots a COPY of the shipped v5.0.0 image (which has no updater and no
/etc/aegis-version) and runs bootstrap-update.sh against a local HTTP
server on the host (guest: 10.0.2.2:18081), twice:

  1. TAMPERED run: the served aegis-gui has one byte flipped. The
     bootstrap must abort with HASH MISMATCH, exit non-zero, and
     install NOTHING (/etc/aegis-version still absent, no aegis-update).
  2. GOOD run: the server file is swapped back to the genuine one.
     The bootstrap must succeed and install all four files with the
     exact expected hashes, write /etc/aegis-version as 5.0.1, and
     `aegis-update check` must run (reporting 5.0.1 + the graceful
     no-network message — this VM's QEMU user-net has no external
     egress, proven in net-probe-v502).

Usage: bootstrap-test-v502.py <v500-image> <logfile>
"""
import hashlib
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

IMG, LOG = sys.argv[1], sys.argv[2]
SRC = Path(__file__).resolve().parent  # the aegis-v5 source folder (this script lives in it)
SERVE = Path("/tmp/aegis-bootstrap-test-serve")
PORT = 18081
HOST_URL = f"http://10.0.2.2:{PORT}"

EXPECTED = {
    "aegis-v5/wayland/aegis-shell.py": "a862c7aa67987f82f5dd94e38fd4fe9c0c53b0cda64a74c4033cdfe49ea60edb",
    "aegis-v5/bin/aegis-gui": "9c96c90f343f7945b4a71f95a0db59537fa29a0509ce356243ab42d02cc2058d",  # v5.0.2 preflight guard
    "aegis-v5/serial-shell-test-v501.py": "53e0703bdd1400d7a0e36ba805ee2a5ba71b1a3e13b42a50b7f3b806b5154a6b",
    "aegis-v5/bin/aegis-update": "a17a47bb25504514557362e13e87aa802e9411f2e2af53cf3494e79796daea63",
}

if SERVE.exists():
    shutil.rmtree(SERVE)
for rel in list(EXPECTED) + ["aegis-v5/bootstrap-update.sh"]:
    # rel is the raw.githubusercontent.com path (aegis-v5/...); the local
    # source lives under SRC itself, so strip the prefix for the copy.
    src = SRC / rel.removeprefix("aegis-v5/")
    dst = SERVE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
# Tamper the served aegis-gui for run 1 (flip one byte).
gui = SERVE / "aegis-v5/bin/aegis-gui"
data = bytearray(gui.read_bytes())
data[100] ^= 0xFF
gui.write_bytes(bytes(data))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SERVE), **kw)
    def log_message(self, *a):
        pass

httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"[bootstrap-test] serving at http://127.0.0.1:{PORT} (guest: {HOST_URL})", flush=True)

TEST_IMG = IMG + ".test"
print(f"[bootstrap-test] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
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
                print(f"\n[bootstrap-test] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[bootstrap-test] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[bootstrap-test] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label, timeout=180):
    # Wait for the marker to be EXECUTED, not merely typed: the tty
    # echoes input immediately, so waiting for the marker text alone
    # returns while the foreground command is still running. Require
    # the marker's output followed by a fresh shell prompt.
    _drain_n[0] += 1
    m = f"BSDRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    pat = re.compile(m.encode() + rb"\r+\n.*?analyst@aegis", re.DOTALL)
    return wait_for(pat, timeout, f"drain {label}")

def check(pat, label):
    global ok
    found = re.search(pat, buf)
    print(f"[bootstrap-test] {'PASS' if found else 'FAIL'} {label}: {pat}", flush=True)
    ok = ok and bool(found)
    return bool(found)

ok = True
SUDO = "echo secure | sudo -S"
ok &= wait_for(rb"aegis login:", 600, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
    # Precondition: v5.0.0 has no updater and no version file.
    send("echo MARK_BS_PRE; ls /etc/aegis-version 2>&1; which aegis-update 2>&1; echo PRE_DONE\n")
    ok &= drain("pre")
    check(rb"No such file or directory", "v5.0.0 has no /etc/aegis-version")
if ok:
    # Run 1: tampered aegis-gui served — must abort, install nothing.
    send(f"echo MARK_BS_TAMPER; curl -fsSL {HOST_URL}/aegis-v5/bootstrap-update.sh -o /tmp/bootstrap-update.sh && {SUDO} env AEGIS_RAW_BASE={HOST_URL} bash /tmp/bootstrap-update.sh; echo BS_TAMPER_RC=$?; ls /etc/aegis-version 2>&1; which aegis-update 2>&1\n")
    ok &= drain("tamper", timeout=240)
    check(rb"HASH MISMATCH", "tampered run aborts on hash mismatch")
    check(rb"BS_TAMPER_RC=1", "tampered run exit non-zero")
if ok:
    # Swap the genuine file back in on the host, then run 2 (good).
    shutil.copyfile(SRC / "bin/aegis-gui", SERVE / "aegis-v5/bin/aegis-gui")
    print("[bootstrap-test] host: restored genuine aegis-gui on the server", flush=True)
    send(f"echo MARK_BS_GOOD; curl -fsSL {HOST_URL}/aegis-v5/bootstrap-update.sh -o /tmp/bootstrap-update.sh && {SUDO} env AEGIS_RAW_BASE={HOST_URL} bash /tmp/bootstrap-update.sh; echo BS_GOOD_RC=$?; cat /etc/aegis-version; sha256sum /usr/local/lib/aegis-shell/aegis-shell.py /usr/local/bin/aegis-gui /usr/local/bin/aegis-update /usr/local/bin/serial-shell-test-v501.py; aegis-update check; echo CHECK_RC=$?\n")
    ok &= drain("good", timeout=240)
    check(rb"BS_GOOD_RC=0", "good run exit 0")
    check(rb"5\.0\.1", "version file reads 5.0.1")
    for rel, h in EXPECTED.items():
        check(re.escape(h).encode(), f"installed hash matches for {rel}")
    check(rb"Installed version: 5\.0\.1", "aegis-update check reports 5.0.1")
if ok:
    send("echo MARK_BS_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
httpd.shutdown()
print(f"[bootstrap-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
