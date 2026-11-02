# Saral in SecureOS — v0.3.0 (prepared, NOT pushed, NOT live yet)

Saral is the simplest automation language (`.srl` files, `saral`
command, Python 3 stdlib only). In SecureOS it is installed by
default: `secureos-v4/setup-v4.sh` copies this folder's interpreter
to `/usr/local/bin/saral` and its libraries to
`/usr/local/lib/saral/libs/`, and `secureos-v4/build-image.sh`
copies this folder into the image at those same paths. After that,
any user on SecureOS can run `saral script.srl` with no install step.

## What is copied here — and what is left out, and why

Copied here (everything needed to RUN Saral in the OS):
- `saral.py` — the interpreter (lexer, parser, executor, loader).
  This copy differs from `~/workspace/saral-lang/saral.py` in exactly
  one way: its library search (`_resolve_lib_dir`) also looks in
  `/usr/local/lib/saral/libs` and `~/.local/lib/saral/libs`, so the
  split install layout (`/usr/local/bin/saral` + libraries in
  `/usr/local/lib/saral/`) works. Version string is unchanged:
  `saral version` prints `Saral 0.3.0`.
- `libs/` — all v0.3 libraries: `data.py`, `file.py`, `log_rules.py`,
  `logs.py`, `net.py`, `report.py`, `system.py`, plus the
  `greet_bridge/` Node bridge folder (`greet.js` + `lib.json`).
  The Node bridge only works if Node.js is installed in the OS
  image; core libraries need only Python 3.

Left out (deliberately, to keep the OS repo lean):
- `examples/` — runnable `.srl` scripts and sample logs/fixtures.
- `tests/` — the unittest suite (47 tests in v0.3).
- `README.md`, `SPEC.md`, `PROOF.md` — full language docs and proof.
- `install.sh`, `INSTALL.md` — the standalone installer.

All of the left-out material lives in the standalone Saral repo
(prepared as `Die-Another-Day/Saral`, not pushed yet). Get the full
docs, examples, and tests from there once it is published; this
folder is the runtime only.

## How to use it, once installed by default

```bash
saral version
saral list
saral script.srl
```

Example (from the Saral repo's examples, not shipped here):

```saral
took net
took log.rules
hosts is scan net "127.0.0.1" ports : "22,80"
show hosts
```

## Safety — same rules as Saral itself

- `net` verbs accept localhost + RFC1918 private IPs only; public
  IPs are refused, never scanned.
- No VAPT verbs, no login/CAPTCHA/human-verification automation,
  no credentials anywhere. If a site shows a human check, stop and
  hand it to the human.
- Saral in SecureOS is NOT proven by a QEMU boot yet. The install
  steps were simulated in a temp prefix (see the preparation notes
  held by the agent); a real image build + boot that shows
  `saral version` inside the guest remains unproven until it is
  actually built and booted.

## Status

Prepared locally only. Nothing in this folder has been pushed to
GitHub, and Saral is NOT installed by default in any live SecureOS
image until: (1) these changes are pushed to
`Die-Another-Day/SecureOS` main, (2) a new v4 image is built from
that head, and (3) `saral version` is verified inside a booted guest.
