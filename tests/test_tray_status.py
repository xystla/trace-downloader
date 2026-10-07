from datetime import datetime

from gui.viewmodel import tray_status

NOW = datetime(2026, 10, 7, 15, 30)


def test_nothing_to_say_before_the_first_check():
    assert tray_status(NOW, None, False, False, None) == ""


def test_the_last_check_is_told_in_everyday_words():
    assert tray_status(NOW, None, False, False, (datetime(2026, 10, 7, 14, 14), 0)) == \
        "Last checked today at 2:14 PM · no new games"
    assert tray_status(NOW, None, False, False, (datetime(2026, 10, 7, 9, 5), 1)) == \
        "Last checked today at 9:05 AM · 1 new game saved"
    assert tray_status(NOW, None, False, False, (datetime(2026, 10, 6, 23, 0), 3)) == \
        "Last checked yesterday at 11:00 PM · 3 new games saved"
    assert tray_status(NOW, None, False, False, (datetime(2026, 10, 2, 12, 0), 0)) == \
        "Last checked Oct 2 at 12:00 PM · no new games"


def test_what_is_happening_now_comes_first():
    last = (datetime(2026, 10, 7, 14, 14), 0)
    assert tray_status(NOW, None, True, False, last) == "Checking for new games…"
    assert tray_status(NOW, ("vs Rovers", 42), True, False, last) == "Downloading vs Rovers · 42%"
    assert tray_status(NOW, ("vs Rovers", 0), False, False, None) == "Downloading vs Rovers · 0%"


def test_an_expired_login_is_said_plainly():
    assert tray_status(NOW, None, False, True, (datetime(2026, 10, 7, 14, 14), 0)) == \
        "Trace login expired · reconnect to keep downloading"
