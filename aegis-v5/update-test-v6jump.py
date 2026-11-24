#!/usr/bin/env python3
"""Updater v5->v6 jump test (hotfix 2026-11-23, streaming rewrite 2026-11-24).

Boots a COPY of the shipped v5.0.3 image in QEMU (serial console, no
display) and proves the fixed updater can fetch a v6 full image. Serves
all fixtures from a local HTTP server on the host (guest reaches it at
10.0.2.2:18082):

  0. Precondition: the image ships the OLD updater (hash a17a47bb...)
     and /etc/aegis-version reads 5.0.3.
  1. BUG REPRODUCTION with the old updater, against a FAKE v6.0.0
     release (two v6 parts + SHA256SUMS.txt): `check` reports v6.0.0
     available (with the old hardcoded "~400 MB"); `apply` must die
     with "no patch bundle and no complete image parts" — the exact
     failure the user saw on his VM.
  2. Bootstrap (AEGIS_RAW_BASE -> local server, same one-liner the
     user runs): installs the fixed updater, leaves /etc/aegis-version
     at 5.0.3, installed hash is the new one (28c906e7...).
  3. `check` against the fake v6.0.0 release with the FIXED updater:
     reports v6.0.0 available with the REAL summed size (~3 MB for the
     fake parts — the size comes from the release's asset sizes, not a
     hardcoded number).
  4. `apply` against the fake v6.0.0 release: STREAMS the v6 parts
     (download, verify, append, delete — no combine step), produces a
     byte-identical aegis-v6.img.xz (hash matching the release notes),
     leaves no part files behind, prints STOP, exit 0, version file
     still 5.0.3 (the fallback never touches the booted disk). Peak
     disk during the run is sampled and must stay under
     total + largest part + 1 MiB.
  4b. RESUME (valid): `apply` again with the staged image present
     skips the download entirely, prints "already staged" + STOP,
     exit 0.
  4c. RESUME (corrupt): the staged image is corrupted in place;
     `apply` deletes it and re-downloads, hash matches again, STOP.
  5. REGRESSION: the fake API is swapped to a v5.0.5 release (v5 parts);
     the same updater must still check + apply it (aegis-v5.img.xz).
  6. TAMPERED PART: the fake API is swapped to a v6.0.1 release whose
     part-01 bytes are flipped (SHA256SUMS.txt keeps the good hashes);
     `apply` must die with a checksum mismatch, exit 1, and leave no
     partial .xz and no part files behind.

Real-GitHub-API testing is impossible from this sandbox (no external
egress, proven in net-probe-v502); the real proof will be the user
running the bootstrap + `sudo aegis-update apply` on his VM.

Usage: update-test-v6jump.py <v503-image> <logfile>
"""
import hashlib
import io
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
SERVE = Path("/tmp/aegis-v6jump-test-serve")
PORT = 18082
HOST_URL = f"http://10.0.2.2:{PORT}"

OLD_UPDATER_HASH = "a17a47bb25504514557362e13e87aa802e9411f2e2af53cf3494e79796daea63"
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


def make_fake_image(prefix, data_bytes, tag, outdir=None, tamper=None):
    """Build a fake full image: random data -> xz -> 2 parts + sums.
    Returns (release dict, total part bytes, largest part bytes,
    SHA256SUMS text, .xz SHA256). When tamper is a part index, the
    SERVED bytes of that part are flipped but SHA256SUMS.txt keeps the
    good hashes, so the updater must refuse it on checksum mismatch.
    Fixtures for different tags share part filenames, so a tampered
    fixture is built into its own outdir and only copied into SERVE
    when its release is activated (see swap_release)."""
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
    # The updater downloads SHA256SUMS.txt by that exact name; serve one
    # copy per release under distinct names and copy the right one in
    # place when the fake API is swapped (see swap_release below).
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


# v6 fake: 3 MiB of incompressible data -> ~3 MiB .xz, so `check` must
# report "~3 MB download". v5 fake: 2 MiB -> "~2 MB".
v6_release, v6_total, v6_largest, v6_sums, v6_xz_hash = make_fake_image(
    "v6", os.urandom(3 * 1024 * 1024), "v6.0.0")
