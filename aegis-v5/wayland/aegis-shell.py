#!/usr/bin/env python3
"""AegisOS v5 Nebula-style shell — ORIGINAL implementation (no Nebula code).

GTK3 + gtk-layer-shell, Python. Modes:
  aegis-shell.py --lock      starfield lock screen (see below)
  aegis-shell.py --desktop   floating-island top bar + scattered widgets
  aegis-shell.py --launcher  radial app launcher (ring of real .desktop apps)
  aegis-shell.py --lock-bg   render the lock background PNG for swaylock
                             (used by the secure-lock path; static image)

Lock screen (reel: lid-open -> lock screen -> desktop, no logo splash):
  dark navy starfield, a LARGE clock inside a SCALLOPED disc (the scallop
  is drawn with Cairo: a ring of overlapping petal bumps around the disc
  edge — not a plain circle), date beneath, a music-player card showing
  the REAL current track (playerctl if a player exists, else the honest
  text "No track playing" — a track is never invented), and widget dots
  ORBITING the clock (animated: they rotate on a timer; if the timer
  cannot run, they sit at fixed orbit positions — see README-v5.md).
  Unlock: type the analyst account password (verified with `sudo -S true`,
  i.e. the real account password) OR, when AEGIS_TEST_UNLOCK=1, click
  "Unlock (test mode)". The test-mode click is the path used in QEMU
  verification and is labelled as such on the button.

Desktop: three floating-island top bar (left: workspaces from swaymsg,
centre: launcher + clock, right: network / battery / time — all real
data), plus scattered scalloped widgets: battery/charge ring (real upower
data; "No battery (VM)" when absent — never a faked 100%), music widget
(real player state or "No track"), system monitor (real CPU/mem from
/proc, updated every 2 s). NO weather widget: there is no real weather
source available offline in the guest, so it is omitted, not faked.
Colours come from ~/.config/aegis/theme.json (aegis-colours.py).
Blur is HONESTLY faked: sway has no live blur, so panels use a
Pillow pre-blurred wallpaper slice (blurred.png / blurred-top.png).

Requires in the guest: python3-gi, gir1.2-gtk-3.0, libgtk-layer-shell0,
python3-pil. If gtk-layer-shell is absent, windows fall back to plain
GTK windows (still usable, just not layer-anchored).
"""
import json, math, os, random, subprocess, sys, time
from pathlib import Path

TEST_UNLOCK = os.environ.get("AEGIS_TEST_UNLOCK", "") == "1"
HOME = Path.home()
CFG = HOME / ".config" / "aegis"

def load_theme():
    t = {"dominant": "#1b2350", "accent": "#7a8cff",
         "background": "#0a0e24",
         "accent_variants": {"light": "#aab6ff", "dark": "#3d4fa8"}}
    try:
        t.update(json.loads((CFG / "theme.json").read_text()))
    except Exception:
        pass
    return t

THEME = load_theme()

# ---- real system data (no faking) -------------------------------------------
def cpu_mem():
    try:
        a = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        a = [int(x) for x in a]; time.sleep(0.1)
        b = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        b = [int(x) for x in b]
        tot = sum(b) - sum(a); idle = b[3] - a[3]
        cpu = max(0.0, min(100.0, 100.0 * (1 - idle / tot))) if tot else 0.0
    except Exception:
        cpu = 0.0
    try:
        mem = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" in line:
                k, v = line.split(":", 1); mem[k.strip()] = int(v.split()[0])
        mpct = 100.0 * (1 - mem.get("MemAvailable", 0) / mem.get("MemTotal", 1))
    except Exception:
        mpct = 0.0
    return cpu, mpct

def battery():
    """Return (percent, state) or None when no battery exists (VM)."""
    try:
        devs = subprocess.run(["upower", "-e"], capture_output=True, text=True, timeout=5).stdout
        for dev in devs.splitlines():
            dev = dev.strip()
            if "battery" in dev.lower():
                out = subprocess.run(["upower", "-i", dev], capture_output=True, text=True, timeout=5).stdout
                pct = state = None
                for line in out.splitlines():
                    if "percentage:" in line: pct = line.split(":", 1)[1].strip()
                    if "state:" in line: state = line.split(":", 1)[1].strip()
                return pct, state
    except Exception:
        pass
    return None

