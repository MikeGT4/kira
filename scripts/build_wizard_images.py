"""Generate Inno-Setup wizard BMP images from Kira branding.

Outputs two 24-bit BMPs that the Inno installer references via
WizardImageFile / WizardSmallImageFile:

  - assets/wizard-side.bmp  (164x314 px) -- left panel, Welcome/Finished pages
  - assets/wizard-small.bmp (55x58 px)  -- top-right header on inner pages

Inno 6.5.2+ supports PNG, but BMP-24 stays universally compatible across all
Inno 6 builds and is what jrsoftware ships in the modern-style template.

Run from anywhere:
    python scripts/build_wizard_images.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Inno modern-style canonical raw sizes. Will be upscaled by Inno itself
# (WizardSizePercent default 100, can go to ~150% on hi-DPI).
SIDE_W, SIDE_H = 164, 314
SMALL_W, SMALL_H = 55, 58

# Branding -- dark glass background. Hex 1c1c1c chosen to match
# WizardImageBackColor in kira.iss; keep them in lockstep.
BG_DARK = (28, 28, 28)
ACCENT_YELLOW = (255, 209, 71)  # Kira's tray accent
TEXT_PRIMARY = (255, 255, 255)
TEXT_SECONDARY = (180, 180, 180)
TEXT_TERTIARY = (110, 110, 110)


def _load_branded_icon() -> Image.Image:
    """Load the largest frame from icon-branded.ico as RGBA."""
    repo_root = Path(__file__).resolve().parents[1]
    ico = repo_root / "assets" / "icon-branded.ico"
    if not ico.exists():
        raise FileNotFoundError(f"Missing {ico} -- run scripts/regenerate_branded_icon.py first")
    img = Image.open(ico)
    # Pillow exposes ICO frames via .info['sizes']; pick the largest by
    # asking IcoImagePlugin to return that specific frame (modern Pillow
    # removed the img.size setter pattern).
    sizes = img.info.get("sizes")
    if sizes:
        largest = max(sizes, key=lambda s: s[0] * s[1])
        try:
            from PIL import IcoImagePlugin  # type: ignore[import-untyped]
            # F2-10: with-block damit der File-Handle definitiv geschlossen
            # wird; vorher leakte das Handle bei jedem Aufruf weil
            # IcoImagePlugin.IcoFile(open(...)) nichts schliesst.
            with open(ico, "rb") as fh:
                ico_img = IcoImagePlugin.IcoFile(fh)
                img = ico_img.getimage(largest)
                # PIL lazy-loads pixel data; force load while file open,
                # sonst spaeter `seek of closed file` beim convert().
                img.load()
        except (ImportError, AttributeError, OSError):
            img.load()
    return img.convert("RGBA")


def _try_load_font(size: int, *, bold: bool = False):
    """Pick a clean sans-serif. Fallback chain stays graceful on Win/WSL."""
    candidates = [
        # Windows-side fonts (preferred for the developer's machine)
        "C:\\Windows\\Fonts\\segoeui.ttf" if not bold else "C:\\Windows\\Fonts\\segoeuib.ttf",
        "/mnt/c/Windows/Fonts/segoeui.ttf"
        if not bold
        else "/mnt/c/Windows/Fonts/segoeuib.ttf",
        # WSL DejaVu fallback
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    width: int,
    font,
    color: tuple[int, int, int],
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    x = (width - text_w) // 2
    draw.text((x, y), text, fill=color, font=font)


def build_side_image(out_path: Path) -> None:
    """164x314 px left panel: dark BG + icon centered top + wordmark + footer."""
    canvas = Image.new("RGB", (SIDE_W, SIDE_H), BG_DARK)
    draw = ImageDraw.Draw(canvas)

    # 1. Icon centered, ~38% of the side-panel height up from top.
    icon = _load_branded_icon()
    icon_size = 88
    icon_resized = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
    icon_x = (SIDE_W - icon_size) // 2
    icon_y = 38
    # Paste with alpha mask -- icon-branded already has the rounded yellow BG.
    canvas.paste(icon_resized, (icon_x, icon_y), icon_resized)

    # 2. Wordmark "Kira" -- large, white, centered, just below the icon.
    title_font = _try_load_font(32, bold=True)
    _draw_centered_text(draw, "Kira", icon_y + icon_size + 14, SIDE_W, title_font, TEXT_PRIMARY)

    # 3. Subtitle in a thinner weight, two lines if it doesn't fit.
    subtitle_font = _try_load_font(11)
    line1 = "Voice-to-Text"
    line2 = "mit KI-Polish"
    _draw_centered_text(draw, line1, icon_y + icon_size + 56, SIDE_W, subtitle_font, TEXT_SECONDARY)
    _draw_centered_text(draw, line2, icon_y + icon_size + 72, SIDE_W, subtitle_font, TEXT_SECONDARY)

    # 4. Footer "digitalroots" -- tertiary text, 14 px from the bottom.
    footer_font = _try_load_font(9)
    _draw_centered_text(draw, "digitalroots", SIDE_H - 22, SIDE_W, footer_font, TEXT_TERTIARY)

    # Drop alpha; Inno only ingests RGB BMPs.
    canvas.convert("RGB").save(out_path, "BMP")
    print(f"wrote {out_path} ({SIDE_W}x{SIDE_H} px, {out_path.stat().st_size:,} bytes)")


def build_small_image(out_path: Path) -> None:
    """55x58 px top-right tile: branded icon, centered, dark BG."""
    canvas = Image.new("RGB", (SMALL_W, SMALL_H), BG_DARK)

    icon = _load_branded_icon()
    # Leave 4 px padding so the rounded yellow plate doesn't kiss the edge.
    icon_size = min(SMALL_W, SMALL_H) - 8
    icon_resized = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
    icon_x = (SMALL_W - icon_size) // 2
    icon_y = (SMALL_H - icon_size) // 2
    canvas.paste(icon_resized, (icon_x, icon_y), icon_resized)

    canvas.convert("RGB").save(out_path, "BMP")
    print(f"wrote {out_path} ({SMALL_W}x{SMALL_H} px, {out_path.stat().st_size:,} bytes)")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    assets = repo_root / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    build_side_image(assets / "wizard-side.bmp")
    build_small_image(assets / "wizard-small.bmp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