v5_release, v5_total, v5_largest, v5_sums, v5_xz_hash = make_fake_image(
    "v5", os.urandom(2 * 1024 * 1024), "v5.0.5")
# Tampered v6.0.1: part-01 served corrupted, sums keep the good hashes.
t_dir = SERVE / "tampered-v6.0.1"
t_release, t_total, t_largest, t_sums, t_xz_hash = make_fake_image(
    "v6", os.urandom(2 * 1024 * 1024), "v6.0.1", outdir=t_dir, tamper=1)
V6_MB = v6_total // (1024 * 1024)
V5_MB = v5_total // (1024 * 1024)
V6_PEAK_BOUND = v6_total + v6_largest + 1024 * 1024
print(f"[v6jump-test] fake v6 total {v6_total} bytes (~{V6_MB} MB); "
      f"fake v5 total {v5_total} bytes (~{V5_MB} MB); "
      f"v6 peak bound {V6_PEAK_BOUND} bytes", flush=True)

api_dir = SERVE / "repos" / "Die-Another-Day" / "AegisOS" / "releases"
api_dir.mkdir(parents=True)


def swap_release(release, sums, part_dir=None):
    if part_dir is not None:
        for p in Path(part_dir).glob("aegis-*.img.xz.part-*"):
            shutil.copyfile(p, SERVE / p.name)
    (api_dir / "latest").write_text(json.dumps(release))
    (SERVE / "SHA256SUMS.txt").write_text(sums)


swap_release(v6_release, v6_sums)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SERVE), **kw)

    def log_message(self, *a):
        pass


httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"[v6jump-test] serving fixtures at http://127.0.0.1:{PORT} (guest: {HOST_URL})", flush=True)

