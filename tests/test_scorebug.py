from io import BytesIO

from PIL import Image, ImageChops, ImageFont

from trace_grabber import scorebug

HOME = {"code": "TIG", "color": "#16a05a"}
AWAY = {"code": "BLU", "color": "#1e5ac8"}


def _near(pixel, rgb, slack=12):
    return all(abs(pixel[i] - rgb[i]) <= slack for i in range(3))


def test_the_typeface_is_shipped_with_the_page():
    path = scorebug.font_path()
    assert path.name == "BarlowSemiCondensed-SemiBold.ttf" and path.parent.name == "fonts" and path.is_file()
    assert (path.parent / "OFL.txt").is_file()


def test_every_typeface_on_offer_is_shipped_with_its_licence():
    assert list(scorebug.FONTS)[0] == scorebug.DEFAULT_FONT == "barlow" and len(scorebug.FONTS) == 6
    for key, (label, file) in scorebug.FONTS.items():
        assert label and scorebug.font_path(key).name == file and scorebug.font_path(key).is_file()
    assert scorebug.font_path("no such font") == scorebug.font_path()
    assert len(list(scorebug.font_path().parent.glob("OFL*.txt"))) == 6


def test_a_bug_style_is_tidied():
    usual = {"size": 1.0, "font": "barlow", "color": "#2d0a3c", "clock": 50, "strip": 7, "round": 10}
    assert scorebug.style(None) == usual == scorebug.style("junk")
    assert scorebug.style({"size": 1.4, "font": "anton"}) == {**usual, "size": 1.4, "font": "anton"}
    assert scorebug.style({"size": 9, "font": "comic"}) == {**usual, "size": 2.0}
    mine = scorebug.style({"color": "#0A2A5C", "clock": 0, "strip": 30})
    assert (mine["color"], mine["clock"], mine["strip"]) == ("#0a2a5c", 0, 30)
    wild = scorebug.style({"color": "navy", "clock": 900, "strip": -3})
    assert (wild["color"], wild["clock"], wild["strip"]) == ("#2d0a3c", 100, 3)
    assert scorebug.style({"clock": "x", "strip": True, "color": 7}) == usual and scorebug.style({"strip": 999})["strip"] == 40
    assert [scorebug.style({"round": r})["round"] for r in (0, 23, 99, -1, "x")] == [0, 23, 23, 0, 10]
    assert scorebug.style({"size": 0.1})["size"] == 0.5 and scorebug.style({"size": "big"})["size"] == 1.0
    assert scorebug.style({"size": True})["size"] == 1.0 and scorebug.style({"size": float("nan")})["size"] == 1.0


def _ink(image, box, dark=True):
    """The bounding box of the dark (or light) marks inside a part of a plate."""
    part = image.crop(box).convert("L").point(lambda v: 255 if (v < 110 if dark else v > 200) else 0)
    found = part.getbbox()
    return found and (found[0] + box[0], found[1] + box[1], found[2] + box[0], found[3] + box[1])


def _score_box(plate):
    """The white score box, found by looking: (left, right) on the middle line."""
    mid = plate.size[1] // 2
    clock_end = next(x for x in range(plate.size[0]) if plate.getpixel((x, mid))[3] == 0)
    row = round(plate.size[1] * 12 / 58)                               # above the digits and names, inside the box
    whites = [x for x in range(clock_end, plate.size[0])
              if plate.getpixel((x, row))[3] > 200 and _near(plate.getpixel((x, row)), (255, 255, 255))]
    return whites[0], whites[-1] + 1




def test_the_plate_is_the_bug_without_its_clock_digits():
    plate = scorebug.render(HOME, AWAY, 2, 1)
    wide, tall = plate.size
    lay = scorebug.layout(1.0, HOME, AWAY)
    assert plate.mode == "RGBA" and (wide, tall) == scorebug.size(HOME, AWAY) == (lay["width"], lay["height"])
    assert tall == 58 and 515 <= wide <= 540
    assert _near(plate.getpixel((57, 29)), (255, 255, 255))            # the clock box, empty
    gap = lay["clock"]["width"] + 5
    assert plate.getpixel((gap, 29))[3] == 0                           # the gap between clock and bar
    assert _near(plate.getpixel((gap + 19, 29)), (22, 160, 90))        # home strip
    assert _near(plate.getpixel((wide - 15, 29)), (30, 90, 200))       # away strip
    left, right = _score_box(plate)
    assert _near(plate.getpixel((left - 20, 5)), (45, 10, 60))         # the bar
    assert 110 <= right - left <= 140


def test_the_score_changes_only_the_score_box():
    before, after = scorebug.render(HOME, AWAY, 0, 0), scorebug.render(HOME, AWAY, 1, 0)
    changed = ImageChops.difference(before.convert("RGB"), after.convert("RGB")).getbbox()
    left, right = _score_box(before)
    assert changed is not None and left <= changed[0] and changed[2] <= right


