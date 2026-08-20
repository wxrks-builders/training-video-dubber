"""
YouTube thumbnail rendering.

Pure black canvas, deep emerald radial glow rising from a corner with a faint
grid inside it, a glassy translucent 3D icon, thin-line outline glyphs echoing
the theme, a mixed-weight headline (bold white + extra-light gray on one line),
an extra-light subline, an arrow cue, and the wxrks wordmark. Generous margins.
"""

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (150, 155, 158)          # extra-light headline words
SOFT_WHITE = (196, 202, 205)    # subline
EMERALD = (16, 185, 129)        # glow core
EMERALD_DEEP = (5, 90, 66)      # glow falloff
GRID_LINE = (16, 74, 56)

_ASSETS = Path(__file__).parent.parent / "assets"
_FONT_DIR = _ASSETS / "fonts"
LOGO_PATH = _ASSETS / "logo.png"

MARGIN = 84
GLOW_CORNER = "bottom-left"


# ── Fonts ─────────────────────────────────────────────────────────────────────

_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    path = _FONT_DIR / f"Poppins-{weight}.ttf"
    if path.exists():
        return ImageFont.truetype(str(path), size)
    for fb in _FALLBACKS:
        if os.path.exists(fb):
            return ImageFont.truetype(fb, size)
    return ImageFont.load_default(size=size)


def _text_w(draw, text, font) -> int:
    return draw.textbbox((0, 0), text, font=font)[2]


# ── Background: radial glow + grid ────────────────────────────────────────────

def _glow_mask(corner: str = GLOW_CORNER) -> Image.Image:
    """
    Falloff built small and upscaled — a per-pixel 1280x720 loop in Python is
    slow, and the blur hides the interpolation completely.
    """
    s = 96
    g = Image.new("L", (s, s), 0)
    px = g.load()
    cx, cy = {
        "bottom-left": (-6, s + 6), "bottom-right": (s + 6, s + 6),
        "top-left": (-6, -6), "top-right": (s + 6, -6),
    }[corner]
    radius = s * 1.5
    for y in range(s):
        for x in range(s):
            d = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) / radius
            px[x, y] = 0 if d >= 1 else int(255 * (1 - d) ** 1.5)
    return g.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(48))


def _radial_glow(mask: Image.Image) -> Image.Image:
    """Emerald core fading out into deep green, over black."""
    glow = Image.new("RGB", (W, H), EMERALD_DEEP)
    core = Image.new("RGB", (W, H), EMERALD)
    glow.paste(core, (0, 0), mask.point(lambda v: max(0, min(255, int((v - 150) * 2.0)))))

    out = Image.new("RGB", (W, H), BLACK)
    out.paste(glow, (0, 0), mask.point(lambda v: int(v * 0.78)))
    return out


def _grid_overlay(glow_mask: Image.Image, step: int = 46) -> Image.Image:
    """Faint darker grid, visible only where the glow is."""
    grid = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(grid)
    for x in range(0, W, step):
        d.line([(x, 0), (x, H)], fill=GRID_LINE, width=1)
    for y in range(0, H, step):
        d.line([(0, y), (W, y)], fill=GRID_LINE, width=1)
    return grid


def _background() -> Image.Image:
    mask = _glow_mask()
    base = _radial_glow(mask)
    grid = _grid_overlay(mask)
    base.paste(grid, (0, 0), mask.point(lambda v: int(v * 0.55)))
    return base


# ── Thin-line outline glyphs ──────────────────────────────────────────────────

