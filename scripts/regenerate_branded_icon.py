"""Generate assets/icon-branded.ico from assets/icon.ico.

Adds a yellow rounded-square background behind the existing logo so the
icon stays visible in the Windows 11 dark-mode tray and on dark Explorer
backgrounds. The source icon.ico (black logo, transparent background)
remains the single source of truth — branded.ico is a build artifact.

Run after the source logo changes:
    python scripts/regenerate_branded_icon.py

Then re-embed via scripts/embed_icon.ps1 to update kira.exe / kira-once.exe.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw

YELLOW = (255, 196, 0, 255)              # warm yellow, matches tray runtime
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
MASTER_SIZE = 256                         # we render once at 256 and let
                                          # Pillow scale down for the ICO.

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SRC = ASSETS / "icon.ico"
DST = ASSETS / "icon-branded.ico"


def _load_largest_logo(path: Path) -> Image.Image:
    """Return the highest-resolution frame from a multi-size ICO as RGBA.

    Pillow's ICO plugin exposes ``img.ico.sizes()`` and re-loads the
    chosen frame on ``img.size = (w, h)``; the type stubs don't model
    that, hence the ignores.
    """
    img = Image.open(path)
    ico = getattr(img, "ico", None)
    if ico is not None:
        try:
            sizes = sorted(ico.sizes(), key=lambda s: s[0] * s[1])
            img.size = sizes[-1]  # type: ignore[misc]
            img.load()
        except Exception:
            pass  # fall through to the default frame Pillow already loaded
    return img.convert("RGBA")


def _make_branded_master(logo: Image.Image, size: int) -> Image.Image:
    """Yellow rounded-square + centered logo at the given resolution.

    Padding (10%) and corner-radius (20%) are proportional so smaller
    sizes scale visually consistently.
    """
    padding = max(1, size // 10)
    radius = max(2, size // 5)

    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(bg).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=YELLOW,
    )

    inner = size - 2 * padding
    scaled_logo = logo.resize((inner, inner), Image.Resampling.LANCZOS)
    bg.alpha_composite(scaled_logo, (padding, padding))
    return bg


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Source icon not found: {SRC}")

    logo = _load_largest_logo(SRC)
    # Render JEDE Size eigenstaendig statt PIL's auto-downscale auf einen
    # Master-Frame. PIL's ICO-Save mit sizes=... hat einen Bug bei dem
    # die kleineren Frames (16x16, 32x32) faelschlich nur den 1. Pixel
    # des Master rendern → Icon erscheint schwarz im Datei-Explorer
    # bei kleinen Symbol-Sizes (Win11 Default).
    # Per-size rendering vermeidet Pillow's NEAREST-downscale-Bug
    # bei ICO mit alpha-graded edges (16x16-Frame wurde quasi
    # komplett transparent statt gelb).
    frames = [_make_branded_master(logo, w) for w, _h in ICO_SIZES]
    # ICO-Save: base = groesster Frame (Win11 nutzt 256x256 als
    # PNG-encoded), append_images = alle anderen native-Sizes.
    # KEIN sizes=... Parameter — der wuerde Pillow zwingen jeden
    # Frame neu zu downscalen statt sie 1:1 zu uebernehmen.
    sorted_frames = sorted(frames, key=lambda f: f.size[0], reverse=True)
    base = sorted_frames[0]
    base.save(
        DST,
        format="ICO",
        append_images=sorted_frames[1:],
    )

    size_kb = DST.stat().st_size / 1024
    print(f"OK {DST} ({size_kb:.1f} KB, {len(ICO_SIZES)} sizes, per-size rendered)")


if __name__ == "__main__":
    main()