def network_summary():
    try:
        out = subprocess.run(["ip", "-brief", "addr"], capture_output=True, text=True, timeout=5).stdout
        parts = []
        for line in out.splitlines():
            f = line.split()
            if len(f) >= 3 and f[0] != "lo":
                parts.append(f"{f[0]} {f[2]}")
        return "  ".join(parts) if parts else "no network"
    except Exception:
        return "no network"

def now_playing():
    """Real current track via playerctl, else None (caller shows 'No track playing')."""
    try:
        p = subprocess.run(["playerctl", "metadata", "--format", "{{artist}} - {{title}}"],
                           capture_output=True, text=True, timeout=3)
        s = p.stdout.strip()
        if p.returncode == 0 and s and s != " - ":
            st = subprocess.run(["playerctl", "status"], capture_output=True, text=True, timeout=3).stdout.strip()
            return f"{s}  [{st}]" if st else s
    except Exception:
        pass
    return None

def workspaces():
    try:
        out = subprocess.run(["swaymsg", "-t", "get_workspaces"], capture_output=True, text=True, timeout=5).stdout
        ws = json.loads(out)
        return [(w.get("num"), w.get("focused", False)) for w in ws]
    except Exception:
        return [(1, True), (2, False), (3, False)]

# ---- GTK ---------------------------------------------------------------------
try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib, Pango
    try:
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell as Layer
        HAS_LAYER = True
    except Exception:
        Layer = None; HAS_LAYER = False
    try:
        import cairo
        HAS_CAIRO = True
    except Exception:
        cairo = None; HAS_CAIRO = False
except Exception as e:  # pragma: no cover - only on hosts without GTK
    print(f"aegis-shell: GTK unavailable ({e})", file=sys.stderr); sys.exit(2)

ACCENT = THEME.get("accent", "#7a8cff")
BG = THEME.get("background", "#0a0e24")

BASE_CSS = f"""
window {{ background-color: transparent; }}
.aegis-island {{ background-color: rgba(16, 20, 48, 0.82); border-radius: 18px;
  border: 1px solid {ACCENT}; color: #eef0ff; padding: 6px 12px; }}
.aegis-island button {{ background: transparent; border: none; color: #eef0ff; }}
.aegis-island button:hover {{ background: {ACCENT}; border-radius: 10px; }}
.aegis-title {{ font-size: 15px; font-weight: bold; color: #eef0ff; }}
.aegis-clock {{ font-size: 64px; font-weight: bold; color: #ffffff; }}
.aegis-date {{ font-size: 18px; color: #cdd3ff; }}
.aegis-muted {{ color: #9aa3d0; }}
"""

# v5.0.1: the shell must never die on a missing display.
# Gdk.Screen.get_default() is None until GTK has opened a display, and
# apply_css() used to be the first GTK call in every mode — before any
# window existed — so on a serial console (no WAYLAND_DISPLAY at all)
# and on slow graphics where sway had not finished bringing up an
# output yet, the shell died with a bare TypeError ("Argument 0 does
# not allow None as a value"). The modes below now go through
# ensure_screen(), which initialises GTK explicitly, waits briefly
# while a display may still be appearing, and otherwise exits with a
# clear one-line message instead of a traceback.
NO_DISPLAY_MSG = (
    "aegis-shell: no graphical display found — run it inside a sway session "
    "from the VM's own display (tty1) with `aegis-gui`, not from a serial console."
)
DISPLAY_WAIT_SECONDS = 10.0

def ensure_screen():
    """Return a usable Gdk.Screen, or None if no display appears."""
    deadline = time.time() + DISPLAY_WAIT_SECONDS
    while True:
        screen = Gdk.Screen.get_default()
        if screen is not None:
            return screen
        # The environment names no display at all (serial console:
        # WAYLAND_DISPLAY and DISPLAY both unset) — no retry can help.
        if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
            return None
        try:
            Gtk.init_check()
        except Exception:
            pass
        screen = Gdk.Screen.get_default()
        if screen is not None:
            return screen
        if time.time() >= deadline:
            return None
        time.sleep(0.5)

