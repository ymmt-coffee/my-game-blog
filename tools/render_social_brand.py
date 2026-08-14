"""FRAMINGのX用ブランド画像をPNGへ書き出す。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "brand" / "social"
FONT = Path(r"C:\Windows\Fonts\NotoSansJP-VF.ttf")
INK, GRID, LINE, PAPER = "#171717", "#303030", "#747474", "#F7F7F5"


def corner_frame(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], length: int, width: int) -> None:
    left, top, right, bottom = box
    segments = (
        ((left, top + length), (left, top), (left + length, top)),
        ((right - length, top), (right, top), (right, top + length)),
        ((right, bottom - length), (right, bottom), (right - length, bottom)),
        ((left + length, bottom), (left, bottom), (left, bottom - length)),
    )
    for points in segments:
        draw.line(points, fill=LINE, width=width, joint="curve")


def draw_spaced_text(
    draw: ImageDraw.ImageDraw, center: tuple[int, int], text: str,
    font: ImageFont.FreeTypeFont, spacing: int,
) -> None:
    widths = [draw.textlength(char, font=font) for char in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x, y = center[0] - total / 2, center[1]
    for char, width in zip(text, widths):
        draw.text((x, y), char, font=font, fill=PAPER, anchor="lm")
        x += width + spacing


def render_icon() -> None:
    image = Image.new("RGB", (800, 800), INK)
    draw = ImageDraw.Draw(image)
    draw.line((142, 400, 658, 400), fill=GRID, width=2)
    draw.line((400, 142, 400, 658), fill=GRID, width=2)
    corner_frame(draw, (170, 170, 630, 630), 110, 8)
    font = ImageFont.truetype(FONT, 340)
    draw.text((400, 398), "F", font=font, fill=PAPER, anchor="mm", stroke_width=0)
    image.save(OUTPUT / "framing-x-icon.png", optimize=True)


def render_header() -> None:
    image = Image.new("RGB", (1500, 500), INK)
    draw = ImageDraw.Draw(image)
    for y in (125, 375):
        draw.line((0, y, 1500, y), fill="#2D2D2D", width=2)
    for x in (500, 1000):
        draw.line((x, 0, x, 500), fill="#2D2D2D", width=2)
    corner_frame(draw, (430, 100, 1070, 400), 55, 4)
    font = ImageFont.truetype(FONT, 88)
    draw_spaced_text(draw, (750, 250), "FRAMING", font, 14)
    image.save(OUTPUT / "framing-x-header.png", optimize=True)


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    render_icon()
    render_header()
