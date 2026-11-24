#!/usr/bin/env python3
"""Bootstrap test for AegisOS v6.0.0.

Boots a COPY of the shipped v6.0.0 image (which HAS aegis-update and
/etc/aegis-version, unlike v5.0.0) and runs bootstrap-update.sh against
a local HTTP server on the host (guest: 10.0.2.2:18081), three times:

  1. TAMPERED run: the served aegis-gui has one byte flipped. The
     bootstrap must abort with HASH MISMATCH, exit non-zero, and
     install NOTHING (installed files keep their genuine hashes,
     /etc/aegis-version still reads 6.0.0).
  2. GOOD run: the server file is swapped back to the genuine one.
     The bootstrap must succeed, install all three files with the
     exact expected hashes, write /etc/aegis-version as 6.0.0, and
     `aegis-update check` must run (reporting 6.0.0 + the graceful
     no-network message — this VM's QEMU user-net has no external
     egress, proven in net-probe-v502).
  3. INSTALL-FAILURE run: a directory sits where
     /usr/local/bin/aegis-update should be. The bootstrap must fail
     with INSTALL FAILED naming the file, exit non-zero, write no
     version file, and print no "done".

Usage: bootstrap-test-v6.py <v6-image> <logfile>
"""
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
SRC = Path(__file__).resolve().parent  # the aegis-v6 source folder (this script lives in it)
SERVE = Path("/tmp/aegis-bootstrap-test-serve")
PORT = 18081
HOST_URL = f"http://10.0.2.2:{PORT}"

# Recomputed 2026-11-24 after the streaming rewrite (aegis-update);
# keep in sync with bootstrap-update.sh.
EXPECTED = {
    "aegis-v6/src/bin/aegis-gui": "943532f09479b61dbeed0b4272beecf6312d0757cb421141c795b16496f247a6",
    "aegis-v6/bin/aegis-tools": "7c3930e8fcfd8bac9cbdf3e5c64ebccbc1b21f6fd79eb182ce16df3d6470a22c",
    "aegis-v6/src/bin/aegis-update": "28c906e70365465ef2d5578125036e34147eca23a7d9b8b8e03b7c97797435c5",
}

# The v6.0.0 image ships the OLD updater (222cf879...); only the
# bootstrap installs the new one. So the tampered run (which installs
# nothing) must leave the OLD updater hash in place, while aegis-gui
# and aegis-tools are unchanged files whose shipped hash already
# equals EXPECTED.
SHIPPED = {
    "aegis-v6/src/bin/aegis-gui": "943532f09479b61dbeed0b4272beecf6312d0757cb421141c795b16496f247a6",
    "aegis-v6/bin/aegis-tools": "7c3930e8fcfd8bac9cbdf3e5c64ebccbc1b21f6fd79eb182ce16df3d6470a22c",
    "aegis-v6/src/bin/aegis-update": "222cf879c5c6204e4b41ed2f9688122adb899173b4c07e394c4410a1d31fbefb",
}

if SERVE.exists():
    shutil.rmtree(SERVE)
for rel in list(EXPECTED) + ["aegis-v6/bootstrap-update.sh"]:
    # rel is the raw.githubusercontent.com path (aegis-v6/...); the local
    # source lives under SRC itself, so strip the prefix for the copy.
    src = SRC / rel.removeprefix("aegis-v6/")
    dst = SERVE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
# Tamper the served aegis-gui for run 1 (flip one byte).
gui = SERVE / "aegis-v6/src/bin/aegis-gui"
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
    # Precondition: v6.0.0 ships the updater and the version file.
    send("echo MARK_BS_PRE; cat /etc/aegis-version; which aegis-update aegis-gui aegis-tools; echo PRE_DONE\n")
    ok &= drain("pre")
    check(rb"6\.0\.0", "v6.0.0 has /etc/aegis-version 6.0.0")
    check(rb"/usr/local/bin/aegis-update", "v6.0.0 has aegis-update")
