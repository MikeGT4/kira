# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tauscht das digitalroots-Logo in Kiras Bildern gegen die Patina-Fassung.

Quelle ist ausschließlich der Logo-Ordner (``--logo-dir``):
- assets/digitalroots-logo.png: 1:1 die Farbfassung (1001 × 188)
- assets/kira-splash.png und assets/readme-splash.jpg: bisheriges Bild, nur das
  Logo ersetzt. „digital“ stammt aus der weißen Datei, „roots“ und die
  Pixelmarke aus der Farbdatei; beide Dateien sind pixelgleich ausgerichtet.
  Freigabe Mike 22.09.2026.

Aufruf:
    python scripts/swap_logo.py --logo-dir <Ordner mit den Logo-Dateien>
"""
from __future__ import annotations
import argparse
from pathlib import Path
from PIL import Image
from PIL.PngImagePlugin import PngInfo

AUTHOR = "© 2026 Mike Pollow, Digitalroots"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
# Suchbereich des alten Logos als Anteil von Breite und Höhe (Logo unten mittig).
X_RANGE = (0.28, 0.73)
Y_RANGE = (0.80, 0.93)


def two_tone_logo(color: Image.Image, white: Image.Image) -> Image.Image:
    """Die fast schwarzen Pixel („digital“) kommen aus der weißen Datei."""
    out = color.copy()
    cp, wp, op = color.load(), white.load(), out.load()
    for y in range(color.height):
        for x in range(color.width):
            r, g, b, a = cp[x, y]
            if a and max(r, g, b) < 60:
                op[x, y] = wp[x, y]
    return out


def find_logo_box(img: Image.Image) -> tuple[int, int, int, int]:
    w, h = img.size
    px = img.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(round(h * Y_RANGE[0]), round(h * Y_RANGE[1])):
        for x in range(round(w * X_RANGE[0]), round(w * X_RANGE[1])):
            if max(px[x, y][:3]) > 55:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise SystemExit("kein Logo im Suchbereich gefunden")
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def replace_logo(img: Image.Image, box: tuple[int, int, int, int], logo: Image.Image) -> Image.Image:
    """Altes Logo mit Grund von links überdecken, neues proportional einsetzen."""
    height = box[3] - box[1]
    margin = max(8, round(height * 0.14))
    patch = (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
    shift = (patch[2] - patch[0]) + round(img.width * 0.05)
    out = img.copy()
    out.paste(img.crop((patch[0] - shift, patch[1], patch[2] - shift, patch[3])), (patch[0], patch[1]))
    visible = logo.crop(logo.getchannel("A").getbbox())
    scaled = visible.resize((round(visible.width * height / visible.height), height), Image.LANCZOS)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    out.alpha_composite(scaled, (round(cx - scaled.width / 2), round(cy - scaled.height / 2)))
    return out


def _save_png(img: Image.Image, path: Path) -> None:
    meta = PngInfo()
    meta.add_text("Author", AUTHOR)
    meta.add_text("Copyright", AUTHOR)
    img.save(path, pnginfo=meta)


def _save_jpeg(img: Image.Image, path: Path) -> None:
    # Exif-Text ist als ASCII deklariert; Pillow ersetzt ein "©" beim Schreiben
    # sonst stumm durch "?". Latin-1-Bytes halten das Zeichen (ein Byte, 0xA9)
    # und Pillow liest es beim Zurücklesen wieder korrekt als "©" ein.
    exif = Image.Exif()
    exif[0x013B] = AUTHOR.encode("latin-1")
    exif[0x8298] = AUTHOR.encode("latin-1")
    img.convert("RGB").save(path, quality=92, exif=exif)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logo-dir", type=Path, required=True)
    args = parser.parse_args()
    color_path = args.logo_dir / "digitalroots-logo-original.png"
    color = Image.open(color_path).convert("RGBA")
    white = Image.open(args.logo_dir / "digitalroots-logo-weiss-original.png").convert("RGBA")
    if color.size != white.size:
        raise SystemExit("Farb- und Weißfassung haben verschiedene Maße")
    _save_png(color, ASSETS / "digitalroots-logo.png")
    logo = two_tone_logo(color, white)
    splash = Image.open(ASSETS / "kira-splash.png").convert("RGBA")
    _save_png(replace_logo(splash, find_logo_box(splash), logo), ASSETS / "kira-splash.png")
    readme = Image.open(ASSETS / "readme-splash.jpg").convert("RGBA")
    _save_jpeg(replace_logo(readme, find_logo_box(readme), logo), ASSETS / "readme-splash.jpg")
    print("Logo getauscht: digitalroots-logo.png, kira-splash.png, readme-splash.jpg")


if __name__ == "__main__":
    main()
