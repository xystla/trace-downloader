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
    usual = {"size": 1.0, "font": "barlow", "color": "#2d0a3c", "clock": 50, "strip": 7, "round": 10, "timer": "left", "animate": True, "design": "classic", "color2": ""}
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
    corner = lambda plate, inset: plate.getpixel((plate.size[0] - 1 - inset, inset))[3]      # the bar's top right corner
    assert corner(square, 2) > 200 and corner(usual, 0) < 40 and corner(usual, 5) > 200 and corner(pill, 6) < 40
    assert square.getpixel((square.size[0] - 3, 55))[3] > 200 and pill.getpixel((pill.size[0] - 7, 51))[3] < 40
    left, right = _score_box(square)
    assert _near(square.getpixel((left + 1, 9)), (255, 255, 255))                    # the score box is square too
    for font in scorebug.FONTS:                                                       # the clock keeps clear of round ends
        lay = scorebug.layout(1.0, HOME, AWAY, {"font": font, "round": 23, "clock": 0})["clock"]
        wide = max(ImageFont.truetype(str(scorebug.font_path(font)), lay["size"]).getlength(d) for d in "0123456789")
        assert lay["slots"][0] - wide / 2 >= 6, font


def test_the_timer_box_is_as_tall_as_the_score_box():
    for bug in ({}, {"timer": "right"}, {"round": 0}, {"size": 1.6}):
        plate = scorebug.render(HOME, AWAY, 0, 0, bug=bug)
        clock = scorebug.layout(1.0, HOME, AWAY, bug)["clock"]
        left, right = _score_box(plate)
        rows = lambda x: [y for y in range(plate.size[1]) if plate.getpixel((x, y))[3] > 128 and _near(plate.getpixel((x, y)), (255, 255, 255))]
        timer, score = rows(clock["x"] + clock["width"] // 2), rows(left + 16)
        assert abs(timer[0] - score[0]) <= 1 and abs(timer[-1] - score[-1]) <= 1, bug
        assert timer[0] > 4 and plate.getpixel((clock["x"] + clock["width"] // 2, 1))[3] == 0, bug       # shorter than the bar


def test_the_timer_can_sit_on_the_right_of_the_bar():
    assert [scorebug.style({"timer": t})["timer"] for t in ("right", "left", "top", 3)] == ["right", "left", "left", "left"]
    left, right = scorebug.layout(1.0, HOME, AWAY), scorebug.layout(1.0, HOME, AWAY, {"timer": "right"})
    assert (right["width"], right["height"], right["x"], right["y"]) == (left["width"], left["height"], left["x"], left["y"])
    assert left["clock"]["x"] == 0 and right["clock"]["width"] == left["clock"]["width"]
    assert abs(right["clock"]["x"] - (right["width"] - right["clock"]["width"])) <= 1
    moved = right["clock"]["x"]
    assert all(abs(b - a - moved) <= 1 for a, b in zip(left["clock"]["slots"], right["clock"]["slots"]))
    plate = scorebug.render(HOME, AWAY, 0, 0, bug={"timer": "right"})
    assert plate.size == (left["width"], left["height"])
    assert _near(plate.getpixel((15, 29)), (22, 160, 90))                               # the bar starts the bug, home strip first
    assert _near(plate.getpixel((moved + 20, 29)), (255, 255, 255)) and plate.getpixel((moved + 20, 29))[3] > 200   # then the empty timer box
    assert plate.getpixel((moved - 5, 29))[3] == 0                                      # after a gap
    assert _near(plate.getpixel((moved - 25, 29)), (30, 90, 200))                       # which follows the away strip


def test_the_bug_slides_in_and_out_unless_asked_not_to():
    assert [scorebug.style({"animate": a})["animate"] for a in (False, True, None, "no", 0)] == [False, True, True, True, True]
    assert scorebug.layout()["slide"] == [0.6, 0.5] and scorebug.layout(1.0, HOME, AWAY, {"animate": False})["slide"] is None


def test_there_are_three_designs_to_choose_from():
    assert list(scorebug.DESIGNS) == ["classic", "slim", "blocks"] and all(scorebug.DESIGNS.values())
    assert [scorebug.style({"design": d})["design"] for d in ("slim", "blocks", "classic", "neon", 4)] == ["slim", "blocks", "classic", "classic", "classic"]


def test_every_design_draws_in_every_typeface_with_the_clock_in_its_place():
    for design in scorebug.DESIGNS:
        for font in scorebug.FONTS:
            for extra in ({}, {"timer": "right", "round": 23, "clock": 0, "strip": 30, "size": 1.4}):
                bug = {"design": design, "font": font, **extra}
                plate, lay = scorebug.render(HOME, AWAY, 12, 10, bug=bug), scorebug.layout(1.0, HOME, AWAY, bug)
                clock = lay["clock"]
                assert plate.size == (lay["width"], lay["height"]) == scorebug.size(HOME, AWAY, bug=bug), bug
                wide = max(ImageFont.truetype(str(scorebug.font_path(font)), clock["size"]).getlength(d) for d in "0123456789")
                assert clock["x"] <= clock["slots"][0] - wide / 2 and clock["slots"][4] + wide / 2 <= clock["x"] + clock["width"], bug
                # Where the digits go is one plain colour, top to bottom of their height: nothing else is drawn there.
                x, y = clock["slots"][1], clock["y"]
                under = [plate.getpixel((x, yy)) for yy in range(y - clock["size"] // 3, y + clock["size"] // 3)]
                assert all(p[3] > 250 and _near(p, under[0], slack=4) for p in under), bug
                # And the digits will show against it.
                ink = tuple(int(clock["color"][i:i + 2], 16) for i in (1, 3, 5))
                assert sum(abs(a - b) for a, b in zip(ink, under[0][:3])) > 300, bug


def test_the_slim_design_is_one_bar_with_the_timer_inside_and_the_names_underlined():
    bug = {"design": "slim"}
    plate, lay = scorebug.render(HOME, AWAY, 2, 1, bug=bug), scorebug.layout(1.0, HOME, AWAY, bug)
    clock = lay["clock"]
    assert lay["clock"]["color"] == "#ffffff"                                    # light digits on the dark bar
    for x in (clock["width"] // 2, clock["width"] + 4, plate.size[0] // 2):      # the bar runs under the timer and on, unbroken
        assert _near(plate.getpixel((x, 4)), (45, 10, 60)) and plate.getpixel((x, 4))[3] > 250
    row = [plate.getpixel((x, 50)) for x in range(plate.size[0])] + [plate.getpixel((x, 49)) for x in range(plate.size[0])]
    assert sum(_near(p, (22, 160, 90)) for p in row) > 20 and sum(_near(p, (30, 90, 200)) for p in row) > 20     # a line of each team's colour
    assert not any(_near(plate.getpixel((x, 29)), (22, 160, 90)) for x in range(plate.size[0]))                 # and no strips at the ends
    assert _ink(plate, (0, 10, plate.size[0], 48), dark=False) is not None       # the score is written light, with no box
    whites = sum(_near(plate.getpixel((x, 12)), (255, 255, 255)) for x in range(plate.size[0]))
    assert whites < 12
    pale = scorebug.layout(1.0, HOME, AWAY, {"design": "slim", "color": "#f2e9c8"})
    assert pale["clock"]["color"] == "#1c1226"                                   # dark digits on a light bar


def test_the_blocks_design_fills_each_side_with_its_team_colour():
    bug = {"design": "blocks"}
    plate, lay = scorebug.render(HOME, AWAY, 2, 1, bug=bug), scorebug.layout(1.0, HOME, AWAY, bug)
    start = lay["clock"]["width"] + 10                                           # the bar begins after the timer and its gap
    assert _near(plate.getpixel((start + 8, 29)), (22, 160, 90)) and _near(plate.getpixel((start + 8, 6)), (22, 160, 90))
    assert _near(plate.getpixel((plate.size[0] - 8, 29)), (30, 90, 200))
    assert plate.getpixel((start - 5, 29))[3] == 0 and _near(plate.getpixel((lay["clock"]["width"] // 2, 12)), (255, 255, 255))
    plan = scorebug._plan(HOME, AWAY, scorebug.style(bug))
    middle = round((plan["score"] + plan["score_wide"] / 2) * scorebug.BIG)
    assert _near(plate.getpixel((middle, 11)), (45, 10, 60))                     # the score sits in a box of the bug's own colour
    left = round(plan["score"] * scorebug.BIG)
    assert _ink(plate, (left + 6, 12, left + 50, 46), dark=False) is not None    # written light
    # A pale team colour gets dark letters.
    pale = scorebug.render({"code": "TIG", "color": "#ffe9a8"}, AWAY, 0, 0, bug=bug)
    assert _ink(pale, (start + 20, 12, left - 10, 46)) is not None
    # More of the strip setting means more solid colour before it fades toward the middle.
    far = round((plan["bar"] + (plan["score"] - plan["bar"]) * 0.8) * scorebug.BIG)
    soft, solid = plate.getpixel((far, 5)), scorebug.render(HOME, AWAY, 2, 1, bug={**bug, "strip": 40}).getpixel((far, 5))
    assert _near(solid, (22, 160, 90)) and not _near(soft, (22, 160, 90))


def test_the_bar_can_fade_from_one_colour_to_another():
    assert [scorebug.style({"color2": c})["color2"] for c in ("#FF5500", "", "orange", None, 5)] == ["#ff5500", "", "", "", ""]
    for design in scorebug.DESIGNS:
        bug = {"design": design, "color": "#000080", "color2": "#c00000", "timer": "right"}      # navy to red, bar first
        plate, lay = scorebug.render(HOME, AWAY, 0, 0, bug=bug), scorebug.layout(1.0, HOME, AWAY, bug)
        end = lay["clock"]["x"] - 12 if design != "slim" else plate.size[0] - 1                   # where the bar stops
        colour_at = lambda frac: plate.getpixel((round(end * frac), 3))
        if design != "blocks":                                                                    # (blocks start and end in team colours)
            assert _near(colour_at(0.1), (0, 0, 128), slack=40) and _near(colour_at(0.9), (192, 0, 0), slack=40), design
            assert colour_at(0.1)[2] > colour_at(0.5)[2] > colour_at(0.9)[2] and colour_at(0.1)[0] < colour_at(0.5)[0] < colour_at(0.9)[0], design
        mid = colour_at(0.5) if design != "blocks" else plate.getpixel((round((scorebug._plan(HOME, AWAY, scorebug.style(bug))["dash"]) * scorebug.BIG), 3))
        assert 30 < mid[0] < 170 and 20 < mid[2] < 110 and mid[1] < 20, design                    # between the two in the middle
        assert plate.size == (lay["width"], lay["height"]), design
    assert scorebug.render(HOME, AWAY, 0, 0, bug={"color2": ""}).tobytes() == scorebug.render(HOME, AWAY, 0, 0).tobytes()
    # Names are read against the two colours together: dark on a pale fade.
    pale = scorebug.render(HOME, AWAY, 0, 0, bug={"color": "#fff6c8", "color2": "#c8f0ff"})
    left, _ = _score_box(pale) if False else (round(scorebug._plan(HOME, AWAY, scorebug.style(None))["score"] * scorebug.BIG), 0)
    assert _ink(pale, (left - 100, 12, left - 20, 46)) is not None
    assert scorebug.layout(1.0, HOME, AWAY, {"design": "slim", "color": "#fff6c8", "color2": "#c8f0ff"})["clock"]["color"] == "#1c1226"


def test_a_plate_can_be_handed_over_as_a_png():
    data = scorebug.png_bytes(scorebug.render(HOME, AWAY, 3, 3))
    assert data.startswith(b"\x89PNG") and Image.open(BytesIO(data)).size == scorebug.size(HOME, AWAY)
