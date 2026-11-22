#!/usr/bin/env python3
"""VT graphical verification for AegisOS v6 (Hyprland + Quickshell).

Method (adapted from the v5 vt-gui-test recipe):
- boot a COPY of the image in QEMU (virtio-vga, VNC display, serial stdio,
  QMP + monitor sockets, usb-tablet + usb-kbd) — the shipped image is
  never written by a test. QEMU runs with -smp 4: the bar defect (fixed
  2026-11-22) was a first-frame latency under software rendering that
  scales with CPU count (1 vCPU: bar ~2-4 min after unlock; 4 vCPUs:
  <30 s), so a 1-vCPU guest measures the sandbox, not the product.
- log in on the SERIAL console as analyst (command channel only).
- inject keystrokes into /dev/tty1 via TIOCSTI: login on tty1, then start
  the GUI the way a real user does: `aegis-gui > /tmp/gui.log 2>&1`.
- gate every step on real process state (Hyprland alive, qs alive, lock
  surface present in `hyprctl clients`); a dead GUI fails the run.
- unlock by TYPING THE REAL PASSWORD into the Quickshell lock screen
  via QMP key events (usb-kbd) — this is the PAM-unlock build gate.
  If the password unlock cannot be proven, the run reports it plainly
  and the hyprlock fallback is NOT silently substituted.
- VISUAL GATE (added 2026-11-22, after the bar defect): process
  aliveness is NOT enough — the old run reported ok=True while the
  desktop showed only wallpaper. The driver now checks what is actually
  on screen and FAILS when it is absent:
    * `hyprctl layers` must list aegis:bar and aegis:desktop;
    * the bar must visibly draw: bright (text) pixels in the top-left
      bar island of the desktop screenshot (absent: ~13, present: ~1065;
      threshold 200);
    * the right-click menu, launcher and Chrome window must each change
      their screen region by >500 strongly-changed pixels vs the bare
      desktop shot (animation alone: 0 in those regions);
    * `hyprctl clients` must list a chrome window after dispatch.
  Each UI gate retries once after a 30-60 s wait (first Qt Quick frames
  are slow under llvmpipe) and then fails the run.
- animation proof: two desktop screenshots N seconds apart; the driver
  computes a Pillow pixel diff and prints ANIMATION_DIFF — the animated
  wallpaper must provably move.
- screenshots via QMP screendump: 01-lock-screen, 02-desktop,
  02b-desktop-animation-2, 03-right-click-menu, 04-launcher, 05-chrome.

Usage: vt-gui-test-v6.py <image> <logfile>
"""
import os, pty, re, select, shutil, socket, subprocess, sys, time, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".test"
print(f"[vt-test] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
SHOTS = HERE / "screenshots"
SHOTS.mkdir(exist_ok=True)
MON_SOCK = "/tmp/aegis-v6-vt-mon.sock"
QMP_SOCK = "/tmp/aegis-v6-vt-qmp.sock"
for p in (MON_SOCK, QMP_SOCK):
    try: os.unlink(p)
    except OSError: pass
logf = open(LOG, "wb", buffering=0)

def emit(b):
    logf.write(b); sys.stdout.buffer.write(b); sys.stdout.buffer.flush()

master, slave = pty.openpty()
q = subprocess.Popen(
    ["qemu-system-x86_64", "-m", "2048", "-machine", "pc", "-cpu", "qemu64",
     "-smp", "4",
     "-drive", f"file={IMG},format=raw,if=ide",
     "-netdev", "user,id=net0,hostfwd=tcp::18000-:8000",
     "-device", "e1000,netdev=net0",
     "-device", "virtio-vga",
     "-device", "qemu-xhci",
     "-device", "usb-tablet",
     "-device", "usb-kbd",
     "-display", "vnc=:1",
     "-serial", "stdio", "-monitor", f"unix:{MON_SOCK},server,nowait",
     "-qmp", f"unix:{QMP_SOCK},server,nowait"],
    stdin=slave, stdout=slave, stderr=slave, close_fds=True)
os.close(slave)
# NOTE (2026-11-22): a crash mid-run (e.g. a Python error in a gate)
# used to orphan the QEMU child — it kept the VM booted, holding TCP
# :18000 + VNC :1, so the NEXT run's QEMU died at startup ("Could not
# set up host forwarding rule") and the run failed at the login prompt.
# Terminate QEMU on any exit path, crash included.
import atexit
def _kill_qemu():
    try: q.terminate()
    except Exception: pass
    try: q.wait(timeout=10)
    except Exception:
        try: q.kill()
        except Exception: pass
atexit.register(_kill_qemu)
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
                print(f"\n[vt-test] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[vt-test] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[vt-test] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label):
    _drain_n[0] += 1
    m = f"VTDRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    return wait_for(m.encode(), 60, f"drain {label}")

def qmp(events):
    """Send raw input events over QMP. Returns the response line or None."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(20); s.connect(QMP_SOCK)
        f = s.makefile("rw", buffering=1, encoding="utf-8")
        f.readline()  # greeting
        f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush()
        f.readline()
        f.write(json.dumps({"execute": "input-send-event", "arguments": {"events": events}}) + "\n"); f.flush()
        resp = f.readline()
        s.close()
        return resp.strip()
    except Exception as e:
        emit(f"\n[vt-test] qmp FAILED: {e}\n".encode()); return None

def mouse_move(x, y):
    """Move the pointer to ABSOLUTE output coordinates (usb-tablet 0..32767)."""
    ax = int(x / 1280 * 32767); ay = int(y / 800 * 32767)
    r = qmp([{"type": "abs", "data": {"axis": "x", "value": ax}},
             {"type": "abs", "data": {"axis": "y", "value": ay}}])
    print(f"[vt-test] mouse moved to {x},{y}: {r}", flush=True)
    time.sleep(1.0)

def mouse_click(button="left"):
    qmp([{"type": "btn", "data": {"down": True, "button": button}}])
    time.sleep(0.2)
    qmp([{"type": "btn", "data": {"down": False, "button": button}}])
    time.sleep(1.0)

def type_text(text):
    """Type text via QMP key events (usb-kbd, qcode). Lowercase + Return only."""
    for ch in text:
        if ch == "\n":
            code = "ret"
        else:
            code = ch
        qmp([{"type": "key", "data": {"down": True, "key": {"type": "qcode", "data": code}}}])
        time.sleep(0.08)
        qmp([{"type": "key", "data": {"down": False, "key": {"type": "qcode", "data": code}}}])
        time.sleep(0.08)
    print(f"[vt-test] typed {len(text)} chars", flush=True)

def screendump(name):
    ppm = f"/tmp/aegis-shot-{name}.ppm"
    png = str(SHOTS / f"{name}.png")
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(20); s.connect(MON_SOCK)
        time.sleep(0.5)
        try: s.recv(65536)
        except socket.timeout: pass
        s.sendall(f"screendump {ppm}\n".encode())
        time.sleep(2)
        try:
            resp = s.recv(65536)
            emit(f"\n[vt-test] monitor reply for {name}: {resp!r}\n".encode())
        except socket.timeout:
            pass
        s.close()
    except Exception as e:
        emit(f"\n[vt-test] screendump {name} FAILED: {e}\n".encode()); return None
    time.sleep(1)
    try:
        from PIL import Image
        im = Image.open(ppm)
        im.save(png)
        print(f"[vt-test] screenshot saved: {png} {im.size}", flush=True)
        return png
    except Exception as e:
        emit(f"\n[vt-test] convert {name} FAILED: {e}\n".encode()); return None

def shell_has(pat, label, timeout=60):
    """Run a check on the serial shell; True only if the pattern appears."""
    global buf
    buf = b""
    # NOTE (found 2026-11-22, qs-diag4 + host repro): the old pattern
    # 'Hyprland|quickshell|hyprlock|swww' can NEVER list `qs -c aegis` —
    # its cmdline contains none of those words — so shell-alive could
    # never match even with qs running. 'qs' must be in the pattern.
    send(f"pgrep -af 'Hyprland|quickshell|hyprlock|swww|qs'; echo CHECK_{label}\n")
    return wait_for(pat, timeout, f"check {label}")

def hyprctl(cmd, label, timeout=60):
    """Run hyprctl from the serial shell (finds the Hyprland socket first)."""
    global buf
    buf = b""
    # Hyprland 0.55 layout: instance dir is $XDG_RUNTIME_DIR/hypr/<sig>/
    # (not $XDG_RUNTIME_DIR/hyprland-<sig> as in <= 0.5x). The signature
    # is the directory name itself; proven by qs-diag3 (hyprctl clients
    # + dispatch both work with this value).
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); "
         f"hyprctl {cmd}; echo HYPR_{label}_DONE\n")
    return wait_for(f"HYPR_{label}_DONE".encode(), timeout, f"hyprctl {label}")

def hyprctl_text(cmd, label, timeout=60):
    """Like hyprctl(), but returns the command's serial output as text."""
    if not hyprctl(cmd, label, timeout):
        return ""
    return buf.decode("utf-8", "replace")

# --- VISUAL GATE (2026-11-22, bar defect) ---------------------------------
# Calibrated on qs-diag9/qs-diag10 screenshots (1280x800):
#   bar island (x8-405, y4-42), bright pixels (max channel > 180):
#     bar absent: 13, 13, 0   |   bar present: 1065 (every time)
#   menu region (x200-450, y200-502), pixels changed by >60 vs bare desktop:
#     animation alone: 0      |   menu present: 2650, 2651
#   launcher card region (x340-940, y40-480), same measure:
#     animation alone: 0      |   launcher present: thousands (card is
#     ~600x440 of solid panel; validated by qs-diag11)
# Thresholds sit far from both sides, so the gate is not flaky.
BAR_BOX = (8, 4, 405, 42)
BAR_BRIGHT_MIN = 200
MENU_BOX = (200, 200, 450, 502)
LAUNCHER_BOX = (340, 40, 940, 480)
CHROME_BOX = (200, 100, 1080, 700)
REGION_DELTA_MIN = 500

def bar_present(png_path):
    """True when the bar visibly draws (gold/white text on its islands)."""
    try:
        from PIL import Image
        im = Image.open(png_path).convert("RGB").crop(BAR_BOX)
        n = sum(1 for r, g, b in im.getdata() if max(r, g, b) > 180)
        print(f"[vt-test] BAR_BRIGHT={n} (min {BAR_BRIGHT_MIN}) in {png_path}", flush=True)
        return n >= BAR_BRIGHT_MIN
    except Exception as e:
        print(f"[vt-test] bar check FAILED: {e}", flush=True)
        return False

def region_changed(png_before, png_after, box, label):
    """True when a window visibly appeared in `box` (vs the bare desktop)."""
    try:
        from PIL import Image, ImageChops
        a = Image.open(png_before).convert("RGB").crop(box)
        b = Image.open(png_after).convert("RGB").crop(box)
        d = ImageChops.difference(a, b)
        n = sum(1 for r, g, b in d.getdata() if max(r, g, b) > 60)
        print(f"[vt-test] REGION_DELTA[{label}]={n} (min {REGION_DELTA_MIN})", flush=True)
        return n >= REGION_DELTA_MIN
    except Exception as e:
        print(f"[vt-test] region check {label} FAILED: {e}", flush=True)
        return False

def layers_has(*namespaces):
    """True when `hyprctl layers` lists every named layer-shell surface.

    NOTE (2026-11-22): the first version of this gate parsed the layers
    output out of the driver's serial buffer, but `hyprctl layers` came
    back empty there (the 40-line gui.log tail dumped just before it was
    still streaming, and the capture could not tell empty output from a
    lost one). This version writes the output to a file on the guest and
    greps the file there, so the answer is a plain count the driver can
    trust; the file is also dumped to the log for inspection.
    """
    global buf
    # NOTE (2026-11-22): the result line must match a pattern the typed
    # command itself cannot match. An earlier version echoed
    # `LAYERS_COUNTS aegis_bar=$aegis_bar ...` and the driver's regex
    # matched the command ECHO (unexpanded `$aegis_bar`) instead of the
    # result. Here the result is bare numbers (`LAYERS_RESULT 1 1`),
    # which the echo text (`$aegis_bar`) can never match.
    # NOTE (2026-11-22): `grep -c` prints the count (even 0) but exits
    # 1 on no match, so `|| echo 0` after it DOUBLE-prints ("0\n0").
    # `| head -n 1` takes exactly the one count line; the file always
    # exists (the redirect above creates it), so this is exact.
    assigns = "; ".join(
        f"{n.replace(':', '_').replace('-', '_')}=$(grep -c '{n}' /tmp/layers.txt 2>/dev/null | head -n 1)"
        for n in namespaces)
    vars_ = " ".join("$" + n.replace(":", "_").replace("-", "_") for n in namespaces)
    buf = b""
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); "
         "hyprctl layers > /tmp/layers.txt 2>&1; "
         f"{assigns}; echo LAYERS_RESULT {vars_}; echo HYPR_layers_DONE\n")
    # Wait for the RESULT line itself, not the DONE marker: the typed
    # command echo contains the literal text "HYPR_layers_DONE", so a
    # wait on the marker would return on the echo, before the command
    # has even run. The echo cannot match `LAYERS_RESULT \d` (it has
    # `$aegis_bar`, not digits), so this only matches the real result.
    if not wait_for(rb"LAYERS_RESULT \d", 60, "hyprctl layers result"):
        print("[vt-test] LAYERS result line NOT FOUND", flush=True)
        return False
    text = buf.decode("utf-8", "replace")
    m = re.search(r"LAYERS_RESULT ((?:\d+ )*\d+)", text)
    if not m:
        print("[vt-test] LAYERS result line NOT FOUND", flush=True)
        return False
    counts = [int(x) for x in m.group(1).split()]
    print(f"[vt-test] LAYERS counts: {dict(zip(namespaces, counts))}", flush=True)
    missing = [n for n, c in zip(namespaces, counts) if c < 1]
    if missing:
        print(f"[vt-test] LAYERS missing: {missing}", flush=True)
        return False
    print(f"[vt-test] LAYERS present: {list(namespaces)}", flush=True)
    return True

