"""Render carousel slides on top of assets/base_template.png (1080x1350)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "assets" / "base_template.png"
FONT = ROOT / "assets" / "Inter.ttf"
W, H = 1080, 1350
GLOW_Y = 740          # the light bar sits here
TITLE_BOTTOM = 690    # titles end just above the glow
BODY_TOP = 790
MAX_W = 800


def font(size, weight):
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_axes([min(32, max(14, size * 0.4)), weight])
    return f


def wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for word in text.split():
        t = f"{cur} {word}".strip()
        if draw.textlength(t, font=fnt) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_title(draw, text, max_lines=4):
    for size in range(104, 56, -4):
        f = font(size, 300)
        lines = wrap(draw, text, f, MAX_W)
        if len(lines) <= max_lines:
            return f, lines, size
    f = font(56, 300)
    return f, wrap(draw, text, f, MAX_W), 56


def draw_title(img, text):
    d = ImageDraw.Draw(img)
    f, lines, size = fit_title(d, text)
    lh = int(size * 0.96)
    top = TITLE_BOTTOM - lh * len(lines)
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    for i, line in enumerate(lines):
        w = md.textlength(line, font=f)
        md.text(((W - w) / 2, top + i * lh), line, font=f, fill=255)
    # vertical gradient: dim grey-blue far from the light -> lavender near it
    y0, y1 = top, TITLE_BOTTOM
    t = np.clip((np.arange(H) - y0) / max(1, (y1 - y0)), 0, 1)[:, None] ** 1.3
    dim = np.array([72, 76, 92])
    lit = np.array([205, 185, 245])
    grad = (dim + (lit - dim) * t[:, :, None]).astype(np.uint8)
    grad = np.broadcast_to(grad, (H, W, 3))
    layer = Image.fromarray(np.ascontiguousarray(grad), "RGB")
    img.paste(layer, (0, 0), mask)
    return top


def draw_kicker(img, text, y):
    """Small letter-spaced label above the title (e.g. 'WEBSITE TRUST' or '01')."""
    d = ImageDraw.Draw(img)
    f = font(28, 500)
    sp = 5
    widths = [d.textlength(c, font=f) for c in text]
    x = (W - (sum(widths) + sp * (len(text) - 1))) / 2
    for c, w in zip(text, widths):
        d.text((x, max(60, y)), c, font=f, fill=(140, 135, 185))
        x += w + sp


def draw_body(img, text):
    d = ImageDraw.Draw(img)
    size = 34
    while True:
        f = font(size, 300)
        lines = wrap(d, text, f, MAX_W)
        if len(lines) <= 7 or size <= 28:
            break
        size -= 2
    lh = int(size * 1.35)
    for i, line in enumerate(lines):
        w = d.textlength(line, font=f)
        d.text(((W - w) / 2, BODY_TOP + i * lh), line, font=f, fill=(228, 228, 234))


def render_slide(title, body, out_path, kicker=None):
    img = Image.open(TEMPLATE).convert("RGB")
    top = draw_title(img, title)
    if kicker:
        draw_kicker(img, kicker, top - 64)
    if body:
        draw_body(img, body)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_carousel(slides, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, s in enumerate(slides, 1):
        p = out_dir / f"slide_{i}.png"
        render_slide(s["title"], s.get("body", ""), p, s.get("kicker"))
        paths.append(p)
    return paths


if __name__ == "__main__":
    demo = [
        {"title": "7 Things To Consider on Your Website as a Small Business",
         "body": "Your website is your digital storefront. To stand out online, a great website needs more than just a pretty design it requires strategy."},
        {"title": "Mobile responsive",
         "body": "Over half of all web traffic comes from phones. If your site looks broken or is hard to navigate on mobile, you are actively losing customers to your competitors."},
    ]
    print(render_carousel(demo, ROOT / "preview"))
