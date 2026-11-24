#!/usr/bin/env python3
"""Updater test for AegisOS v6.0.0 (streaming rewrite 2026-11-24).

Boots a COPY of the image in QEMU (serial console, no display) and
exercises aegis-update end to end. Serves all test fixtures from a local
HTTP server on the host (guest reaches it at 10.0.2.2:18080):

  1. Guest internet: curl https://api.github.com (real API) — records
     the HTTP code. If the guest cannot reach it, that is reported as a
     finding, not faked.
  2. `aegis-update check` against the REAL API (latest release at test
     time is v6.0.0; installed is 6.0.0, so expect "You are up to
     date"). This step is RECORDED, not gating: this VM's QEMU user
     networking has no external egress (proven by net-probe-v502: DNS
     gets no answer, TCP to the outside fails; only the 10.0.2.2 host
     channel works), so the real-API check is expected to fail HERE and
     is proven instead against the local fake API in step 2b.
  2b. `AEGIS_API_BASE=http://10.0.2.2:18080 aegis-update check` — the
     same code path against the fake release (v6.0.2, full image only).
  3. Bootstrap (AEGIS_RAW_BASE -> local server): installs the new
     streaming updater from source, installed hash is 28c906e7....
  4. Non-root apply must refuse (exit 2, "needs root").
  5. Streaming full-image apply: `sudo env
     AEGIS_API_BASE=http://10.0.2.2:18080 aegis-update apply` against
     the FAKE release (v6.0.2, two parts + SHA256SUMS.txt served
     locally). Verifies: parts downloaded + checksummed + appended +
     deleted (no part files left), staged .xz byte-identical to the
     fixture (hash matches the release notes), peak disk during the run
     under total + largest part + 1 MiB, the updater prints STOP with
     flashing instructions and does NOT touch the booted disk, version
     stays 6.0.0.
  6. Resume (valid): apply again with the staged image present skips
     the download entirely, prints "already staged" + STOP, exit 0.
  7. Resume (corrupt): the staged image is corrupted in place; apply
     deletes it and re-downloads, hash matches again, STOP, exit 0.
  8. Tampered part: the fake API is swapped to a v6.0.3 release whose
     part-01 bytes are flipped (SHA256SUMS.txt keeps the good hashes);
     apply must die with a checksum mismatch, exit 1, and leave no
     partial .xz and no part files behind.

Patch-bundle tests are gone with the patch-bundle code (removed
2026-11-24: no bundle was ever published, no builder exists).

Usage: update-test-v6.py <image> <logfile>
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
SRC = Path(__file__).resolve().parent  # the aegis-v6 source folder
SERVE = Path("/tmp/aegis-update-test-serve")
PORT = 18080
HOST_URL = f"http://10.0.2.2:{PORT}"

NEW_UPDATER_HASH = "28c906e70365465ef2d5578125036e34147eca23a7d9b8b8e03b7c97797435c5"

# --- Build test fixtures on the host --------------------------------------
if SERVE.exists():
    shutil.rmtree(SERVE)
SERVE.mkdir(parents=True)

# Bootstrap files, served at the raw.githubusercontent.com layout.
for rel in ("aegis-v6/bootstrap-update.sh", "aegis-v6/src/bin/aegis-gui",
            "aegis-v6/bin/aegis-tools", "aegis-v6/src/bin/aegis-update"):
    src = SRC / rel.removeprefix("aegis-v6/")
    dst = SERVE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def make_fake_image(prefix, data_bytes, tag, outdir=None, tamper=None):
    """Build a fake full image: random data -> xz -> 2 parts + sums.
    Returns (release dict, total part bytes, largest part bytes,
    SHA256SUMS text, .xz SHA256). When tamper is a part index, the
    SERVED bytes of that part are flipped but SHA256SUMS.txt keeps the
    good hashes. A tampered fixture is built into its own outdir and
    only copied into SERVE when its release is activated."""
    outdir = outdir or SERVE
    outdir.mkdir(parents=True, exist_ok=True)
    raw = outdir / f"fake-{prefix}.img"
    raw.write_bytes(data_bytes)
    subprocess.run(["xz", "-k", "-f", str(raw)], check=True)
    xz = outdir / f"fake-{prefix}.img.xz"
    xz_hash = hashlib.sha256(xz.read_bytes()).hexdigest()
    data = xz.read_bytes()
    half = len(data) // 2
    chunks = (data[:half], data[half:])
    names = []
    for i, chunk in enumerate(chunks):
        name = f"aegis-{prefix}.img.xz.part-{i:02d}"
        served = bytearray(chunk)
        if tamper == i:
            served[0] ^= 0xFF
        (outdir / name).write_bytes(bytes(served))
        names.append(name)
    sums = ""
    for name, chunk in zip(names, chunks):
        sums += f"{hashlib.sha256(chunk).hexdigest()}  {name}\n"
    (outdir / f"SHA256SUMS-{prefix}.txt").write_text(sums)
    assets = []
    for name in names:
        assets.append({"name": name, "size": (outdir / name).stat().st_size,
                       "browser_download_url": f"{HOST_URL}/{name}"})
    assets.append({"name": "SHA256SUMS.txt", "size": len(sums),
                   "browser_download_url": f"{HOST_URL}/SHA256SUMS.txt"})
    release = {
        "tag_name": tag,
        "body": (f"Fake release {tag} for updater testing.\n\n"
                 f"Compressed .xz SHA256: {xz_hash}\n"),
        "assets": assets,
    }
    total = sum(len(c) for c in chunks)
    largest = max(len(c) for c in chunks)
    return release, total, largest, sums, xz_hash


# Fake full image: 3 MiB of incompressible data -> ~3 MiB .xz.
fake_release, fake_total, fake_largest, fake_sums, fake_xz_hash = make_fake_image(
    "v6", os.urandom(3 * 1024 * 1024), "v6.0.2")
FAKE_MB = fake_total // (1024 * 1024)
PEAK_BOUND = fake_total + fake_largest + 1024 * 1024
# Tampered v6.0.3: part-01 served corrupted, sums keep the good hashes.
t_dir = SERVE / "tampered-v6.0.3"
t_release, t_total, t_largest, t_sums, t_xz_hash = make_fake_image(
    "v6", os.urandom(2 * 1024 * 1024), "v6.0.3", outdir=t_dir, tamper=1)
print(f"[update-test] fake v6.0.2 total {fake_total} bytes (~{FAKE_MB} MB); "
      f"peak bound {PEAK_BOUND} bytes", flush=True)

api_dir = SERVE / "repos" / "Die-Another-Day" / "AegisOS" / "releases"
api_dir.mkdir(parents=True)


def swap_release(release, sums, part_dir=None):
    if part_dir is not None:
        for p in Path(part_dir).glob("aegis-*.img.xz.part-*"):
            shutil.copyfile(p, SERVE / p.name)
    (api_dir / "latest").write_text(json.dumps(release))
    (SERVE / "SHA256SUMS.txt").write_text(sums)


swap_release(fake_release, fake_sums)


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
    logf.write(b)
    sys.stdout.buffer.write(b)
    sys.stdout.buffer.flush()


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
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            emit(data)
            buf += data
            if re.search(pat, buf):
                print(f"\n[update-test] MATCH {label}\n", flush=True)
                return True
        if q.poll() is not None:
            print(f"\n[update-test] QEMU EXITED rc={q.returncode}\n", flush=True)
            return False
    print(f"\n[update-test] TIMEOUT {label}: {pat}\n", flush=True)
    return False


def send(s):
    os.write(master, s.encode())
    time.sleep(1.0)


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
    send("analyst\n")
    ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n")
    ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
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
    # 2. check against the real API (installed 6.0.0 vs latest v6.0.0).
    # Only meaningful if the net step above succeeded; otherwise the
    # updater must print its clear no-network message.
    mark()
    send("echo MARK_UPD_CHECK; cat /etc/aegis-version; which aegis-update; aegis-update check; echo CHECK_RC=$?\n")
    ok &= drain("check")
    check(rb"Installed version: 6\.0\.0", "installed version is 6.0.0")
    if re.search(rb"API_HTTP=200", buf):
        check(rb"Latest release:\s+v6\.0\.0", "latest release reported as v6.0.0")
        check(rb"You are up to date", "check reports up to date")
    else:
        check(rb"cannot reach the GitHub API", "check fails gracefully with no network")
if ok:
    # 2b. Same check code path against the local fake API (v6.0.2).
    # NOTE: this still runs the OLD updater shipped in the image, whose
    # check hardcodes "~400 MB" — the real size only appears after the
    # bootstrap (step 3) installs the new updater.
    mark()
    send(f"echo MARK_UPD_CHECKFAKE; AEGIS_API_BASE={HOST_URL} aegis-update check; echo CHECKFAKE_RC=$?\n")
    ok &= drain("checkfake")
    check(rb"Latest release:\s+v6\.0\.2", "fake-API check reports v6.0.2")
    check(rb"Update available: v6\.0\.2 \(full image only, ~400 MB download\)",
          "old updater check prints hardcoded ~400 MB")
if ok:
    # 3. Bootstrap installs the new streaming updater from source.
    mark()
    send(f"echo MARK_UPD_BS; curl -fsSL {HOST_URL}/aegis-v6/bootstrap-update.sh -o /tmp/bootstrap-update.sh && {SUDO} env AEGIS_RAW_BASE={HOST_URL} bash /tmp/bootstrap-update.sh; echo BS_RC=$?; sha256sum /usr/local/bin/aegis-update; cat /etc/aegis-version\n")
    ok &= drain("bootstrap", timeout=240)
    check(rb"BS_RC=0", "bootstrap exit 0")
    check(re.escape(NEW_UPDATER_HASH).encode(), "new streaming updater installed")
    check(rb"6\.0\.0", "bootstrap leaves version at 6.0.0")
if ok:
    # 3b. The NEW updater's check against the fake API reports the real
    # summed size (~3 MB for the fake parts), not the hardcoded ~400 MB.
    mark()
    send(f"echo MARK_UPD_CHECKNEW; AEGIS_API_BASE={HOST_URL} aegis-update check; echo CHECKNEW_RC=$?\n")
    ok &= drain("checknew")
    check(rb"Latest release:\s+v6\.0\.2", "new updater check reports v6.0.2")
    check(f"Update available: v6\\.0\\.2 \\(full image only, ~{FAKE_MB} MB download\\)".encode(),
          f"new updater check reports real size ~{FAKE_MB} MB")
if ok:
    # 4. Non-root apply must refuse.
    mark()
    send("echo MARK_UPD_NOROOT; aegis-update apply; echo NOROOT_RC=$?\n")
    ok &= drain("noroot")
    check(rb"needs root", "non-root apply refused")
    check(rb"NOROOT_RC=2", "non-root apply exit 2")
if ok:
    # 5. Streaming full-image apply, with a background du sampler
    # recording peak disk use of the update dir during the run.
    send("echo MARK_UPD_DU_START; rm -f /tmp/du.log /tmp/du.pid; echo secure | sudo -S sh -c 'echo $$ > /tmp/du.pid; while true; do du -sb /var/lib/aegis/update 2>/dev/null | cut -f1 >> /tmp/du.log; sleep 0.05; done' >/dev/null 2>&1 & echo DU_STARTED\n")
    ok &= drain("du-start")
    mark()
    send(f"echo MARK_UPD_FULL; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo FULL_RC=$?; cat /etc/aegis-version\n")
    ok &= drain("full", timeout=240)
    check(rb"aegis-v6\.img\.xz\.part-00: OK", "streaming apply verified part-00")
    check(rb"aegis-v6\.img\.xz\.part-01: OK", "streaming apply verified part-01")
    check(rb"matches the release notes", "streaming apply assembled hash matches")
    check(rb"STOP", "streaming apply prints STOP, does not install")
    check(rb"FULL_RC=0", "streaming apply exit 0")
    check(rb"6\.0\.0", "version file still 6.0.0 after apply")
if ok:
    mark()
    send(f"echo MARK_UPD_DU_STOP; kill $(cat /tmp/du.pid) 2>/dev/null; sleep 0.5; wc -l /tmp/du.log; PEAK=$(sort -n /tmp/du.log 2>/dev/null | tail -1); [ -n \"$PEAK\" ] || PEAK=0; echo PEAK=$PEAK BOUND={PEAK_BOUND}; [ \"$PEAK\" -le {PEAK_BOUND} ] && echo PEAK_OK || echo PEAK_TOO_HIGH\n")
    ok &= drain("du-stop")
    check(rb"PEAK_OK", "peak disk during streaming apply under total + largest part + 1 MiB")
if ok:
    # The staged .xz must be byte-identical to the fixture and no part
    # files may be left behind (deleted as they are appended).
    mark()
    send(f"echo MARK_UPD_LS; {SUDO} ls -l /var/lib/aegis/update/v6.0.2/; {SUDO} sha256sum /var/lib/aegis/update/v6.0.2/aegis-v6.img.xz\n")
    ok &= drain("ls")
    check(rb"-rw-r--r--.*aegis-v6\.img\.xz", "staged file aegis-v6.img.xz listed")
    check(re.escape(fake_xz_hash).encode(), "staged .xz byte-identical (sha256 matches fixture)")
    check_absent(rb"part-", "no part files left in update dir after streaming apply")
if ok:
    # 6. Resume (valid): apply again with the staged image present.
    mark()
    send(f"echo MARK_UPD_RESUME; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo RESUME_RC=$?\n")
    ok &= drain("resume", timeout=240)
    check(rb"already staged", "resume prints already-staged")
    check(rb"STOP", "resume prints STOP")
    check(rb"RESUME_RC=0", "resume apply exit 0")
    check_absent(rb"downloading", "resume downloads nothing")
if ok:
    # 7. Resume (corrupt): corrupt the staged image in place; apply
    # must delete it and re-download (size is unchanged, so only the
    # release-notes hash check can catch this).
    mark()
    send(f"echo MARK_UPD_CORRUPT; {SUDO} dd if=/dev/zero of=/var/lib/aegis/update/v6.0.2/aegis-v6.img.xz bs=32 count=1 seek=3 conv=notrunc; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo CORRUPT_RC=$?\n")
    ok &= drain("corrupt", timeout=240)
    check(rb"incomplete or corrupt", "corrupt staged image detected")
    check(rb"downloading", "corrupt staged image triggers re-download")
    check(rb"aegis-v6\.img\.xz\.part-00: OK", "re-download part-00 checksum OK")
    check(rb"matches the release notes", "re-downloaded hash matches release notes")
    check(rb"STOP", "corrupt-resume prints STOP")
    check(rb"CORRUPT_RC=0", "corrupt-resume apply exit 0")
if ok:
    # 8. Tampered part: swap the fake API to a v6.0.3 release whose
    # part-01 bytes are flipped (sums keep the good hashes).
    swap_release(t_release, t_sums, part_dir=t_dir)
    print("[update-test] host: fake API swapped to tampered v6.0.3 release", flush=True)
    mark()
    send(f"echo MARK_UPD_TAMPER; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo TAMPER_RC=$?; {SUDO} ls -l /var/lib/aegis/update/v6.0.3/; test ! -e /var/lib/aegis/update/v6.0.3/aegis-v6.img.xz && echo NO_XZ_LEFT; ls /var/lib/aegis/update/v6.0.3/ | grep -q part- && echo PARTS_LEFT || echo NO_PARTS_LEFT\n")
    ok &= drain("tamper", timeout=240)
    check(rb"checksum mismatch for aegis-v6\.img\.xz\.part-01", "tampered part refused on checksum mismatch")
    check(rb"TAMPER_RC=1", "tampered apply exit non-zero")
    check(rb"NO_XZ_LEFT", "tampered apply leaves no partial final file")
    check(rb"NO_PARTS_LEFT", "tampered apply leaves no part files")
if ok:
    send("echo MARK_UPD_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try:
    q.terminate()
except Exception:
    pass
try:
    q.wait(timeout=25)
except Exception:
    q.kill()
httpd.shutdown()
print(f"[update-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close()
sys.exit(0 if ok else 1)
