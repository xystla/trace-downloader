import math

from trace_grabber import suggest

PLAYERS = 14


def spot(x, y):
    return {"l": [round(x), round(y)], "h": [0, 0]}


def lined_up():
    """Everyone in their place for a kick-off, standing."""
    return {str(p): spot(150 + 50 * p, 300 + 30 * (p % 5)) for p in range(PLAYERS)}


def playing(t):
    """Everyone on the move, in a band along the middle of the field."""
    return {str(p): spot(500 + 300 * math.sin(t / 3 + p), 500 + 150 * math.sin(t / 2 + 2 * p)) for p in range(PLAYERS)}


def walking_off():
    """Everyone strung out across the field, on their way to the side."""
    return {str(p): spot(400 + 10 * p, 120 + 55 * p) for p in range(PLAYERS)}


def nobody():
    return {"90": spot(500, 20), "91": spot(520, 980)}      # two people at the edges: the field is empty


def lingering():
    """After the game: some of them still standing about, across the field."""
    return {str(p): spot(450 + 10 * p, 150 + 80 * p) for p in range(9)}


def game(script, fps=2):
    """A tracking file from [(seconds, scene)], where a scene is a function of the
    time or a fixed set of people."""
    frames, t = [], 0.0
    for seconds, scene in script:
        for _ in range(int(seconds * fps)):
            frames.append({"t": round(t * 100), "a": scene(t) if callable(scene) and scene is playing else scene()})
            t += 1 / fps
    return {"setup": {"fps": fps, "athletes": {}}, "frm": frames}


def quarter(seconds):
    return [(20, lined_up), (seconds, playing), (10, walking_off)]


def kinds(found):
    return [m["kind"] for m in found]


def times(found):
    return [m["t"] for m in found]


def test_a_game_of_quarters_gets_its_start_its_breaks_and_its_end():
    # warm-up, then four quarters with the field empty between them
    script = [(40, playing)] + quarter(300) + [(60, nobody)] + quarter(300) + [(90, nobody)] \
        + quarter(300) + [(60, nobody)] + quarter(300) + [(60, nobody)]
    found = suggest.from_tracking([game(script)])
    assert kinds(found) == ["start", "break", "resume", "break", "resume", "break", "resume", "end"]
    kicks = [60, 450, 870, 1260]                     # when each quarter's play begins
    whistles = [360, 750, 1170, 1560]                # ... and when it stops
    for got, kick in zip(times(found)[0::2], kicks):
        assert kick - 15 <= got <= kick              # a start or restart: on the early side, and not by much
    for got, whistle in zip(times(found)[1::2], whistles):
        assert whistle <= got <= whistle + 15        # a break or the end: on the late side


def test_the_end_is_found_when_the_field_never_empties_after_it():
    script = [(30, playing)] + quarter(400) + [(120, lingering)]
    found = suggest.from_tracking([game(script)])
    assert kinds(found) == ["start", "end"]
    assert 450 <= found[1]["t"] <= 465


def test_the_earlier_of_two_moments_that_look_like_a_restart_is_the_one():
    script = quarter(300) + [(60, nobody)] + [(20, lined_up), (40, playing), (15, lined_up), (300, playing),
                                              (10, walking_off), (60, nobody)]
    found = suggest.from_tracking([game(script)])
    assert kinds(found) == ["start", "break", "resume", "end"]
    assert 395 <= found[2]["t"] <= 410               # the first time they stood and then all moved, not the second


def test_the_second_half_is_timed_from_the_end_of_the_first():
    first = game(quarter(300) + [(30, nobody)])
    second = game(quarter(300) + [(60, nobody)])
    alone = suggest.from_tracking([first, second])
    longer = suggest.from_tracking([first, second], first_half_length=400.0)
    assert kinds(alone) == ["start", "break", "resume", "end"]
    assert suggest.half_length(first) == 360.0
    # The first half's video ran 40 seconds past its tracking: the second half's marks are that much later.
    assert [b - a for a, b in zip(times(alone), times(longer))] == [0, 0, 40.0, 40.0]


def test_no_mark_is_put_past_the_end_of_the_video():
    script = quarter(300) + [(60, nobody)]           # the whistle goes at 320
    assert suggest.from_tracking([game(script)])[-1]["t"] > 321.0
    assert suggest.from_tracking([game(script)], length=321.0)[-1] == {"kind": "end", "t": 321.0}


def test_too_little_tracking_is_no_guess_at_all():
    assert suggest.from_tracking([]) == []
    assert suggest.from_tracking([{"frm": []}]) == []
    assert suggest.from_tracking([game([(600, nobody)])]) == []          # hardly anyone was ever tracked
    assert suggest.from_tracking([game([(20, playing)])]) == []          # a few seconds of it


def test_only_marks_that_make_a_game_are_kept_and_in_order():
    m = lambda kind, t: {"kind": kind, "t": float(t)}
    assert suggest._in_order([m("start", 10), m("break", 100), m("resume", 90), m("end", 300)]) == [m("start", 10)]
    assert suggest._in_order([m("break", 5), m("start", 10), m("end", 300)]) == [m("start", 10), m("end", 300)]
    # a break that play never came back from is not a break
    assert suggest._in_order([m("start", 10), m("break", 100)]) == [m("start", 10)]


def test_frames_without_a_time_are_timed_by_their_place_in_the_file():
    data = game(quarter(300) + [(60, nobody)])
    timed = suggest.from_tracking([data])
    for frame in data["frm"]:
        del frame["t"]
    assert suggest.from_tracking([data]) == timed and timed


def whistles(*found):
    """A `heard` that knows of these whistles, wherever it is asked to listen."""
    return lambda start, seconds: [w for w in found if start <= w[0] <= start + seconds]


HALF = quarter(300) + [(60, nobody)]          # lined up to 20, play to 320, walking off to 330


def test_a_whistle_heard_near_a_start_or_a_stop_settles_it():
    plain = suggest.from_tracking([game(HALF)])
    found = suggest.from_tracking([game(HALF)], heard=whistles((17.0, 17.4), (316.0, 317.5)))
    assert kinds(found) == kinds(plain) == ["start", "end"]
    assert times(found) == [16.0, 318.5]         # just before the whistle play starts on; just after the one it stops on
    assert times(plain) != times(found)


def test_the_first_whistle_starts_play_and_the_last_one_stops_it():
    found = suggest.from_tracking([game(HALF)], heard=whistles((10.0, 10.3), (17.0, 17.4), (312.0, 312.6), (316.0, 317.5)))
    assert times(found) == [9.0, 318.5]


def test_a_short_peep_does_not_end_a_half_and_a_far_off_whistle_settles_nothing():
    plain = suggest.from_tracking([game(HALF)])
    assert suggest.from_tracking([game(HALF)], heard=whistles((316.0, 316.15))) == plain      # a foul, not the end
    assert suggest.from_tracking([game(HALF)], heard=whistles((60.0, 60.5), (250.0, 252.0))) == plain


def test_a_video_with_no_sound_leaves_the_tracking_to_decide():
    plain = suggest.from_tracking([game(HALF)])
    assert suggest.from_tracking([game(HALF)], heard=lambda start, seconds: None) == plain
