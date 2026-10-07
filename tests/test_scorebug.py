from io import BytesIO

from PIL import Image, ImageChops

from trace_grabber import scorebug

HOME = {"code": "TIG", "color": "#16a05a"}
AWAY = {"code": "BLU", "color": "#1e5ac8"}


def _near(pixel, rgb, slack=12):
    return all(abs(pixel[i] - rgb[i]) <= slack for i in range(3))


def test_the_typeface_is_shipped_with_the_page():
    path = scorebug.font_path()
    assert path.name == "BarlowSemiCondensed-SemiBold.ttf" and path.parent.name == "fonts" and path.is_file()
    assert (path.parent / "OFL.txt").is_file()


def test_the_plate_is_the_bug_without_its_clock_digits():
    plate = scorebug.render(HOME, AWAY, 2, 1)
    assert plate.mode == "RGBA" and plate.size == (418, 46)
    assert _near(plate.getpixel((46, 23)), (255, 255, 255))            # the clock box, empty
    assert plate.getpixel((96, 23))[3] == 0                            # the gap between clock and bar
    assert _near(plate.getpixel((200, 4)), (45, 10, 60))               # the bar
    assert _near(plate.getpixel((111, 23)), (22, 160, 90))             # home strip
    assert _near(plate.getpixel((406, 23)), (30, 90, 200))             # away strip
    assert _near(plate.getpixel((213, 10)), (255, 255, 255))           # the score box


def test_the_score_changes_only_the_score_box():
    before, after = scorebug.render(HOME, AWAY, 0, 0), scorebug.render(HOME, AWAY, 1, 0)
    changed = ImageChops.difference(before.convert("RGB"), after.convert("RGB")).getbbox()
    assert changed is not None and 210 <= changed[0] and changed[2] <= 308


def test_codes_colours_and_big_scores_all_fit(tmp_path):
    wide = scorebug.render({"code": "WWWW", "color": "#ffffff"}, {"code": "MMMM", "color": "#000000"}, 12, 10)
    assert wide.size == (418, 46)
    box = wide.crop((211, 7, 307, 39)).convert("RGB")                  # just inside the score box
    assert ImageChops.difference(box, Image.new("RGB", box.size, (255, 255, 255))).getbbox() is not None
    # Nothing spills past it (sampled a few pixels clear of the box's own soft edge).
    assert _near(wide.getpixel((206, 23)), (45, 10, 60)) and _near(wide.getpixel((312, 23)), (45, 10, 60))


def test_the_bug_is_scaled_to_the_picture():
    assert scorebug.render(HOME, AWAY, 0, 0, scale=720 / 1080).size == (279, 31)
    small = scorebug.layout(720 / 1080)
    assert (small["x"], small["y"], small["width"], small["height"]) == (40, 32, 279, 31)
    full = scorebug.layout()
    assert (full["x"], full["y"], full["width"], full["height"]) == (60, 48, 418, 46)


def test_the_clock_digits_have_fixed_places_inside_the_white_box():
    clock = scorebug.layout()["clock"]
    assert len(clock["slots"]) == 5 and clock["slots"] == sorted(clock["slots"])
    assert 8 <= clock["slots"][0] and clock["slots"][-1] <= 84 and clock["slots"][2] == 46
    assert clock["y"] == 23 and clock["size"] == 27 and clock["color"] == "#1c1226"


def test_a_plate_can_be_handed_over_as_a_png():
    data = scorebug.png_bytes(scorebug.render(HOME, AWAY, 3, 3))
    assert data.startswith(b"\x89PNG") and Image.open(BytesIO(data)).size == (418, 46)