def test_big_scores_fit_in_the_score_box_in_every_typeface():
    for font in scorebug.FONTS:
        bug = {"font": font}
        plate = scorebug.render({"code": "WWW", "color": "#16a05a"}, {"code": "MMM", "color": "#1e5ac8"}, 88, 88, bug=bug)
        left, right = _score_box(plate)
        marks = _ink(plate, (left + 4, 10, right - 4, 48))
        assert marks and marks[0] > left + 4 and marks[2] < right - 4 and marks[1] > 10 and marks[3] < 48, font
        assert abs((marks[1] + marks[3]) / 2 - plate.size[1] / 2) <= 1.5, font       # the digits sit in the middle


def test_a_long_name_makes_the_bug_wider_instead_of_being_squeezed():
    long_home = {"code": "TIGER SHARKS UNITED", "color": "#16a05a"}
    short, wide = scorebug.render(HOME, AWAY, 0, 0), scorebug.render(long_home, AWAY, 0, 0)
    assert wide.size[1] == short.size[1] and wide.size[0] > short.size[0] + 150
    assert wide.size == scorebug.size(long_home, AWAY)
    strip = scorebug.layout()["clock"]["width"] + 24
    assert _near(wide.getpixel((strip, 29)), (22, 160, 90))            # the strips stay at the ends
    assert _near(wide.getpixel((wide.size[0] - 15, 29)), (30, 90, 200))
    # The name stays clear of its strip and of the score box, which has moved along.
    left, _ = _score_box(wide)
    assert left > _score_box(short)[0] + 150
    for x in (strip + 11, left - 8):
        assert all(_near(wide.getpixel((x, y)), (45, 10, 60)) for y in range(4, 54))
    # A long name on the other side leaves the clock, home side and score where they were.
    long_away = scorebug.render(HOME, {"code": "BLUE DRAGONS", "color": "#1e5ac8"}, 0, 0)
    upto = _score_box(short)[1]
    same = ImageChops.difference(long_away.crop((0, 0, upto, 58)), short.crop((0, 0, upto, 58)))
    assert long_away.size[0] > short.size[0] and max(high for _, high in same.getextrema()) <= 8


def test_the_bug_is_scaled_to_the_picture():
    full, small = scorebug.layout(1.0, HOME, AWAY), scorebug.layout(720 / 1080, HOME, AWAY)
    assert (full["x"], full["y"], full["height"]) == (60, 48, 58) and full["width"] == scorebug.size(HOME, AWAY)[0]
    assert (small["x"], small["y"], small["height"]) == (40, 32, 38)
    assert scorebug.render(HOME, AWAY, 0, 0, scale=720 / 1080).size == (small["width"], small["height"])
    assert abs(small["width"] - full["width"] * 2 / 3) <= 1


def test_the_size_setting_scales_the_whole_bug_from_its_corner():
    big, usual = scorebug.layout(1.0, HOME, AWAY, {"size": 1.5}), scorebug.layout(1.0, HOME, AWAY)
    assert (big["x"], big["y"]) == (usual["x"], usual["y"]) == (60, 48)
    assert big["height"] == 86 and abs(big["width"] - usual["width"] * 1.5) <= 1
    assert abs(big["clock"]["size"] - usual["clock"]["size"] * 1.5) <= 1
    assert scorebug.render(HOME, AWAY, 0, 0, bug={"size": 1.5}).size == (big["width"], big["height"])
    assert scorebug.layout(1.0, HOME, AWAY, {"size": 0.5})["height"] == 29


def test_the_clock_digits_have_fixed_places_inside_the_white_box_in_every_typeface():
    for font in scorebug.FONTS:
        lay = scorebug.layout(1.0, HOME, AWAY, {"font": font})
        clock = lay["clock"]
        slots = clock["slots"]
        assert lay["font"] == font and len(slots) == 5 and slots == sorted(slots), font
        assert clock["y"] == 29 and clock["color"] == "#1c1226" and len(clock["page_y"]) == 5
        # Each digit has room: the slots are at least a digit apart and stay inside the box.
        wide = max(ImageFont.truetype(str(scorebug.font_path(font)), clock["size"]).getlength(d) for d in "0123456789")
        assert slots[1] - slots[0] >= wide and slots[4] - slots[3] >= wide, font
        assert slots[0] - wide / 2 >= 8 and slots[4] + wide / 2 <= clock["width"] - 8, font
        assert abs((slots[0] + slots[4]) / 2 - clock["width"] / 2) <= 1.5, font
        plate = scorebug.render(HOME, AWAY, 0, 0, bug={"font": font})
        assert _near(plate.getpixel((clock["width"] - 6, 29)), (255, 255, 255)) and plate.getpixel((clock["width"] + 4, 29))[3] == 0


def test_the_clock_is_set_as_big_as_the_score():
    for font in scorebug.FONTS:
        plate = scorebug.render(HOME, AWAY, 0, 0, bug={"font": font})
        left, right = _score_box(plate)
        score_zero = _ink(plate, (left + 4, 10, (left + right) // 2 - 8, 48))
        size = scorebug.layout(1.0, HOME, AWAY, {"font": font})["clock"]["size"]
        zero = ImageFont.truetype(str(scorebug.font_path(font)), size).getbbox("0")
        assert abs((score_zero[3] - score_zero[1]) - (zero[3] - zero[1])) <= 2, font


def test_the_timer_box_can_be_made_smaller_or_roomier():
    for font in scorebug.FONTS:
        tight = scorebug.layout(1.0, HOME, AWAY, {"font": font, "clock": 0})["clock"]
        usual = scorebug.layout(1.0, HOME, AWAY, {"font": font})["clock"]
        roomy = scorebug.layout(1.0, HOME, AWAY, {"font": font, "clock": 100})["clock"]
        assert tight["width"] < usual["width"] - 15 and roomy["width"] > usual["width"] + 15, font
        wide = max(ImageFont.truetype(str(scorebug.font_path(font)), tight["size"]).getlength(d) for d in "0123456789")
        assert tight["slots"][0] - wide / 2 >= 2 and tight["slots"][4] + wide / 2 <= tight["width"] - 2, font   # digits still inside
        assert abs((tight["slots"][0] + tight["slots"][4]) / 2 - tight["width"] / 2) <= 1.5, font
    small, usual = scorebug.size(HOME, AWAY, bug={"clock": 0}), scorebug.size(HOME, AWAY)
    assert small[0] < usual[0] - 15 and small[1] == usual[1]            # the bar moves up beside it


def test_the_bar_takes_the_colour_you_give_it_and_keeps_its_names_readable():
    navy = scorebug.render(HOME, AWAY, 0, 0, bug={"color": "#0a2a5c"})
    left, _ = _score_box(navy)
    assert _near(navy.getpixel((left - 20, 5)), (10, 42, 92))
    assert _ink(navy, (left - 110, 12, left - 22, 46), dark=False) is not None       # white names on a dark bar
    pale = scorebug.render(HOME, AWAY, 0, 0, bug={"color": "#f2e9c8"})
    assert _near(pale.getpixel((left - 20, 5)), (242, 233, 200))
    assert _ink(pale, (left - 110, 12, left - 22, 46)) is not None                   # dark names on a light bar
    # The score box stands out from a white bar too.
    white = scorebug.render(HOME, AWAY, 0, 0, bug={"color": "#ffffff"})
    assert not _near(white.getpixel((left + 6, 12)), (255, 255, 255), slack=6)


def test_the_team_colour_strips_can_be_made_wider():
    usual, wide = scorebug.render(HOME, AWAY, 0, 0), scorebug.render(HOME, AWAY, 0, 0, bug={"strip": 30})
    assert wide.size[0] - usual.size[0] in (57, 58) and wide.size[1] == usual.size[1]     # 23 more each side, at 1.25
    start = scorebug.layout()["clock"]["width"] + 21
    green = lambda plate: sum(_near(plate.getpixel((x, 29)), (22, 160, 90)) for x in range(start - 6, start + 60))
    blue = lambda plate: sum(_near(plate.getpixel((x, 29)), (30, 90, 200)) for x in range(plate.size[0] - 60, plate.size[0]))
    assert 7 <= green(usual) <= 10 and 36 <= green(wide) <= 39 and 7 <= blue(usual) <= 10 and 36 <= blue(wide) <= 39
    # The name has moved along, clear of the wider strip.
    assert all(_near(wide.getpixel((start + 44, y)), (45, 10, 60)) for y in range(4, 54))


def test_the_corners_go_from_square_to_fully_round():
    square, usual, pill = (scorebug.render(HOME, AWAY, 0, 0, bug={"round": r}) for r in (0, 10, 23))
    assert square.size == usual.size and pill.size[1] == usual.size[1]
    corner = lambda plate, inset: plate.getpixel((inset, inset))[3]
    assert corner(square, 0) > 200 and corner(usual, 0) < 40 and corner(usual, 5) > 200 and corner(pill, 6) < 40
    assert square.getpixel((square.size[0] - 3, 55))[3] > 200 and pill.getpixel((pill.size[0] - 7, 51))[3] < 40
    left, right = _score_box(square)
    assert _near(square.getpixel((left + 1, 9)), (255, 255, 255))                    # the score box is square too
    for font in scorebug.FONTS:                                                       # the clock keeps clear of round ends
        lay = scorebug.layout(1.0, HOME, AWAY, {"font": font, "round": 23, "clock": 0})["clock"]
        wide = max(ImageFont.truetype(str(scorebug.font_path(font)), lay["size"]).getlength(d) for d in "0123456789")
        assert lay["slots"][0] - wide / 2 >= 6, font


def test_a_plate_can_be_handed_over_as_a_png():
    data = scorebug.png_bytes(scorebug.render(HOME, AWAY, 3, 3))
    assert data.startswith(b"\x89PNG") and Image.open(BytesIO(data)).size == scorebug.size(HOME, AWAY)