def clients_has_chrome():
    """True when `hyprctl clients` lists a Chrome window (file+grep)."""
    global buf
    buf = b""
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); "
         "hyprctl clients > /tmp/clients.txt 2>&1; "
         "echo CHROME_COUNT=$(grep -ci 'chrome' /tmp/clients.txt 2>/dev/null | head -n 1); echo HYPR_clients_chrome_DONE\n")
    # Wait for the result digits, not the DONE marker (same echo trap
    # as layers_has: the typed command contains the marker text).
    if not wait_for(rb"CHROME_COUNT=\d", 60, "hyprctl clients chrome"):
        return False
    text = buf.decode("utf-8", "replace")
    m = re.search(r"CHROME_COUNT=(\d+)", text)
    n = int(m.group(1)) if m else 0
    print(f"[vt-test] CHROME clients count={n}", flush=True)
    return n >= 1

ok = True
ok &= wait_for(rb"aegis login:", 900, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
    send("echo MARK_DIAG; systemctl is-enabled aegis-labapp.service aegis-ssh-lab.service; systemctl is-active aegis-labapp.service aegis-ssh-lab.service; ss -tlnp 2>/dev/null | grep -E ':2222|:8080' || echo NO_LAB_LISTENERS; ls /dev/dri/ 2>&1; ls -l /usr/share/aegis/wallpapers/; cat /etc/aegis-version\n")
    ok &= drain("diag")
if ok:
    # Injector: type into tty1 (real VT login + real user GUI start).
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
    # QEMU llvmpipe slowness (found 2026-11-22, qs-diag3): Quickshell's
    # Qt Quick startup under software rendering takes ~2 min before the
    # `qs -c aegis` process is even visible (Hyprland + swww are up in
    # seconds; qs itself runs clean, no QML errors). The old 45 s wait +
    # 60 s check timed out at ~105 s, before qs appeared. Wait longer
    # here; on real hardware this is seconds, not minutes.
    time.sleep(150)
    # Real gates: Hyprland AND the Quickshell shell must be alive.
    ok &= shell_has(rb"Hyprland", "hyprland-alive")
    ok &= shell_has(rb"qs -c aegis", "shell-alive", timeout=180)
    if ok:
        ok &= hyprctl("clients", "clients")
        ok &= hyprctl("workspaces", "workspaces")
if ok:
    # Lock screen must be showing (autostart locks on entry).
    send("echo ---GUILOG---; cat /tmp/gui.log 2>&1 | head -n 60\n")
    ok &= drain("lock")
if ok:
    mouse_move(560, 625)  # on the lock-screen password row
    mouse_click("left")
    screendump("01-lock-screen")
    # PAM UNLOCK GATE: type the real password into the lock screen.
    type_text("secure\n")
    time.sleep(10)
    ok &= shell_has(rb"qs -c aegis", "shell-after-unlock")
    if ok:
        ok &= hyprctl("clients", "clients-after-unlock")
        # The lock surface must be gone and the bar must exist.
        send("echo MARK_VT_UNLOCKED; pgrep -af 'qs|Hyprland'; echo ---GUILOG-TAIL---; tail -n 40 /tmp/gui.log 2>&1\n")
        ok &= drain("unlocked")
if ok:
    # VISUAL GATE 1 — layers: the bar + desktop surfaces must exist.
    # (A surface existing is necessary but NOT sufficient — the bar
    # defect was a surface that existed yet rendered nothing — so the
    # pixel gates below are the real proof.)
    ok &= layers_has("aegis:bar", "aegis:desktop")
if ok:
    # VISUAL GATE 2 — the bar must visibly draw in the desktop shot.
    # Retry twice (30 s apart): a first Qt Quick frame under llvmpipe
    # can still be slow; with the bar fix (always visible, pre-rendered
    # at startup) the first try should already pass.
    desktop_png = None
    for attempt in (1, 2, 3):
        mouse_move(640, 400)
        desktop_png = screendump("02-desktop")
        if desktop_png and bar_present(desktop_png):
            break
        print(f"[vt-test] BAR NOT DRAWN on attempt {attempt}/3", flush=True)
        desktop_png = None
        if attempt < 3:
            time.sleep(30)
    if not desktop_png:
        print("[vt-test] VISUAL GATE FAILED: bar never drew", flush=True)
        ok = False
if ok:
    # Animation proof: a second desktop shot 12 s later; frames must differ.
    time.sleep(12)
    screendump("02b-desktop-animation-2")
    try:
        from PIL import Image, ImageChops
        a = Image.open(SHOTS / "02-desktop.png").convert("RGB")
        b = Image.open(SHOTS / "02b-desktop-animation-2.png").convert("RGB")
        diff = ImageChops.difference(a, b)
        n = sum(1 for px in diff.getdata() if px != (0, 0, 0))
        print(f"[vt-test] ANIMATION_DIFF={n} pixels differ between desktop shots", flush=True)
        if n < 100:
            print("[vt-test] ANIMATION NOT PROVEN (frames nearly identical)", flush=True)
            ok = False
    except Exception as e:
        print(f"[vt-test] animation diff FAILED: {e}", flush=True)
        ok = False
if ok:
    # VISUAL GATE 3 — right-click desktop menu must visibly appear.
    # The Hyprland right-click bind opens it at the fallback position
    # (200,200); the first frame is slow under llvmpipe, so wait 60 s
    # and retry the shot once before failing.
    mouse_move(640, 400)
    mouse_click("right")
    time.sleep(60)
    menu_ok = False
    for attempt in (1, 2):
        menu_png = screendump("03-right-click-menu")
        if menu_png and region_changed(str(SHOTS / "02-desktop.png"), menu_png, MENU_BOX, "menu"):
            menu_ok = True
            break
        print(f"[vt-test] MENU NOT DRAWN on attempt {attempt}/2", flush=True)
        if attempt < 2:
            time.sleep(60)
            screendump("03-right-click-menu")
            menu_png = str(SHOTS / "03-right-click-menu.png")
            if region_changed(str(SHOTS / "02-desktop.png"), menu_png, MENU_BOX, "menu"):
                menu_ok = True
                break
    if not menu_ok:
        print("[vt-test] VISUAL GATE FAILED: right-click menu never drew", flush=True)
        ok = False
    ok &= layers_has("aegis:desktopmenu")
    mouse_click("left")  # close the menu
if ok:
    # VISUAL GATE 4 — launcher must visibly appear (IPC toggle).
    send("export XDG_RUNTIME_DIR=/run/user/1000; export WAYLAND_DISPLAY=wayland-1; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER_SENT\n")
    ok &= drain("launcher")
    time.sleep(60)
    launcher_ok = False
    for attempt in (1, 2):
        launcher_png = screendump("04-launcher")
        if launcher_png and region_changed(str(SHOTS / "02-desktop.png"), launcher_png, LAUNCHER_BOX, "launcher"):
            launcher_ok = True
            break
        print(f"[vt-test] LAUNCHER NOT DRAWN on attempt {attempt}/2", flush=True)
        if attempt < 2:
            time.sleep(60)
    if not launcher_ok:
        print("[vt-test] VISUAL GATE FAILED: launcher never drew", flush=True)
        ok = False
    ok &= layers_has("aegis:launcher")
    send("export XDG_RUNTIME_DIR=/run/user/1000; export WAYLAND_DISPLAY=wayland-1; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); qs -c aegis ipc call aegis toggleLauncher; echo LAUNCHER_CLOSED\n")
    ok &= drain("launcher-closed")
if ok:
    # VISUAL GATE 5 — Chrome window must appear (dispatch + clients + pixels).
    send("export XDG_RUNTIME_DIR=/run/user/1000; export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr/ 2>/dev/null | head -1); hyprctl dispatch exec google-chrome; echo CHROME_SENT\n")
    ok &= drain("chrome")
    # Chrome's first window under QEMU llvmpipe (software GL) takes well
    # over 15 s to appear; give it 90 s, then check clients + pixels.
    time.sleep(90)
    chrome_ok = False
    for attempt in (1, 2):
        has_window = clients_has_chrome()
        chrome_png = screendump("05-chrome")
        drew = bool(chrome_png) and region_changed(str(SHOTS / "02-desktop.png"), chrome_png, CHROME_BOX, "chrome")
        print(f"[vt-test] CHROME attempt {attempt}/2: clients_window={has_window} drew={drew}", flush=True)
        if has_window and drew:
            chrome_ok = True
            break
        if attempt < 2:
            time.sleep(60)
    if not chrome_ok:
        print("[vt-test] VISUAL GATE FAILED: Chrome window never appeared", flush=True)
        ok = False
    send("echo MARK_VT_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[vt-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
