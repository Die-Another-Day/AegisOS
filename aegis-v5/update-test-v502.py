#!/usr/bin/env python3
"""Updater test for AegisOS v5.0.3 (streaming rewrite 2026-11-24).

Boots a COPY of the image in QEMU (serial console, no display) and
exercises aegis-update end to end. Serves all test fixtures from a local
HTTP server on the host (guest reaches it at 10.0.2.2:18080):

  1. Guest internet: curl https://api.github.com (real API) — records
     the HTTP code. If the guest cannot reach it, that is reported as a
     finding, not faked.
  2. `aegis-update check` against the REAL API (latest release at test
     time is v6.0.0; installed is 5.0.3, so expect an update to be
     available). This step is RECORDED, not gating: this VM's QEMU user
     networking has no external egress (proven by net-probe-v502: DNS
     gets no answer, TCP to the outside fails; only the 10.0.2.2 host
     channel works), so the real-API check is expected to fail HERE and
     is proven instead against the local fake API in step 2b.
  2b. `AEGIS_API_BASE=http://10.0.2.2:18080 aegis-update check` — the
     same code path against the fake release (v5.0.5, full image only).
  3. Bootstrap (AEGIS_RAW_BASE -> local server): installs the new
     streaming updater from source, installed hash is 28c906e7...,
     version stays 5.0.3.
  4. Non-root apply must refuse (exit 2, "needs root").
  5. Streaming full-image apply: `sudo env
     AEGIS_API_BASE=http://10.0.2.2:18080 aegis-update apply` against
     the FAKE release (v5.0.5, two parts + SHA256SUMS.txt served
     locally). Verifies: parts downloaded + checksummed + appended +
     deleted (no part files left), staged .xz byte-identical to the
     fixture (hash matches the release notes), the updater prints STOP
     with flashing instructions and does NOT touch the booted disk,
     version stays 5.0.3.

Patch-bundle tests are gone with the patch-bundle code (removed
2026-11-24: no bundle was ever published, no builder exists).

Usage: update-test-v502.py <image> <logfile>
"""
import hashlib
import json
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
SRC = Path(__file__).resolve().parent  # the aegis-v5 source folder
SERVE = Path("/tmp/aegis-update-test-serve")
PORT = 18080
HOST_URL = f"http://10.0.2.2:{PORT}"

NEW_UPDATER_HASH = "28c906e70365465ef2d5578125036e34147eca23a7d9b8b8e03b7c97797435c5"

# --- Build test fixtures on the host --------------------------------------
if SERVE.exists():
    shutil.rmtree(SERVE)
SERVE.mkdir(parents=True)

# Bootstrap files, served at the raw.githubusercontent.com layout.
for rel in ("aegis-v5/bootstrap-update.sh", "aegis-v5/wayland/aegis-shell.py",
            "aegis-v5/bin/aegis-gui", "aegis-v5/serial-shell-test-v501.py",
            "aegis-v5/bin/aegis-update"):
    src = SRC / rel.removeprefix("aegis-v5/")
    dst = SERVE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)

# Fake full image: a tiny xz, split into 2 parts, served with checksums.
fake_raw = SERVE / "fake.img"
fake_raw.write_bytes(b"AEGIS-FAKE-IMAGE-v5.0.5\n" * 100)
subprocess.run(["xz", "-k", "-f", str(fake_raw)], check=True)
fake_xz = SERVE / "fake.img.xz"
fake_xz_hash = hashlib.sha256(fake_xz.read_bytes()).hexdigest()
data = fake_xz.read_bytes()
half = len(data) // 2
(SERVE / "aegis-v5.img.xz.part-00").write_bytes(data[:half])
(SERVE / "aegis-v5.img.xz.part-01").write_bytes(data[half:])
sums = ""
for name in ("aegis-v5.img.xz.part-00", "aegis-v5.img.xz.part-01"):
    sums += f"{hashlib.sha256((SERVE / name).read_bytes()).hexdigest()}  {name}\n"
(SERVE / "SHA256SUMS.txt").write_text(sums)

fake_release = {
    "tag_name": "v5.0.5",
    "body": f"Fake release for updater testing.\n\nCompressed .xz SHA256: {fake_xz_hash}\n",
    "assets": [
        {"name": "aegis-v5.img.xz.part-00", "size": half,
         "browser_download_url": f"{HOST_URL}/aegis-v5.img.xz.part-00"},
        {"name": "aegis-v5.img.xz.part-01", "size": len(data) - half,
         "browser_download_url": f"{HOST_URL}/aegis-v5.img.xz.part-01"},
        {"name": "SHA256SUMS.txt", "size": len(sums),
         "browser_download_url": f"{HOST_URL}/SHA256SUMS.txt"},
    ],
}
api_dir = SERVE / "repos" / "Die-Another-Day" / "AegisOS" / "releases"
api_dir.mkdir(parents=True)
(api_dir / "latest").write_text(json.dumps(fake_release))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SERVE), **kw)
    def log_message(self, *a):
        pass

httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"[update-test] serving fixtures at http://127.0.0.1:{PORT} (guest: {HOST_URL})", flush=True)