def _outline_glyphs(img: Image.Image) -> None:
    """Two faint dark-green line figures echoing the theme, well behind everything."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    line = (24, 116, 86, 90)

    d.ellipse([W - 300, -120, W - 20, 160], outline=line, width=2)
    d.ellipse([W - 240, -66, W - 78, 96], outline=line, width=2)
    # Right of the logo lock-up, not on top of it.
    d.rounded_rectangle([440, H - 210, 690, H - 58], radius=28, outline=line, width=2)
    d.line([(480, H - 150), (650, H - 150)], fill=line, width=2)
    d.line([(480, H - 116), (596, H - 116)], fill=line, width=2)

    img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"), (0, 0))


# ── Glassy 3D icon ────────────────────────────────────────────────────────────

def _placeholder_icon(size: int) -> Image.Image:
    """
    Frosted glass over a brighter green core. Only a fallback — the real icon is
    generated per video — but a thumbnail must never fail to render.
    """
    s = size
    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(icon)
    pad, r = int(s * 0.13), int(s * 0.24)

    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=r, fill=(14, 120, 88, 165))
    core = int(s * 0.28)
    d.rounded_rectangle([core, core, s - core, s - core], radius=int(s * 0.13),
                        fill=(60, 240, 176, 225))
    icon = icon.filter(ImageFilter.GaussianBlur(1.2))

    # Clip the gloss to the icon silhouette, or it spills past the rounded corners.
    silhouette = Image.new("L", (s, s), 0)
    ImageDraw.Draw(silhouette).rounded_rectangle(
        [pad, pad, s - pad, s - pad], radius=r, fill=255)

    gloss = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    gd.ellipse([pad - int(s * 0.06), pad - int(s * 0.24),
                s - pad + int(s * 0.06), int(s * 0.46)], fill=(225, 255, 244, 52))
    gloss.putalpha(Image.composite(gloss.getchannel("A"),
                                   Image.new("L", (s, s), 0), silhouette))
    icon = Image.alpha_composite(icon, gloss)

    d = ImageDraw.Draw(icon)
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=r,
                        outline=(206, 255, 238, 135), width=max(2, s // 120))
    return icon


def _place_icon(img: Image.Image, icon: Image.Image, box_size: int, center) -> None:
    """Drop shadow, then the icon floating slightly above it."""
    icon = icon.convert("RGBA")
    icon.thumbnail((box_size, box_size), Image.LANCZOS)
    cx, cy = center
    x, y = cx - icon.width // 2, cy - icon.height // 2

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", icon.size, (0, 0, 0, 190)), (x, y + 26), icon)
    shadow = shadow.filter(ImageFilter.GaussianBlur(30))

    composed = Image.alpha_composite(img.convert("RGBA"), shadow)
    composed.paste(icon, (x, y), icon)
    img.paste(composed.convert("RGB"), (0, 0))


# ── Headline ──────────────────────────────────────────────────────────────────

def _split_emphasis(headline: str, bold_words: int = None) -> list:
    """
    [(word, is_bold), ...]. '*' marks emphasis explicitly ("*Filter* and export"),
    otherwise the leading half of the line is bold and the rest extra-light.
    """
    words = headline.split()
    if any(w.startswith("*") or w.endswith("*") for w in words):
        return [(w.strip("*"), w.startswith("*") or w.endswith("*")) for w in words]
    n = bold_words if bold_words is not None else max(1, round(len(words) * 0.5))
    return [(w, i < n) for i, w in enumerate(words)]


def _wrap(draw, parts, bold_f, light_f, max_w) -> list:
    """Greedy wrap that keeps each word's weight."""
    lines, cur, cur_w = [], [], 0
    space = _text_w(draw, " ", light_f)
    for word, is_bold in parts:
        f = bold_f if is_bold else light_f
        w = _text_w(draw, word, f)
        if cur and cur_w + space + w > max_w:
            lines.append(cur)
            cur, cur_w = [], 0
        cur.append((word, is_bold, w))
        cur_w += (space if len(cur) > 1 else 0) + w
    if cur:
        lines.append(cur)
    return lines


def _draw_headline(img, draw, headline, top, max_w, size=76) -> int:
    bold_f, light_f = _font("Bold", size), _font("ExtraLight", size)
    parts = _split_emphasis(headline)

    lines = _wrap(draw, parts, bold_f, light_f, max_w)
    while len(lines) > 3 and size > 44:
        size -= 6
        bold_f, light_f = _font("Bold", size), _font("ExtraLight", size)
        lines = _wrap(draw, parts, bold_f, light_f, max_w)

    space = _text_w(draw, " ", light_f)
    y = top
    for line in lines:
        x = MARGIN
        for word, is_bold, w in line:
            draw.text((x, y), word, font=(bold_f if is_bold else light_f),
                      fill=(WHITE if is_bold else GRAY))
            x += w + space
        y += int(size * 1.24)
    return y


# ── Logo + arrow ──────────────────────────────────────────────────────────────

def _draw_logo(img: Image.Image, height: int = 34) -> None:
    if not LOGO_PATH.exists():
        return
    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo.thumbnail((10_000, height), Image.LANCZOS)
    img.paste(logo, (MARGIN, H - MARGIN - logo.height + 6), logo)


def _draw_arrow(draw) -> None:
    x, y, ln = W - MARGIN - 54, H - MARGIN - 8, 42
    draw.line([(x, y), (x + ln, y)], fill=(120, 210, 178), width=2)
    draw.line([(x + ln - 13, y - 10), (x + ln, y)], fill=(120, 210, 178), width=2)
    draw.line([(x + ln - 13, y + 10), (x + ln, y)], fill=(120, 210, 178), width=2)


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_thumbnail(
    headline: str,
    output_path: str,
    subline: str = "",
    icon_path: str = None,
) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    img = _background()
    _outline_glyphs(img)

    icon = None
    if icon_path and os.path.exists(icon_path):
        try:
            icon = Image.open(icon_path)
        except Exception:
            icon = None
    _place_icon(img, icon or _placeholder_icon(560), 420, (W - MARGIN - 230, H // 2 - 30))

    draw = ImageDraw.Draw(img)
    text_max_w = W - MARGIN * 2 - 480

    y = _draw_headline(img, draw, headline, top=MARGIN + 96, max_w=text_max_w)
    if subline:
        sub_f = _font("ExtraLight", 30)
        sy = y + 18
        for line in _wrap_plain(draw, subline, sub_f, text_max_w)[:2]:
            draw.text((MARGIN, sy), line, font=sub_f, fill=SOFT_WHITE)
            sy += 40

    _draw_logo(img)
    _draw_arrow(draw)

    img.save(output_path, "JPEG", quality=94)
    return output_path


def _wrap_plain(draw, text, font, max_w) -> list:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and _text_w(draw, trial, font) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines
