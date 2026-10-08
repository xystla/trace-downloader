"""The score bug: a white clock box, then a dark bar with a strip of each team's
colour at its ends, their names, and the score in a white box. The bar is as
wide as the names need, and the boxes as wide as the chosen typeface's digits.

The app draws the "plate" (everything but the clock's digits) for a score; the
export overlays the plate and writes the digits, and the editor's preview shows
the same plate with the digits drawn by the page. Sizes are for a picture 1080
lines tall, before BIG and the edit's own size setting, and are scaled for
others."""
import math
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import paths

# The typefaces on offer (all under the SIL Open Font License): what the person
# sees, and the file. They live with the page, which uses the same files.
FONTS = {
    "barlow": ("Barlow Semi Condensed", "BarlowSemiCondensed-SemiBold.ttf"),
    "bebas": ("Bebas Neue", "BebasNeue-Regular.ttf"),
    "anton": ("Anton", "Anton-Regular.ttf"),
    "saira": ("Saira Condensed", "SairaCondensed-SemiBold.ttf"),
    "titillium": ("Titillium Web", "TitilliumWeb-SemiBold.ttf"),
    "poppins": ("Poppins", "Poppins-SemiBold.ttf"),
}
DEFAULT_FONT = "barlow"
SIZES = (0.5, 2.0)              # how far the size setting goes; 1.0 is the usual size
ORIGIN = (60, 48)               # where the plate's top-left sits in the picture
BIG = 1.25                      # the whole bug is drawn this much bigger than its measurements
HEIGHT = 46
GAP = 8                         # between the clock's box and the bar
STRIP_AT = 8                    # a team's colour strip starts this far in from the bar's end
STRIPS = (3, 40)                # how narrow and how wide a strip can be
ROUNDS = (0, 23)                # corners: square, up to the bug's ends being half circles
NAME, NAME_SIZE, NAME_PAD = 95, 28, 14      # a name's room (at least), its type size, the space at its sides
DIGIT_SIZE = 29                 # the score's digits and the clock's, alike
WHITE, INK = (255, 255, 255), (28, 18, 38)
USUAL = {"size": 1.0, "font": DEFAULT_FONT, "color": "#2d0a3c", "clock": 50, "strip": 7, "round": 10}
CLOCK_COLOR = "#1c1226"
_SMOOTH = 3                     # drawn this many times bigger, then shrunk, for smooth edges
_FINE = 8                       # type is measured this many times bigger, for fractions of a pixel


def font_path(font: str = DEFAULT_FONT) -> Path:
    """A typeface's file (the usual one's, for a name that isn't on offer)."""
    file = FONTS.get(font, FONTS[DEFAULT_FONT])[1]
    return paths.resource_dir() / "gui" / "web" / "fonts" / file


def style(bug) -> dict:
    """The edit's bug settings as the app keeps them, whatever was handed in."""
    bug = bug if isinstance(bug, dict) else {}
    size = bug.get("size")
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(size):
        size = 1.0
    font = bug.get("font")
    color = bug.get("color")

    def whole(key, low, high):
        value = bug.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return USUAL[key]
        return int(min(high, max(low, round(value))))

    return {"size": round(min(SIZES[1], max(SIZES[0], float(size))), 2),
            "font": font if isinstance(font, str) and font in FONTS else DEFAULT_FONT,
            "color": color.lower() if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) else USUAL["color"],
            "clock": whole("clock", 0, 100),            # how roomy the timer's box is: 0 tight, 100 wide
            "strip": whole("strip", *STRIPS), "round": whole("round", *ROUNDS)}


@lru_cache(maxsize=64)
def _face(font: str, pixels: int):
    return ImageFont.truetype(str(font_path(font)), max(1, pixels))


def _rgb(color: str) -> tuple:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _wide(font: str, size: int, words: str) -> float:
    return _face(font, size * _FINE).getlength(words) / _FINE


def _plan(home: dict, away: dict, bug: dict) -> dict:
    """Where the bug's parts sit, left to right, for these names and this look."""
    font, end = bug["font"], STRIP_AT + bug["strip"]
    # Room at the timer's sides: what was asked for, and more when the ends are round.
    pad = 2 + bug["clock"] / 5 + max(0, bug["round"] - 10) / 4
    digit = max(_wide(font, DIGIT_SIZE, d) for d in "0123456789")
    colon = _wide(font, DIGIT_SIZE, ":")
    # The clock's five glyphs (M M : S S) each have their own place, so the clock
    # doesn't shift sideways as the digits change width.
    steps = [digit / 2, digit + 1, digit / 2 + 1 + colon / 2, colon / 2 + 1 + digit / 2, digit + 1]
    clock = math.ceil(4 * digit + colon + 4 + 2 * pad)
    at, slots = (clock - (4 * digit + colon + 4)) / 2, []
    for step in steps:
        at += step
        slots.append(at)
    bar = clock + GAP
    side = 2 * digit + 8                                   # room for a score of two digits
    dash = 16
    score_wide = math.ceil(2 * side + dash + 8)
    home_room = max(NAME, math.ceil(_wide(font, NAME_SIZE, home["code"])) + 2 * NAME_PAD)
    away_room = max(NAME, math.ceil(_wide(font, NAME_SIZE, away["code"])) + 2 * NAME_PAD)
    score = bar + end + home_room
    return {"clock": clock, "slots": slots, "bar": bar, "home": bar + end + home_room / 2,
            "score": score, "score_wide": score_wide, "home_digit": score + 4 + side / 2,
            "dash": score + score_wide / 2, "away_digit": score + score_wide - 4 - side / 2,
            "away": score + score_wide + away_room / 2, "width": score + score_wide + away_room + end}


