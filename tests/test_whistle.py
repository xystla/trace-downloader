from trace_grabber import whistle

QUIET, VOICE, BLAST = 60, 150, 200


def column(whistle_hz=None, voices=0):
    """One 1/25 of a second of sound: quiet, with voices low down and perhaps a whistle."""
    c = [QUIET] * whistle.ROWS
    for r in range(whistle._row(600), whistle._row(2000)):
        c[r] = voices or QUIET + 10
    if whistle_hz:
        for r in range(whistle._row(whistle_hz - 200), whistle._row(whistle_hz + 200)):
            c[r] = BLAST
    return c


def sound(*parts):
    """Columns from (seconds, column) parts."""
    return [c for seconds, c in parts for _ in range(round(seconds * whistle.COLUMNS))]


def test_a_whistle_is_found_whatever_note_it_is():
    for hz in (2900, 3300, 3700, 4100):
        assert whistle.blasts(sound((4, column()), (0.4, column(hz)), (6, column()))) == [(4.0, 0.4)]


def test_a_whistle_is_heard_over_voices():
    found = whistle.blasts(sound((3, column(voices=VOICE)), (0.4, column(3600, voices=VOICE)), (3, column(voices=VOICE))))
    assert found == [(3.0, 0.4)]


def test_shouting_that_reaches_as_high_is_not_a_whistle():
    # As loud up there as a whistle, but far louder lower down: a voice.
    shout = column(3600, voices=255)
    assert whistle.blasts(sound((3, column()), (0.5, shout), (3, column()))) == []


def test_a_click_too_short_to_be_a_blast_is_passed_over():
    assert whistle.blasts(sound((3, column()), (0.08, column(3600)), (3, column()))) == []


def test_a_noise_that_never_stops_is_not_a_whistle():
    # A hum at whistle pitch the whole way through is what is usual there, not a signal.
    assert whistle.blasts(sound((10, column(3600)))) == []
    assert whistle.blasts([]) == []


def test_blasts_close_together_are_one_signal():
    found = [(4.0, 0.3), (4.8, 0.3), (5.6, 0.5), (20.0, 0.2)]
    assert whistle.signals(found, 100.0) == [(104.0, 106.1), (120.0, 120.2)]


def test_hearing_a_stretch_times_the_whistles_from_the_videos_start(monkeypatch):
    asked = []
    def picture(path, start, seconds):
        asked.append((path, start, seconds))
        return sound((2, column()), (0.4, column(3600)), (2, column()))
    monkeypatch.setattr(whistle, "picture", picture)
    assert whistle.heard("game.mp4", 300.0, 4.4) == [(302.0, 302.4)]
    # A stretch asked for from before the video starts is timed from its start.
    assert whistle.heard("game.mp4", -5.0, 4.4) == [(2.0, 2.4)]
    assert asked == [("game.mp4", 300.0, 4.4), ("game.mp4", -5.0, 4.4)]


def test_a_video_without_sound_has_nothing_to_hear(monkeypatch):
    monkeypatch.setattr(whistle, "picture", lambda path, start, seconds: None)
    assert whistle.heard("game.mp4", 0.0, 10.0) is None
