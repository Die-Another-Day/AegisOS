#!/usr/bin/env python3
"""Generate the two AegisOS v5 wallpapers with Pillow (original, no copied art).
- aegis-starfield.png: dark navy/indigo starfield with soft nebula blobs.
- aegis-sunset.png: warm sunset gradient with a low sun and hill silhouettes.
1920x1080. Run: python3 generate-wallpapers.py [outdir]
"""
import math, os, random, sys
from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080

def vgrad(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img

def starfield(out):
    rng = random.Random(20261112)
    img = vgrad(W, H, (5, 8, 32), (16, 22, 64))
    # soft nebula blobs (indigo / teal / violet), blurred
    neb = Image.new("RGB", (W, H), (0, 0, 0))
    nd = ImageDraw.Draw(neb)
    for (cx, cy, r, col) in [(420, 300, 320, (38, 48, 120)), (1500, 700, 380, (24, 70, 90)),
                             (1150, 220, 260, (70, 40, 110)), (700, 850, 300, (20, 40, 90))]:
        nd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    neb = neb.filter(ImageFilter.GaussianBlur(120))
    # screen-blend the nebula blobs onto the gradient (pure Pillow, no numpy)
    px = img.load(); npx = neb.load()
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            r, g, b = px[x, y]; nr, ng, nb = npx[x, y]
            px[x, y] = (min(255, r + nr // 2), min(255, g + ng // 2), min(255, b + nb // 2))
    d = ImageDraw.Draw(img)
    for _ in range(900):
        x, y = rng.randrange(W), rng.randrange(H)
        s = rng.random()
        r = 1 if s < 0.85 else (2 if s < 0.97 else 3)
        bright = rng.randint(140, 255)
        col = (bright, bright, min(255, bright + 15)) if rng.random() < 0.8 else (bright, bright - 30, bright - 60)
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
        if r == 3:  # cross sparkle on the brightest few
            d.line([x - 6, y, x + 6, y], fill=col, width=1)
            d.line([x, y - 6, x, y + 6], fill=col, width=1)
    img.save(out)
    print("wrote", out)

def sunset(out):
    rng = random.Random(77)
    img = vgrad(W, H, (64, 32, 96), (255, 150, 60))
    d = ImageDraw.Draw(img)
    # sun disc with glow
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W // 2 - 260, 380, W // 2 + 260, 900], fill=(255, 120, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    px, gpx = img.load(), glow.load()
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            r, g, b = px[x, y]; gr, gg, gb = gpx[x, y]
            px[x, y] = (min(255, r + gr // 2), min(255, g + gg // 2), min(255, b + gb // 2))
    d = ImageDraw.Draw(img)
    d.ellipse([W // 2 - 130, 480, W // 2 + 130, 740], fill=(255, 214, 130))
    # hill silhouettes
    for base, col, amp in [(760, (52, 22, 66), 90), (860, (30, 14, 44), 70), (960, (16, 8, 30), 50)]:
        pts = [(0, H), (0, base)]
        for x in range(0, W + 40, 40):
            pts.append((x, base + int(amp * math.sin(x / 260.0 + base))))
        pts += [(W, H)]
        d.polygon(pts, fill=col)
    # a few birds
    for _ in range(12):
        x, y = rng.randrange(200, W - 200), rng.randrange(150, 450)
        d.arc([x - 12, y - 6, x, y + 6], 200, 340, fill=(30, 14, 44), width=2)
        d.arc([x, y - 6, x + 12, y + 6], 200, 340, fill=(30, 14, 44), width=2)
    img.save(out)
    print("wrote", out)

if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)) + "/wallpapers"
    os.makedirs(outdir, exist_ok=True)
    starfield(os.path.join(outdir, "aegis-starfield.png"))
    sunset(os.path.join(outdir, "aegis-sunset.png"))