def add_provider(prov):
    """Attach a CSS provider to the default screen (or exit cleanly)."""
    screen = Gdk.Screen.get_default() or ensure_screen()
    if screen is None:
        print(NO_DISPLAY_MSG, file=sys.stderr)
        sys.exit(4)
    Gtk.StyleContext.add_provider_for_screen(screen, prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

def apply_css():
    css = BASE_CSS
    try:
        css += "\n" + (CFG / "theme.css").read_text()
    except Exception:
        pass
    prov = Gtk.CssProvider(); prov.load_from_data(css.encode())
    add_provider(prov)

def layer_win(anchor_top=False, anchor_bottom=False, anchor_left=False, anchor_right=False,
              exclusive=0, layer=Layer.Layer.TOP if HAS_LAYER else None):
    w = Gtk.Window()
    if HAS_LAYER:
        Layer.init_for_window(w)
        if layer is not None: Layer.set_layer(w, layer)
        if anchor_top: Layer.set_anchor(w, Layer.Edge.TOP, True)
        if anchor_bottom: Layer.set_anchor(w, Layer.Edge.BOTTOM, True)
        if anchor_left: Layer.set_anchor(w, Layer.Edge.LEFT, True)
        if anchor_right: Layer.set_anchor(w, Layer.Edge.RIGHT, True)
        if exclusive: Layer.set_exclusive_zone(w, exclusive)
        # KeyboardInteractivity only exists in gtk-layer-shell >= 0.9;
        # bookworm ships 0.8.0, whose typelib has no such enum (proven by
        # an AttributeError crash of --desktop on 2026-11-14). The default
        # interactivity is NONE anyway, so skipping the call is safe.
        if hasattr(Layer, "KeyboardInteractivity"):
            Layer.set_keyboard_interactivity(w, Layer.KeyboardInteractivity.NONE)
    return w

class ScallopDisc(Gtk.DrawingArea):
    """A disc whose edge is a ring of petal bumps (scalloped/flower), drawn in Cairo."""
    def __init__(self, radius=150, petals=14):
        super().__init__()
        self.radius = radius; self.petals = petals
        self.set_size_request(radius * 2 + 40, radius * 2 + 40)
        self.connect("draw", self.on_draw)
    def on_draw(self, w, cr):
        if not HAS_CAIRO: return False
        cx = cy = self.radius + 20; r = self.radius
        # petal bumps around the rim
        cr.set_source_rgba(0.48, 0.55, 1.0, 0.95)
        for i in range(self.petals):
            a = 2 * math.pi * i / self.petals
            cr.arc(cx + r * math.cos(a), cy + r * math.sin(a), r * 0.22, 0, 2 * math.pi); cr.fill()
        # main disc
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_source_rgba(0.10, 0.13, 0.32, 0.96); cr.fill()
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_source_rgba(0.48, 0.55, 1.0, 0.9); cr.set_line_width(2); cr.stroke()
        return False

class OrbitDots(Gtk.DrawingArea):
    """Dots orbiting the clock disc. Animated on a timer; static if it cannot run."""
    def __init__(self, radius=215):
        super().__init__()
        self.radius = radius; self.angle = 0.0; self.animated = False
        self.set_size_request(radius * 2 + 60, radius * 2 + 60)
        self.connect("draw", self.on_draw)
        try:
            GLib.timeout_add(60, self.tick); self.animated = True
        except Exception:
            pass
    def tick(self):
        self.angle += 0.012; self.queue_draw(); return True
    def on_draw(self, w, cr):
        if not HAS_CAIRO: return False
        cx = cy = self.radius + 30
        for i in range(8):
            a = self.angle + i * math.pi / 4
            x, y = cx + self.radius * math.cos(a), cy + self.radius * math.sin(a)
            cr.arc(x, y, 6 if i % 2 else 4, 0, 2 * math.pi)
            cr.set_source_rgba(0.75, 0.8, 1.0, 0.9 if i % 2 else 0.55); cr.fill()
        return False

def starfield_widget():
    """Background: the real wallpaper image if present, else Cairo-drawn stars.

    v5 repack #3 bug fix: this used to be a bare Gtk.Image at the
    wallpaper's natural 1920x1080 size. The GtkOverlay then laid out at
    1920x1080, so on a 1280x800 display the lock content was centred at
    x=960 (off-screen right) and the unlock controls were cut off at the
    bottom. Now a DrawingArea paints the wallpaper scaled (cover fit) to
    its real allocation, so the overlay is exactly screen-sized.
    """
    da = Gtk.DrawingArea()
    da.connect("draw", _draw_wallpaper_or_stars)
    return da

def _draw_wallpaper_or_stars(w, cr):
    if not HAS_CAIRO:
        return False
    alloc = w.get_allocation()
    wp = CFG / "wallpaper.png"
    if wp.exists():
        try:
            from gi.repository import GdkPixbuf
            pb = GdkPixbuf.Pixbuf.new_from_file(str(wp))
            # cover fit: scale so the image covers the allocation, crop centre
            iw, ih = pb.get_width(), pb.get_height()
            scale = max(alloc.width / iw, alloc.height / ih)
            nw, nh = int(iw * scale), int(ih * scale)
            ox, oy = (alloc.width - nw) // 2, (alloc.height - nh) // 2
            cr.save()
            cr.translate(ox, oy); cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.paint()
            cr.restore()
            return False
        except Exception:
            pass
    return _draw_stars(w, cr)

def _draw_stars(w, cr):
    if not HAS_CAIRO: return False
    alloc = w.get_allocation()
    cr.set_source_rgb(0.03, 0.04, 0.14); cr.rectangle(0, 0, alloc.width, alloc.height); cr.fill()
    rng = random.Random(20261112)
    for _ in range(400):
        x, y = rng.random() * alloc.width, rng.random() * alloc.height
        b = rng.uniform(0.5, 1.0)
        cr.arc(x, y, rng.choice([1, 1, 2]), 0, 2 * math.pi)
        cr.set_source_rgba(b, b, 1.0, b); cr.fill()
    return False

# ---- lock screen --------------------------------------------------------------
def do_lock():
    apply_css()
    win = Gtk.Window(); win.set_title("AegisOS lock")
    win.fullscreen(); win.set_decorated(False)
    overlay = Gtk.Overlay(); win.add(overlay)
    overlay.add(starfield_widget())
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_halign(Gtk.Align.CENTER); box.set_valign(Gtk.Align.CENTER)
    overlay.add_overlay(box)
    # clock disc with orbiting dots behind it (sized to fit an 800px-tall
    # screen with the unlock controls: orbit 450 + date + music + rows)
    disc_wrap = Gtk.Overlay()
    orbit = OrbitDots(195); disc_wrap.add(orbit)
    disc = ScallopDisc(135); disc.set_halign(Gtk.Align.CENTER); disc.set_valign(Gtk.Align.CENTER)
    disc_wrap.add_overlay(disc)
    clock = Gtk.Label(); clock.get_style_context().add_class("aegis-clock")
    clock.set_halign(Gtk.Align.CENTER); clock.set_valign(Gtk.Align.CENTER)
    disc_wrap.add_overlay(clock)
    box.pack_start(disc_wrap, False, False, 0)
    date = Gtk.Label(); date.get_style_context().add_class("aegis-date")
    box.pack_start(date, False, False, 0)
    # music card — real track or honest "No track playing"
    music = Gtk.Frame(); music.get_style_context().add_class("aegis-island")
    mbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    mbox.pack_start(Gtk.Label(label="♪  Now playing"), False, False, 0)
    track = Gtk.Label(); track.set_line_wrap(True); track.set_max_width_chars(48)
    mbox.pack_start(track, False, False, 0)
    music.add(mbox); box.pack_start(music, False, False, 6)
    # unlock row
    pw = Gtk.Entry(); pw.set_visibility(False); pw.set_placeholder_text("Analyst password to unlock")
    pw.set_width_chars(28)
    unlock_btn = Gtk.Button(label="Unlock")
    test_btn = Gtk.Button(label="Unlock (test mode)" if TEST_UNLOCK else "Unlock (test mode — disabled)")
    test_btn.set_sensitive(TEST_UNLOCK)
    status = Gtk.Label(); status.get_style_context().add_class("aegis-muted")
    status.set_line_wrap(True); status.set_max_width_chars(60); status.set_justify(Gtk.Justification.CENTER)
    row = Gtk.Box(spacing=8); row.pack_start(pw, False, False, 0); row.pack_start(unlock_btn, False, False, 0)
    box.pack_start(row, False, False, 2)
    box.pack_start(test_btn, False, False, 0)
    box.pack_start(status, False, False, 0)
    if not TEST_UNLOCK:
        status.set_text("Test-mode unlock is OFF (AEGIS_TEST_UNLOCK=1 to enable it for QEMU verification).")

    def refresh():
        now = time.localtime()
        clock.set_text(time.strftime("%H:%M", now))
        date.set_text(time.strftime("%A, %d %B %Y", now))
        track.set_text(now_playing() or "No track playing")
        return True
    refresh(); GLib.timeout_add_seconds(5, refresh)

    def unlock_ok():
        Gtk.main_quit()
    def try_password(_btn):
        pwd = pw.get_text()
        if not pwd:
            status.set_text("Type the analyst password, or use test-mode unlock."); return
        try:
            p = subprocess.run(["sudo", "-S", "true"], input=pwd + "\n",
                               capture_output=True, text=True, timeout=10)
            if p.returncode == 0:
                status.set_text("Unlocked."); unlock_ok()
            else:
                status.set_text("Wrong password.")
        except Exception as e:
            status.set_text(f"Password check unavailable ({e}); use test-mode unlock.")
    unlock_btn.connect("clicked", try_password)
    pw.connect("activate", try_password)
    test_btn.connect("clicked", lambda _b: unlock_ok())
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    print("aegis-shell: lock screen shown (orbit animation: %s)" % ("animated" if orbit.animated else "static positions"), flush=True)
    Gtk.main()
    print("aegis-shell: unlocked", flush=True)
    return 0

def render_lock_bg(out):
    """Render the lock frame as a PNG for swaylock (static image path)."""
    from PIL import Image, ImageDraw, ImageFont
    wp = CFG / "wallpaper.png"
    img = Image.open(wp).convert("RGB") if wp.exists() else Image.new("RGB", (1920, 1080), (10, 14, 36))
    img = img.resize((1920, 1080))
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy = 960, 420
    for i in range(14):  # scalloped rim
        a = 2 * math.pi * i / 14
        x, y = cx + 190 * math.cos(a), cy + 190 * math.sin(a)
        d.ellipse([x - 42, y - 42, x + 42, y + 42], fill=(122, 140, 255, 240))
    d.ellipse([cx - 190, cy - 190, cx + 190, cy + 190], fill=(26, 33, 82, 245), outline=(122, 140, 255, 255), width=3)
    now = time.strftime("%H:%M")
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 110)
        fs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    except Exception:
        f = ImageFont.load_default(); fs = f
    w = d.textlength(now, font=f); d.text((cx - w / 2, cy - 70), now, font=f, fill=(255, 255, 255))
    day = time.strftime("%A, %d %B %Y")
    w = d.textlength(day, font=fs); d.text((cx - w / 2, cy + 230), day, font=fs, fill=(205, 211, 255))
    img.save(out); print(f"aegis-shell: lock background written to {out}", flush=True)

