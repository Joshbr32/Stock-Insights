"""Generate Stock Insights PWA icons. Run once: `python make_icons.py`."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "icons"
OUT.mkdir(exist_ok=True)

CREAM = (244, 238, 224)
INK = (21, 20, 15)
ACCENT = (140, 28, 28)


def render_icon(size: int, maskable: bool = False) -> Image.Image:
    """Editorial monogram: black 'SI' on cream, with a crimson rule beneath."""
    img = Image.new("RGB", (size, size), CREAM)
    draw = ImageDraw.Draw(img)

    # Maskable icons need a safe zone — keep content within ~80% radius of center
    pad = int(size * 0.18) if maskable else int(size * 0.06)

    # Try to find a serif/strong font on the system. Fall back to default.
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/Library/Fonts/Georgia.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
    ]
    font = None
    for path in candidates:
        try:
            font = ImageFont.truetype(path, int(size * 0.55))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    text = "Si"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1] - int(size * 0.04)
    draw.text((tx, ty), text, fill=INK, font=font)

    # Decorative crimson rule
    rule_y = int(size * 0.78)
    rule_w = int(size * 0.18)
    rule_x = (size - rule_w) // 2
    draw.rectangle(
        [rule_x, rule_y, rule_x + rule_w, rule_y + max(2, int(size * 0.012))],
        fill=ACCENT,
    )

    # Subtle border (skip for maskable so the safe-zone cover is clean)
    if not maskable:
        b = max(1, int(size * 0.005))
        draw.rectangle([pad, pad, size - pad, size - pad], outline=INK, width=b)
    return img


for s in (192, 512):
    render_icon(s).save(OUT / f"icon-{s}.png", optimize=True)

render_icon(512, maskable=True).save(OUT / "icon-maskable-512.png", optimize=True)

print("Icons written to", OUT)
