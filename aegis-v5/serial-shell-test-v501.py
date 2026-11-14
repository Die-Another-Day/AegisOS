#!/usr/bin/env python3
"""Serial-console shell test for AegisOS v5.0.1.

Boots a COPY of the image in QEMU with no graphical display attached
(-display none, serial stdio) and runs aegis-shell in all three modes
from the serial console, where no Wayland display exists.

Expected on a FIXED image: every mode exits quickly with the clear
one-line "no graphical display" message, exit code 4, and NO traceback.
Expected on the BROKEN v5.0.0 image: TypeError traceback from apply_css
(Gdk.Screen.get_default() is None).

Also probes, in the same boot, whether an explicit Gtk.init_check()
can open a screen when no display exists, and records the display
environment (WAYLAND_DISPLAY, SWAYSOCK, GDK_BACKEND, DISPLAY).

Usage: serial-shell-test-v501.py <image> <logfile>
"""
import os, pty, re, select, shutil, subprocess, sys, time
from pathlib import Path

IMG, LOG = sys.argv[1], sys.argv[2]
TEST_IMG = IMG + ".test"
print(f"[serial-test] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
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
                print(f"\n[serial-test] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[serial-test] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[serial-test] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

_drain_n = [0]
def drain(label, timeout=120):
    _drain_n[0] += 1
    m = f"SERIALDRAIN{_drain_n[0]}_{label}"
    send(f"echo {m}\n")
    return wait_for(m.encode(), timeout, f"drain {label}")

ok = True
ok &= wait_for(rb"aegis login:", 600, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
    # Display environment on the serial console (expect all unset).
    send("echo MARK_SERIAL_ENV; echo WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset} SWAYSOCK=${SWAYSOCK:-unset} GDK_BACKEND=${GDK_BACKEND:-unset} DISPLAY=${DISPLAY:-unset} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-unset}; tty\n")
    ok &= drain("env")
if ok:
    # GTK probe: can an explicit init open a screen with no display?
    send("echo MARK_SERIAL_GTKPROBE; timeout 20 python3 -c \"import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk, Gdk; print('SCREEN_BEFORE:', Gdk.Screen.get_default()); print('INIT_CHECK:', Gtk.init_check()); print('SCREEN_AFTER:', Gdk.Screen.get_default())\"; echo GTKPROBE_RC=$?\n")
    ok &= drain("gtkprobe")
if ok:
    # All three shell modes from the serial console. Each must print the
    # clear message and exit (rc 4 on fixed image); a traceback = fail.
    for mode in ("--desktop", "--lock", "--launcher"):
        send(f"echo MARK_SERIAL_{mode[2:].upper()}; timeout 30 aegis-shell {mode}; echo SHELL_RC_{mode[2:].upper()}=$?\n")
        ok &= drain(f"mode-{mode[2:]}")
if ok:
    send("echo MARK_SERIAL_DONE; echo secure | sudo -S poweroff\n")
    drain("done")
try: q.terminate()
except Exception: pass
try: q.wait(timeout=25)
except Exception: q.kill()
print(f"[serial-test] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
