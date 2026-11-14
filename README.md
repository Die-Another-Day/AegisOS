# AegisOS v5 — Nebula-style desktop (Sway, not Hyprland) + Red vs Blue lab

> **v5 (new, 2026-11-14): AegisOS is the renamed SecureOS** (repo renamed
> SecureOS → AegisOS; old URL redirects), with a new desktop in the style
> of the Nebula reel: starfield lock screen with a big clock in a scalloped
> disc and orbiting widgets, a floating-island top bar, scattered scalloped
> widgets, and colours derived from the wallpaper. It is **sway 1.7 + an
> original GTK3/Python shell — NOT real Hyprland/Quickshell**: current
> Hyprland needs C++26 (gcc ≥ 16) and Quickshell needs Qt ≥ 6.6, and
> Debian 12 bookworm ships gcc 12.2 / Qt 6.4.2, so neither can run here.
> There is no live blur (panels use pre-blurred wallpaper slices) and no
> live-animated lock screen in the swaylock path. Real Hyprland +
> Quickshell would need a Debian 13 rebase — a v6 decision, not v5.
> The v4 Red vs Blue lab is carried over, renamed (`aegis-lab`,
> `aegis-ir`, `aegis-fim`); lab mode is OFF by default and the lab units
> cannot start at boot (they have no `[Install]` section — see
> `aegis-v5/README-v5.md`). Saral 0.3.0 is installed in the image
> for the first time.
> Full details: [`aegis-v5/README-v5.md`](aegis-v5/README-v5.md).
> Try it: `./aegis-v5/run-qemu.sh`, then `aegis-gui` inside for the
> desktop, or `aegis-lab --enable` inside for the lab. The multi-GB image
> itself is NOT in this repo.
> LAB ONLY, private LAN only, with consent of everyone on that LAN —
> never the public internet.

---

*(The v4 banner below is kept for history; v4 is superseded by v5.)*

# SecureOS — v4 is a real Red vs Blue lab, v3 added GUI on demand

> **v4 (new, 2026-10-30): SecureOS is now a real, networked Red vs Blue classroom lab — NOT a simulation.** Install it on one device, and students on the same private LAN attack it and defend it for real: real SQL injection, real SSH and plugin-upload flags, real journal/log/FIM alerts, and real IR — contain, eradicate, recover, reset. Lab mode is OFF by default; `secureos-lab --enable` opens it to a private LAN address only, and `secureos-lab --stop` kills it all.
> Full details: [`secureos-v4/README-v4.md`](secureos-v4/README-v4.md).
> Try it: `./secureos-v4/run-qemu.sh`, then `secureos-lab --enable` inside. The multi-GB image itself is NOT in this repo.
> LAB ONLY, private LAN only, with consent of everyone on that LAN — never the public internet.

# Earlier versions removed — v2 and v3 were removed from this repo on 2026-10-31, superseded by v4. They remain in git history only. v4 includes the GUI-on-demand and OS basics from v3 and the real bootable OS from v2.

# SecureOS v1.0 — a web-based analyst OS

**SecureOS is LoveOS, transformed in place.** The original project was a web
desktop ("Love OS — For Her"). v1.0 keeps the same idea — a full operating
system that runs in a browser, no download — and rebuilds it around
cybersecurity.

## Run it (frontend only, no backend needed)

```bash
# from this repo root
python3 -m http.server 8000
# open http://localhost:8000
```

Demo login: any operator name + passphrase `secure`.
That login is a demo gate only — it is **not real authentication**, and it
protects nothing on a server, because there is no server data. Everything
below runs in your browser.

## What is inside

| App | What it actually does |
|---|---|
| 🛡️ SOC Command Center | **Simulated** incident triage: brute-force, phishing, SQLi probe, lateral movement. Score yourself on contain / escalate / false-positive calls. |
| 🔑 Password Lab | Entropy estimate, common-password check, passphrase generator. Local only. |
| #️⃣ Hash Lab | SHA-256/384/512 via WebCrypto, hash identification and comparison. |
| 🎣 Phishing Analyzer | Parses a URL locally and scores heuristic red flags. **It never opens or fetches the link.** |
| 📜 Log Analyzer | Counts brute-force, SQLi, traversal and XSS patterns in pasted logs. |
| 🔒 Vault Notes | AES-GCM notes, PBKDF2-derived key, stored only in this browser. Demo-grade — a forgotten passphrase cannot be recovered. |
| 🌐 Network Lab | **Simulated** port scan for teaching. Sends no packets, touches no network. |
| 🧠 Threat Intel Cards | Curated technique cards, including the compounding-vulnerability idea behind UASAF. |
| 💻 Secure Terminal | Local virtual filesystem only (`help, ls, cat, echo, mkdir, tools, threat`). |

The "overpowered" piece is the SOC Center + Log Analyzer + Threat Intel
together: triage an incident, see *why* a pattern matters, and see how
small flaws chain into a critical path — instead of a single tool in
isolation.

## Security model — read this before you show it to anyone

- **Local-first:** no app sends your passwords, hashes, URLs, logs or notes
  anywhere. Check the code in `apps/secure-apps.js` — there is no fetch to
  a third party in any app.
- **Lab use only:** never scan, probe or test a system you do not own or
  do not have explicit permission to test. The Network Lab is simulated
  precisely so the demo cannot be misused that way.
- **Demo login is not security:** anyone with the page can enter. Do not
  put real production secrets in Vault Notes.
- **Reference tools in v1 vs v2:** in the v1 web demo, Nmap, Wireshark,
  Suricata/Zeek and Wazuh were reference tools only — the demo did not
  install or run them. In the bootable OS (v4) they are real, inside the OS
  (see `secureos-v4/README-v4.md`).

## Backend hardening (v1.0 history, now cleaned up)

The original LoveOS backend could clone **any** GitHub URL,
`npm install` it, and run it with `spawn(..., { shell: true })`. That is
remote code execution if the server is ever exposed, so v1.0 hardened it
to a catalogue-only server, and the v1 cleanup then removed the whole
Node backend (`backend/`) from this repo. SecureOS v2 does not use it at
all: its backend is `secureos-v4/server.py` (Python stdlib only, localhost
only, allowlisted tools only — no clone, install, or arbitrary run).
No exploitation tool is a SecureOS app, in v1 or v2.

## What v1.0 deliberately does NOT do

- No real network scanning, packet capture, or exploitation — those need
  a real lab, real permission, and real tools, not a browser demo.
- No user accounts, no cloud sync, no analytics.
- Cleanup (29 Oct 2026): the legacy `loveos/` folder and the v1 Node
  backend (`backend/`) were removed from main — 29 files in total.
  They remain in git history only. The live desktop loads from
  `secureos/`; the real OS is in `secureos-v4/`.

## Origin

LoveOS was first shared on LinkedIn on 11 Aug 2025 ("Building LoveOS: A
Web-Based OS from Scratch"). SecureOS v1.0, 29 Oct 2026, is its
cybersecurity transformation, built in place in this same repository.
