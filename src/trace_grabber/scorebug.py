"""The score bug: a white clock box, then a dark bar with a strip of each team's
colour at its ends, their three-letter codes, and the score in a white box.

The app draws the "plate" (everything but the clock's digits) for a score; the
export overlays the plate and writes the digits, and the editor's preview shows
the same plate with the digits drawn by the page. Sizes are for a picture 1080
lines tall and are scaled for others."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import paths

FONT_FILE = "BarlowSemiCondensed-SemiBold.ttf"
ORIGIN = (60, 48)               # where the plate's top-left sits in the picture
WIDTH, HEIGHT = 418, 46
BAR_X = 100                     # the bar starts here, after the clock box and a gap
PURPLE, WHITE, INK = (45, 10, 60), (255, 255, 255), (28, 18, 38)
# The clock's five glyphs (M M : S S) each have their own place, so the clock
# doesn't shift sideways as the digits change width.
CLOCK = {"slots": [19, 35, 46, 57, 73], "y": 23, "size": 27, "color": "#1c1226"}
_SMOOTH = 3                     # drawn this many times bigger, then shrunk, for smooth edges


def font_path() -> Path:
    """The bug's typeface. It lives with the page, which uses the same file."""
    return paths.resource_dir() / "gui" / "web" / "fonts" / FONT_FILE


def _rgb(color: str) -> tuple:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def render(home: dict, away: dict, home_score: int, away_score: int, scale: float = 1.0) -> Image.Image:
    """The plate for a score: the whole bug except the clock's digits."""
    k = scale * _SMOOTH
    plate = Image.new("RGBA", (round(WIDTH * k), round(HEIGHT * k)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)

    def box(x, y, w, h, radius, fill):
        draw.rounded_rectangle([x * k, y * k, (x + w) * k, (y + h) * k], radius=radius * k, fill=fill)

    def text(cx, cy, words, size, fill):
        font = ImageFont.truetype(str(font_path()), max(1, round(size * k)))
        draw.text((cx * k, cy * k), words, font=font, fill=fill, anchor="mm")

    code_size = lambda code: 28 if len(code) <= 3 else 23              # four letters are set smaller, to fit
    box(0, 0, 92, HEIGHT, 10, WHITE)                                   # the clock's box
    box(BAR_X, 0, 318, HEIGHT, 10, PURPLE)
    box(BAR_X + 8, 8, 7, HEIGHT - 16, 3, _rgb(home["color"]))
    text(BAR_X + 62, 22, home["code"], code_size(home["code"]), WHITE)
    box(BAR_X + 110, 6, 98, HEIGHT - 12, 7, WHITE)                     # the score
    text(BAR_X + 135, 22, str(home_score), 29, INK)
    text(BAR_X + 159, 21, "-", 25, INK)
    text(BAR_X + 183, 22, str(away_score), 29, INK)
    text(BAR_X + 256, 22, away["code"], code_size(away["code"]), WHITE)
    box(BAR_X + 303, 8, 7, HEIGHT - 16, 3, _rgb(away["color"]))
    return plate.resize((round(WIDTH * scale), round(HEIGHT * scale)), Image.LANCZOS)


def layout(scale: float = 1.0) -> dict:
    """Where the plate goes in the picture and where the clock's digits go on
    the plate (slots are the centre of each glyph, measured from the plate's
    left edge; y is their vertical centre)."""
    s = lambda value: round(value * scale)
    return {"x": s(ORIGIN[0]), "y": s(ORIGIN[1]), "width": s(WIDTH), "height": s(HEIGHT),
            "clock": {"slots": [s(x) for x in CLOCK["slots"]], "y": s(CLOCK["y"]),
                      "size": s(CLOCK["size"]), "color": CLOCK["color"]}}


def png_bytes(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