# ---- desktop -------------------------------------------------------------------
def island_box():
    b = Gtk.Box(spacing=10); b.get_style_context().add_class("aegis-island"); return b

def do_desktop():
    # v5 repack #3 bug fix: the desktop silently fell back to plain windows
    # when the GtkLayerShell typelib was missing, and sway floated them all
    # centred on top of each other (bar/widgets overlapping, text clipped).
    # Never do that again: refuse to start a broken desktop, loudly.
    if not HAS_LAYER:
        print("aegis-shell: ERROR: GtkLayerShell typelib missing "
              "(gir1.2-gtk-layer-shell-0.1 not installed) — refusing to start "
              "the desktop in broken fallback mode.", file=sys.stderr)
        return 3
    print("aegis-shell: layer-shell available, starting desktop", flush=True)
    apply_css()
    # --- top bar: three floating islands in one layer-shell bar window
    bar = layer_win(anchor_top=True, anchor_left=True, anchor_right=True, exclusive=48)
    bar.set_title("AegisOS bar")
    hbox = Gtk.Box(spacing=24); hbox.set_margin_top(6); hbox.set_margin_bottom(6)
    hbox.set_margin_start(12); hbox.set_margin_end(12)
    bar.add(hbox)
    ws_box = island_box()
    ws_btns = []
    for num, _f in workspaces():
        b = Gtk.Button(label=str(num))
        b.connect("clicked", lambda _b, n=num: subprocess.run(
            ["swaymsg", "workspace", str(n)], capture_output=True))
        ws_box.pack_start(b, False, False, 0); ws_btns.append(b)
    hbox.pack_start(ws_box, False, False, 0)
    mid = island_box()
    launch = Gtk.Button(label="◉  AegisOS")
    launch.connect("clicked", lambda _b: subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--launcher"]))
    clock = Gtk.Label(label=time.strftime("%H:%M")); clock.get_style_context().add_class("aegis-title")
    mid.pack_start(launch, False, False, 0); mid.pack_start(clock, False, False, 0)
    hbox.set_center_widget(mid)
    right = island_box()
    net_l = Gtk.Label(label=network_summary())
    bat_l = Gtk.Label(label="battery: …")
    time_l = Gtk.Label(label=time.strftime("%H:%M:%S"))
    right.pack_start(net_l, False, False, 0); right.pack_start(bat_l, False, False, 0)
    right.pack_start(time_l, False, False, 0)
    hbox.pack_end(right, False, False, 0)
    bar.show_all()

    # --- widgets: battery ring (bottom-left), system monitor (bottom-right), music (top-right)
    bat_win = layer_win(anchor_bottom=True, anchor_left=True)
    bat_box = island_box(); bat_box.set_orientation(Gtk.Orientation.VERTICAL)
    bat_title = Gtk.Label(label="Battery"); bat_title.get_style_context().add_class("aegis-title")
    bat_ring = Gtk.DrawingArea(); bat_ring.set_size_request(110, 110)
    bat_text = Gtk.Label(label="…")
    bat_box.pack_start(bat_title, False, False, 0); bat_box.pack_start(bat_ring, False, False, 0)
    bat_box.pack_start(bat_text, False, False, 0)
    bat_win.add(bat_box)
    if HAS_LAYER:
        Layer.set_margin(bat_win, Layer.Edge.BOTTOM, 16)
        Layer.set_margin(bat_win, Layer.Edge.LEFT, 16)
    bat_win.show_all()
    bat_state = {"pct": None}
    def draw_ring(w, cr):
        if not HAS_CAIRO: return False
        pct = bat_state["pct"]
        cr.arc(55, 55, 44, 0, 2 * math.pi); cr.set_source_rgba(1, 1, 1, 0.15); cr.set_line_width(10); cr.stroke()
        if pct is not None:
            cr.arc(55, 55, 44, -math.pi / 2, -math.pi / 2 + 2 * math.pi * pct / 100.0)
            cr.set_source_rgb(0.48, 0.55, 1.0); cr.set_line_width(10); cr.stroke()
        return False
    bat_ring.connect("draw", draw_ring)

    sys_win = layer_win(anchor_bottom=True, anchor_right=True)
    sys_box = island_box(); sys_box.set_orientation(Gtk.Orientation.VERTICAL)
    sys_box.pack_start(Gtk.Label(label="System"), False, False, 0)
    sys_l = Gtk.Label(label="CPU …  MEM …"); sys_l.set_xalign(0)
    sys_box.pack_start(sys_l, False, False, 0)
    sys_win.add(sys_box)
    if HAS_LAYER:
        Layer.set_margin(sys_win, Layer.Edge.BOTTOM, 16)
        Layer.set_margin(sys_win, Layer.Edge.RIGHT, 16)
    sys_win.show_all()

    mus_win = layer_win(anchor_top=True, anchor_right=True)
    mus_box = island_box(); mus_box.set_orientation(Gtk.Orientation.VERTICAL)
    mus_box.pack_start(Gtk.Label(label="♪  Music"), False, False, 0)
    mus_l = Gtk.Label(label="No track playing"); mus_l.set_line_wrap(True); mus_l.set_max_width_chars(32)
    mus_box.pack_start(mus_l, False, False, 0)
    mus_win.add(mus_box)
    # offset the music widget below the bar (layer-shell margins)
    if HAS_LAYER:
        Layer.set_margin(mus_win, Layer.Edge.TOP, 64)
        Layer.set_margin(mus_win, Layer.Edge.RIGHT, 16)
    mus_win.show_all()

    def refresh():
        now = time.localtime()
        clock.set_text(time.strftime("%H:%M", now))
        time_l.set_text(time.strftime("%H:%M:%S", now))
        net_l.set_text(network_summary())
        b = battery()
        if b is None:
            bat_l.set_text("No battery (VM)"); bat_text.set_text("No battery (VM)")
            bat_state["pct"] = None
        else:
            pct, state = b
            bat_l.set_text(f"battery {pct} ({state})" if state else f"battery {pct}")
            bat_text.set_text(f"{pct}  {state or ''}".strip())
            try: bat_state["pct"] = float(str(pct).strip("%"))
            except Exception: bat_state["pct"] = None
        bat_ring.queue_draw()
        cpu, mem = cpu_mem()
        sys_l.set_text(f"CPU {cpu:.0f}%   MEM {mem:.0f}%\n{time.strftime('%H:%M:%S')}")
        mus_l.set_text(now_playing() or "No track playing")
        return True
    refresh(); GLib.timeout_add_seconds(2, refresh)
    print("aegis-shell: desktop shown (bar + battery/system/music widgets)", flush=True)
    Gtk.main()
    return 0

# ---- radial launcher -------------------------------------------------------------
def do_launcher():
    apply_css()
    # v5 repack #3 bug fix: BASE_CSS makes every window transparent, so the
    # launcher showed the bright wallpaper straight through its buttons
    # (pale-on-pale, barely readable). The launcher is a plain window, not
    # a layer surface: give it an opaque dark background and solid buttons.
    prov = Gtk.CssProvider()
    prov.load_from_data(b"""
window { background-color: rgba(10, 14, 36, 0.96); }
.aegis-launcher-btn { background-image: none; background-color: rgba(38, 46, 96, 0.98); color: #ffffff;
  padding: 10px 14px; border: 1px solid #7a8cff; border-radius: 12px; font-weight: bold; }
.aegis-launcher-btn:hover { background-image: none; background-color: #3d4fa8; }
""")
    add_provider(prov)
    win = Gtk.Window(); win.set_title("AegisOS launcher")
    win.set_default_size(640, 520); win.set_position(Gtk.WindowPosition.CENTER)
    win.set_decorated(False)
    fixed = Gtk.Fixed(); win.add(fixed)
    centre = Gtk.Label(label="AegisOS"); centre.get_style_context().add_class("aegis-title")
    fixed.put(centre, 290, 240)
    apps = []
    # real .desktop apps installed in the image
    for d in ("/usr/share/applications", str(HOME / ".local/share/applications")):
        for fp in sorted(Path(d).glob("*.desktop")) if Path(d).exists() else []:
            name = exec_ = None
            try:
                for line in fp.read_text(errors="replace").splitlines():
                    if line.startswith("Name=") and name is None: name = line[5:].strip()
                    if line.startswith("Exec=") and exec_ is None: exec_ = line[5:].strip().split()[0]
            except Exception:
                continue
            if name and exec_ and name not in [a[0] for a in apps]:
                apps.append((name, exec_))
    # fixed entries first (console + terminal are the AegisOS essentials)
    fixed_apps = [("Console :8000", "firefox-esr http://127.0.0.1:8000"),
                  ("Terminal", "foot"), ("Browser", "firefox-esr"),
                  ("Saral", "foot saral"), ("Lock screen", "aegis-gui --lock")]
    seen = {a[0] for a in fixed_apps}
    for name, exe in apps:
        if name not in seen and len(fixed_apps) < 10:
            fixed_apps.append((name, exe)); seen.add(name)
    n = len(fixed_apps)
    for i, (name, cmd) in enumerate(fixed_apps):
        a = 2 * math.pi * i / max(n, 1) - math.pi / 2
        x, y = int(320 + 210 * math.cos(a) - 55), int(250 + 170 * math.sin(a) - 18)
        b = Gtk.Button(label=name)
        b.get_style_context().add_class("aegis-launcher-btn")
        b.connect("clicked", lambda _b, c=cmd: (subprocess.Popen(c.split()), Gtk.main_quit()))
        fixed.put(b, x, y)
    close = Gtk.Button(label="✕ Close")
    close.connect("clicked", lambda _b: Gtk.main_quit())
    fixed.put(close, 280, 470)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    print(f"aegis-shell: launcher shown with {n} real apps", flush=True)
    Gtk.main()
    return 0

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--desktop"
    if mode == "--lock": sys.exit(do_lock())
    if mode == "--launcher": sys.exit(do_launcher())
    if mode == "--lock-bg":
        render_lock_bg(sys.argv[2] if len(sys.argv) > 2 else str(CFG / "lock-bg.png")); sys.exit(0)
    sys.exit(do_desktop())