if ok:
    # Run 1: tampered aegis-gui served — must abort, install nothing.
    send(f"echo MARK_BS_TAMPER; curl -fsSL {HOST_URL}/aegis-v6/bootstrap-update.sh -o /tmp/bootstrap-update.sh && {SUDO} env AEGIS_RAW_BASE={HOST_URL} bash /tmp/bootstrap-update.sh; echo BS_TAMPER_RC=$?; cat /etc/aegis-version; sha256sum /usr/local/bin/aegis-gui /usr/local/bin/aegis-tools /usr/local/bin/aegis-update\n")
    ok &= drain("tamper", timeout=240)
    check(rb"HASH MISMATCH", "tampered run aborts on hash mismatch")
    check(rb"BS_TAMPER_RC=1", "tampered run exit non-zero")
    for rel, h in SHIPPED.items():
        check(re.escape(h).encode(), f"tampered run left genuine hash for {rel}")
if ok:
    # Swap the genuine file back in on the host, then run 2 (good).
    shutil.copyfile(SRC / "src/bin/aegis-gui", SERVE / "aegis-v6/src/bin/aegis-gui")
    print("[bootstrap-test] host: restored genuine aegis-gui on the server", flush=True)
    send(f"echo MARK_BS_GOOD; curl -fsSL {HOST_URL}/aegis-v6/bootstrap-update.sh -o /tmp/bootstrap-update.sh && {SUDO} env AEGIS_RAW_BASE={HOST_URL} bash /tmp/bootstrap-update.sh; echo BS_GOOD_RC=$?; cat /etc/aegis-version; sha256sum /usr/local/bin/aegis-gui /usr/local/bin/aegis-tools /usr/local/bin/aegis-update; aegis-update check; echo CHECK_RC=$?\n")
    ok &= drain("good", timeout=240)
    check(rb"BS_GOOD_RC=0", "good run exit 0")
    check(rb"6\.0\.0", "version file reads 6.0.0")
    for rel, h in EXPECTED.items():
        check(re.escape(h).encode(), f"installed hash matches for {rel}")
    check(rb"Installed version: 6\.0\.0", "aegis-update check reports 6.0.0")
if ok:
    # Run 3: install failure must NOT print "done".
    # Simulate a corrupted/unwritable destination: a directory sits
    # where /usr/local/bin/aegis-update should be. (cp copies INTO
    # the directory, so the failure surfaces in the post-install
    # SHA256 check — sha256sum on a directory path fails.) The good
    # run installed a real file there, so rm it first or mkdir fails
    # with "File exists" and the simulation never happens. Also
    # remove the version file first so a false "done" would be visible
    # (a failed run must leave it absent). NOTE: buf accumulates the
    # whole run, and run 2 legitimately printed "done" — so scope
    # these checks to the run-3 segment only (buf from seg_start on).
    seg_start = len(buf)
    send(f"echo MARK_BS_INSTALLFAIL; {SUDO} rm -f /etc/aegis-version; {SUDO} rm -f /usr/local/bin/aegis-update; {SUDO} mkdir -p /usr/local/bin/aegis-update; curl -fsSL {HOST_URL}/aegis-v6/bootstrap-update.sh -o /tmp/bootstrap-update.sh && {SUDO} env AEGIS_RAW_BASE={HOST_URL} bash /tmp/bootstrap-update.sh; echo BS_INSTALLFAIL_RC=$?; ls /etc/aegis-version 2>&1\n")
    ok &= drain("installfail", timeout=240)
    seg = buf[seg_start:]
    def check_seg(pat, label):
        global ok
        found = re.search(pat, seg)
        print(f"[bootstrap-test] {'PASS' if found else 'FAIL'} {label}: {pat}", flush=True)
        ok = ok and bool(found)
        return bool(found)
    check_seg(rb"INSTALL FAILED.*aegis-update", "install failure names the file")
    check_seg(rb"BS_INSTALLFAIL_RC=1", "install-failure run exit non-zero")
    check_seg(rb"cannot access '/etc/aegis-version': No such file or directory", "install-failure run writes no version file")
    if re.search(rb"bootstrap-update: done", seg):
        print("[bootstrap-test] FAIL install-failure run printed 'done'", flush=True)
        ok = False
    else:
        print("[bootstrap-test] PASS install-failure run printed no 'done'", flush=True)
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