def _middle(face, glyph: str) -> float:
    """How far below the type's own middle line the middle of a glyph's ink is."""
    box = face.getbbox(glyph, anchor="mm")
    return (box[1] + box[3]) / 2


def size(home: dict, away: dict, scale: float = 1.0, bug=None) -> tuple:
    """The plate's width and height in the picture."""
    bug = style(bug)
    k = scale * BIG * bug["size"]
    return round(_plan(home, away, bug)["width"] * k), round(HEIGHT * k)


def render(home: dict, away: dict, home_score: int, away_score: int, scale: float = 1.0, bug=None) -> Image.Image:
    """The plate for a score: the whole bug except the clock's digits."""
    bug = style(bug)
    font = bug["font"]
    final = size(home, away, scale, bug)
    k = scale * BIG * bug["size"] * _SMOOTH
    plan = _plan(home, away, bug)
    width, score, mid = plan["width"], plan["score"], HEIGHT / 2
    bar, corner, strip = _rgb(bug["color"]), bug["round"], bug["strip"]
    light = (bar[0] * 299 + bar[1] * 587 + bar[2] * 114) / 1000 > 150
    names = INK if light else WHITE                    # whichever can be read on the bar
    # On a bar as pale as the score's box, the box is tinted so it still shows.
    score_fill = (232, 230, 236) if min(bar) > 225 else WHITE
    strip_corner = min(strip / 2, corner * 0.3)
    # Drawn exactly _SMOOTH times the final size, so nothing shifts when it is shrunk.
    plate = Image.new("RGBA", (final[0] * _SMOOTH, final[1] * _SMOOTH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)

    def box(x, y, w, h, radius, fill):
        draw.rounded_rectangle([x * k, y * k, (x + w) * k, (y + h) * k], radius=radius * k, fill=fill)

    def text(cx, words, type_size, fill, like):
        # Set by the middle of its ink (of 'like', so a word doesn't ride up and
        # down with its letters), which keeps every typeface in the middle of the bar.
        face = _face(font, round(type_size * k))
        draw.text((cx * k, mid * k - _middle(face, like)), words, font=face, fill=fill, anchor="mm")

    box(0, 0, plan["clock"], HEIGHT, corner, WHITE)                    # the clock's box
    box(plan["bar"], 0, width - plan["bar"], HEIGHT, corner, bar)
    box(plan["bar"] + STRIP_AT, 8, strip, HEIGHT - 16, strip_corner, _rgb(home["color"]))
    text(plan["home"], home["code"], NAME_SIZE, names, "H")
    box(score, 6, plan["score_wide"], HEIGHT - 12, min(17, corner * 0.7), score_fill)      # the score
    text(plan["home_digit"], str(home_score), DIGIT_SIZE, INK, "0")
    box(plan["dash"] - 4.5, mid - 1.6, 9, 3.2, 1, INK)                 # the dash, drawn: a typeface's own sits where it likes
    text(plan["away_digit"], str(away_score), DIGIT_SIZE, INK, "0")
    text(plan["away"], away["code"], NAME_SIZE, names, "H")
    box(width - STRIP_AT - strip, 8, strip, HEIGHT - 16, strip_corner, _rgb(away["color"]))
    return plate.resize(final, Image.LANCZOS)


def layout(scale: float = 1.0, home: dict | None = None, away: dict | None = None, bug=None) -> dict:
    """Where the plate goes in the picture and where the clock's digits go on
    the plate. Slots are the centre of each glyph, measured from the plate's
    left edge; y is the vertical centre of each glyph's ink, which is what the
    export sets; page_y is where the page puts the middle of each glyph's line
    to get the same."""
    bug = style(bug)
    blank = {"code": ""}
    home, away = home or blank, away or blank
    k = scale * BIG * bug["size"]
    plan = _plan(home, away, bug)
    width, height = size(home, away, scale, bug)
    type_size, y = round(DIGIT_SIZE * k), round(HEIGHT / 2 * k)
    face = _face(bug["font"], type_size)
    return {"x": round(ORIGIN[0] * scale), "y": round(ORIGIN[1] * scale), "width": width, "height": height,
            "font": bug["font"],
            "clock": {"slots": [round(x * k) for x in plan["slots"]], "y": y,
                      "page_y": [round(y - _middle(face, glyph), 1) for glyph in "00:00"],
                      "width": round(plan["clock"] * k), "size": type_size, "color": CLOCK_COLOR}}


def png_bytes(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