# --- Boot a copy ------------------------------------------------------------
TEST_IMG = IMG + ".test"
print(f"[update-test] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
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
                print(f"\n[update-test] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[update-test] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[update-test] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label, timeout=180):
    # Wait for the marker to be EXECUTED, not merely typed: the tty
    # echoes input immediately, so waiting for the marker text alone
    # returns while the foreground command is still running. Require
    # the marker's output followed by a fresh shell prompt.
    _drain_n[0] += 1
    m = f"UPDDRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    pat = re.compile(m.encode() + rb"\r+\n.*?analyst@aegis", re.DOTALL)
    return wait_for(pat, timeout, f"drain {label}")

seg_start = [0]
def mark():
    seg_start[0] = len(buf)

def check(pat, label):
    global ok
    found = re.search(pat, buf[seg_start[0]:])
    print(f"[update-test] {'PASS' if found else 'FAIL'} {label}: {pat}", flush=True)
    ok = ok and bool(found)
    return bool(found)

def check_absent(pat, label):
    global ok
    found = re.search(pat, buf[seg_start[0]:])
    print(f"[update-test] {'PASS' if not found else 'FAIL'} {label} (absent): {pat}", flush=True)
    ok = ok and not found
    return not found

ok = True
SUDO = "echo secure | sudo -S"
ok &= wait_for(rb"aegis login:", 600, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
    # 1. Guest internet: real GitHub API. RECORDED, not gating — this
    # VM's QEMU user networking has no external egress (see net-probe
    # logs), so a failure here is an environment finding, not a bug.
    mark()
    send("echo MARK_UPD_NET; curl -s -o /tmp/api.json -w 'API_HTTP=%{http_code}\\n' --max-time 30 https://api.github.com/repos/Die-Another-Day/AegisOS/releases/latest; grep -o '\"tag_name\": \"[^\"]*\"' /tmp/api.json | head -1; echo; ip -brief addr\n")
    ok &= drain("net")
    if re.search(rb"API_HTTP=200", buf):
        print("[update-test] NOTE guest reaches api.github.com (API_HTTP=200)", flush=True)
    else:
        print("[update-test] NOTE guest CANNOT reach api.github.com "
              "(environment: QEMU user-net has no external egress here; "
              "real-API check proven via fake API in step 2b instead)", flush=True)
if ok:
    # 2. check against the real API (installed 5.0.3 vs latest v6.0.0).
    # Only meaningful if the net step above succeeded; otherwise the
    # updater must print its clear no-network message.
    mark()
    send("echo MARK_UPD_CHECK; cat /etc/aegis-version; which aegis-update; aegis-update check; echo CHECK_RC=$?\n")
    ok &= drain("check")
    check(rb"Installed version: 5\.0\.3", "installed version is 5.0.3")
    if re.search(rb"API_HTTP=200", buf):
        check(rb"Latest release:\s+v6\.0\.0", "latest release reported as v6.0.0")
        check(rb"Update available: v6\.0\.0", "check reports v6.0.0 update available")
    else:
        check(rb"cannot reach the GitHub API", "check fails gracefully with no network")
if ok:
    # 2b. Same check code path against the local fake API (v5.0.5).
    mark()
    send(f"echo MARK_UPD_CHECKFAKE; AEGIS_API_BASE={HOST_URL} aegis-update check; echo CHECKFAKE_RC=$?\n")
    ok &= drain("checkfake")
    check(rb"Latest release:\s+v5\.0\.5", "fake-API check reports v5.0.5")
    check(rb"Update available: v5\.0\.5 \(full image only", "fake-API check reports full-image update")
if ok:
    # 3. Bootstrap installs the new streaming updater from source.
    mark()
    send(f"echo MARK_UPD_BS; curl -fsSL {HOST_URL}/aegis-v5/bootstrap-update.sh -o /tmp/bootstrap-update.sh && {SUDO} env AEGIS_RAW_BASE={HOST_URL} bash /tmp/bootstrap-update.sh; echo BS_RC=$?; sha256sum /usr/local/bin/aegis-update; cat /etc/aegis-version\n")
    ok &= drain("bootstrap", timeout=240)
    check(rb"BS_RC=0", "bootstrap exit 0")
    check(re.escape(NEW_UPDATER_HASH).encode(), "new streaming updater installed")
    check(rb"5\.0\.3", "bootstrap leaves version at 5.0.3")
if ok:
    # 4. Non-root apply must refuse.
    mark()
    send("echo MARK_UPD_NOROOT; aegis-update apply; echo NOROOT_RC=$?\n")
    ok &= drain("noroot")
    check(rb"needs root", "non-root apply refused")
    check(rb"NOROOT_RC=2", "non-root apply exit 2")
if ok:
    # 5. Streaming full-image apply against the fake API.
    mark()
    send(f"echo MARK_UPD_FULL; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo FULL_RC=$?; cat /etc/aegis-version\n")
    ok &= drain("full", timeout=240)
    check(rb"aegis-v5\.img\.xz\.part-00: OK", "streaming apply verified part-00")
    check(rb"aegis-v5\.img\.xz\.part-01: OK", "streaming apply verified part-01")
    check(rb"matches the release notes", "streaming apply assembled hash matches")
    check(rb"STOP", "streaming apply prints STOP, does not install")
    check(rb"FULL_RC=0", "streaming apply exit 0")
    check(rb"5\.0\.3", "version file still 5.0.3 after apply")
if ok:
    # The staged .xz must be byte-identical to the fixture and no part
    # files may be left behind (deleted as they are appended).
    mark()
    send(f"echo MARK_UPD_LS; {SUDO} ls -l /var/lib/aegis/update/v5.0.5/; {SUDO} sha256sum /var/lib/aegis/update/v5.0.5/aegis-v5.img.xz\n")
    ok &= drain("ls")
    check(rb"-rw-r--r--.*aegis-v5\.img\.xz", "staged file aegis-v5.img.xz listed")
    check(re.escape(fake_xz_hash).encode(), "staged .xz byte-identical (sha256 matches fixture)")
    check_absent(rb"part-", "no part files left in update dir after streaming apply")
if ok:
    send("echo MARK_UPD_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
httpd.shutdown()
print(f"[update-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