# --- Boot a copy ------------------------------------------------------------
TEST_IMG = IMG + ".test"
print(f"[v6jump-test] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
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
                print(f"\n[v6jump-test] MATCH {label}\n", flush=True)
                return True
        if q.poll() is not None:
            print(f"\n[v6jump-test] QEMU EXITED rc={q.returncode}\n", flush=True)
            return False
    print(f"\n[v6jump-test] TIMEOUT {label}: {pat}\n", flush=True)
    return False


def send(s):
    os.write(master, s.encode())
    time.sleep(1.0)


_drain_n = [0]


def drain(label, timeout=180):
    _drain_n[0] += 1
    m = f"VJDRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    pat = re.compile(m.encode() + rb"\r+\n.*?analyst@aegis", re.DOTALL)
    return wait_for(pat, timeout, f"drain {label}")


seg_start = [0]


def mark():
    seg_start[0] = len(buf)


def check(pat, label):
    global ok
    found = re.search(pat, buf[seg_start[0]:])
    print(f"[v6jump-test] {'PASS' if found else 'FAIL'} {label}: {pat}", flush=True)
    ok = ok and bool(found)
    return bool(found)


def check_absent(pat, label):
    global ok
    found = re.search(pat, buf[seg_start[0]:])
    print(f"[v6jump-test] {'PASS' if not found else 'FAIL'} {label} (absent): {pat}", flush=True)
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
    # 0. Precondition: v5.0.3 image ships the OLD updater.
    mark()
    send("echo MARK_VJ_PRE; cat /etc/aegis-version; sha256sum /usr/local/bin/aegis-update; echo PRE_DONE\n")
    ok &= drain("pre")
    check(rb"Installed version|5\.0\.3", "version file reads 5.0.3")
    check(re.escape(OLD_UPDATER_HASH).encode(), "image ships the OLD updater")
if ok:
    # 1. Bug reproduction with the OLD updater against fake v6.0.0.
    mark()
    send(f"echo MARK_VJ_BUG; AEGIS_API_BASE={HOST_URL} aegis-update check; echo BUG_CHECK_RC=$?; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo BUG_APPLY_RC=$?\n")
    ok &= drain("bug", timeout=240)
    check(rb"Latest release:\s+v6\.0\.0", "old updater sees v6.0.0")
    check(rb"full image only, ~400 MB download", "old check prints hardcoded ~400 MB")
    check(rb"no patch bundle and no complete image parts", "old apply dies with the reported error")
    check(rb"BUG_APPLY_RC=1", "old apply exit non-zero")
if ok:
    # 2. Bootstrap installs the fixed updater; version stays 5.0.3.
    mark()
    send(f"echo MARK_VJ_BS; curl -fsSL {HOST_URL}/aegis-v5/bootstrap-update.sh -o /tmp/bootstrap-update.sh && {SUDO} env AEGIS_RAW_BASE={HOST_URL} bash /tmp/bootstrap-update.sh; echo BS_RC=$?; cat /etc/aegis-version; sha256sum /usr/local/bin/aegis-update\n")
    ok &= drain("bootstrap", timeout=240)
    check(rb"BS_RC=0", "bootstrap exit 0")
    check(rb"5\.0\.3", "bootstrap leaves version at 5.0.3")
    check(re.escape(NEW_UPDATER_HASH).encode(), "fixed updater installed")
if ok:
    # 3. Fixed updater: check against fake v6.0.0 reports the real size.
    mark()
    send(f"echo MARK_VJ_CHECK6; AEGIS_API_BASE={HOST_URL} aegis-update check; echo CHECK6_RC=$?\n")
    ok &= drain("check6")
    check(rb"Latest release:\s+v6\.0\.0", "fixed check reports v6.0.0")
    check(f"Update available: v6\\.0\\.0 \\(full image only, ~{V6_MB} MB download\\)".encode(),
          f"fixed check reports real size ~{V6_MB} MB")
if ok:
    # 4. Fixed updater: apply streams the v6 image. A background du
    # sampler records peak disk use of the update dir during the run.
    send("echo MARK_VJ_DU_START; rm -f /tmp/du.log /tmp/du.pid; echo secure | sudo -S sh -c 'echo $$ > /tmp/du.pid; while true; do du -sb /var/lib/aegis/update 2>/dev/null | cut -f1 >> /tmp/du.log; sleep 0.05; done' >/dev/null 2>&1 & echo DU_STARTED\n")
    ok &= drain("du-start")
    mark()
    send(f"echo MARK_VJ_APPLY6; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo APPLY6_RC=$?; cat /etc/aegis-version\n")
    ok &= drain("apply6", timeout=240)
    check(rb"aegis-v6\.img\.xz\.part-00: OK", "v6 part-00 checksum OK")
    check(rb"aegis-v6\.img\.xz\.part-01: OK", "v6 part-01 checksum OK")
    check(rb"matches the release notes", "v6 assembled hash matches release notes")
    check(rb"STOP", "v6 apply prints STOP, does not install")
    check(rb"APPLY6_RC=0", "v6 apply exit 0")
    check(rb"5\.0\.3", "version file still 5.0.3 after v6 apply")
if ok:
    mark()
    send(f"echo MARK_VJ_DU_STOP; kill $(cat /tmp/du.pid) 2>/dev/null; sleep 0.5; wc -l /tmp/du.log; PEAK=$(sort -n /tmp/du.log 2>/dev/null | tail -1); [ -n \"$PEAK\" ] || PEAK=0; echo PEAK=$PEAK BOUND={V6_PEAK_BOUND}; [ \"$PEAK\" -le {V6_PEAK_BOUND} ] && echo PEAK_OK || echo PEAK_TOO_HIGH\n")
    ok &= drain("du-stop")
    check(rb"PEAK_OK", "peak disk during streaming apply under total + largest part + 1 MiB")
if ok:
    # The staged .xz must be byte-identical to the fixture and no part
    # files may be left behind (they are deleted as they are appended).
    mark()
    send(f"echo MARK_VJ_LS6; {SUDO} ls -l /var/lib/aegis/update/v6.0.0/; {SUDO} sha256sum /var/lib/aegis/update/v6.0.0/aegis-v6.img.xz\n")
    ok &= drain("ls6")
    check(rb"-rw-r--r--.*aegis-v6\.img\.xz", "joined file aegis-v6.img.xz listed in update dir")
    check(re.escape(v6_xz_hash).encode(), "staged .xz byte-identical (sha256 matches fixture)")
    check_absent(rb"part-", "no part files left in update dir after streaming apply")
if ok:
    # 4b. RESUME (valid): apply again with the staged image present.
    mark()
    send(f"echo MARK_VJ_RESUME; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo RESUME_RC=$?\n")
    ok &= drain("resume", timeout=240)
    check(rb"already staged", "resume prints already-staged")
    check(rb"STOP", "resume prints STOP")
    check(rb"RESUME_RC=0", "resume apply exit 0")
    check_absent(rb"downloading", "resume downloads nothing")
if ok:
    # 4c. RESUME (corrupt): corrupt the staged image in place; apply
    # must delete it and re-download (size is unchanged, so only the
    # release-notes hash check can catch this).
    mark()
    send(f"echo MARK_VJ_CORRUPT; {SUDO} dd if=/dev/zero of=/var/lib/aegis/update/v6.0.0/aegis-v6.img.xz bs=32 count=1 seek=3 conv=notrunc; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo CORRUPT_RC=$?\n")
    ok &= drain("corrupt", timeout=240)
    check(rb"incomplete or corrupt", "corrupt staged image detected")
    check(rb"downloading", "corrupt staged image triggers re-download")
    check(rb"aegis-v6\.img\.xz\.part-00: OK", "re-download part-00 checksum OK")
    check(rb"matches the release notes", "re-downloaded hash matches release notes")
    check(rb"STOP", "corrupt-resume prints STOP")
    check(rb"CORRUPT_RC=0", "corrupt-resume apply exit 0")
if ok:
    # 5. Regression: swap the fake API to a v5.0.5 release (v5 parts).
    swap_release(v5_release, v5_sums)
    print("[v6jump-test] host: fake API swapped to v5.0.5 release", flush=True)
    mark()
    send(f"echo MARK_VJ_CHECK5; AEGIS_API_BASE={HOST_URL} aegis-update check; echo CHECK5_RC=$?\n")
    ok &= drain("check5")
    check(rb"Latest release:\s+v5\.0\.5", "regression check reports v5.0.5")
    check(f"Update available: v5\\.0\\.5 \\(full image only, ~{V5_MB} MB download\\)".encode(),
          f"regression check reports real size ~{V5_MB} MB")
if ok:
    mark()
    send(f"echo MARK_VJ_APPLY5; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo APPLY5_RC=$?; cat /etc/aegis-version; {SUDO} ls -l /var/lib/aegis/update/v5.0.5/\n")
    ok &= drain("apply5", timeout=240)
    check(rb"aegis-v5\.img\.xz\.part-00: OK", "v5 part-00 checksum OK")
    check(rb"aegis-v5\.img\.xz\.part-01: OK", "v5 part-01 checksum OK")
    check(rb"matches the release notes", "v5 assembled hash matches release notes")
    check(rb"STOP", "v5 apply prints STOP, does not install")
    check(rb"APPLY5_RC=0", "v5 apply exit 0")
    check(rb"-rw-r--r--.*aegis-v5\.img\.xz", "joined file aegis-v5.img.xz listed in update dir")
if ok:
    # 6. TAMPERED PART: swap the fake API to a v6.0.1 release whose
    # part-01 bytes are flipped (sums keep the good hashes). apply
    # must die on the checksum mismatch and leave no partial .xz and
    # no part files behind.
    swap_release(t_release, t_sums, part_dir=t_dir)
    print("[v6jump-test] host: fake API swapped to tampered v6.0.1 release", flush=True)
    mark()
    send(f"echo MARK_VJ_TAMPER; {SUDO} env AEGIS_API_BASE={HOST_URL} aegis-update apply; echo TAMPER_RC=$?; {SUDO} ls -l /var/lib/aegis/update/v6.0.1/; test ! -e /var/lib/aegis/update/v6.0.1/aegis-v6.img.xz && echo NO_XZ_LEFT; ls /var/lib/aegis/update/v6.0.1/ | grep -q part- && echo PARTS_LEFT || echo NO_PARTS_LEFT\n")
    ok &= drain("tamper", timeout=240)
    check(rb"checksum mismatch for aegis-v6\.img\.xz\.part-01", "tampered part refused on checksum mismatch")
    check(rb"TAMPER_RC=1", "tampered apply exit non-zero")
    check(rb"NO_XZ_LEFT", "tampered apply leaves no partial final file")
    check(rb"NO_PARTS_LEFT", "tampered apply leaves no part files")
if ok:
    send("echo MARK_VJ_DONE; echo secure | sudo -S poweroff\n")
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
print(f"[v6jump-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close()
sys.exit(0 if ok else 1)
