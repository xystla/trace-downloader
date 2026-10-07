from trace_grabber.progress import playlist_duration, parse_out_time, percent, parse_total_size

MEDIA = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXTINF:6.006,
seg0.ts
#EXTINF:6.006,
seg1.ts
#EXTINF:3.000,
seg2.ts
#EXT-X-ENDLIST
"""

def test_playlist_duration_sums_extinf():
    assert abs(playlist_duration(MEDIA) - 15.012) < 0.001

def test_parse_out_time():
    assert abs(parse_out_time("out_time=00:00:12.500000") - 12.5) < 0.001
    assert parse_out_time("frame=10") is None

def test_percent_clamped():
    assert percent(0, 100) == 0
    assert percent(50, 100) == 50
    assert percent(150, 100) == 100
    assert percent(5, 0) == 0

def test_parse_total_size():
    assert parse_total_size("total_size=1048576") == 1048576
    assert parse_total_size("out_time=00:00:01.0") is None


from trace_grabber.progress import Rate


def test_speed_is_measured_over_the_recent_window_only():
    rate = Rate(window=10)
    for second in range(0, 21):                    # 1 MB/s for twenty seconds…
        rate.add(second, second * 1_000_000)
    for second in range(21, 31):                   # …then 4 MB/s for ten
        rate.add(second, 20_000_000 + (second - 20) * 4_000_000)
    assert rate.bytes_per_sec() == 4_000_000


def test_time_left_is_what_remains_at_the_current_speed():
    rate = Rate()
    rate.add(0, 0)
    rate.add(4, 8_000_000)                         # 2 MB/s
    assert rate.eta(10_000_000) == 5


def test_no_time_left_is_given_before_there_is_enough_to_go_on():
    rate = Rate()
    assert rate.bytes_per_sec() == 0 and rate.eta(1_000) is None      # nothing measured
    rate.add(0, 0)
    rate.add(2, 4_000_000)
    assert rate.eta(1_000_000) is None                                # under three seconds


def test_a_stalled_download_gives_no_time_left():
    rate = Rate()
    rate.add(0, 5_000_000)
    rate.add(5, 5_000_000)
    assert rate.bytes_per_sec() == 0 and rate.eta(1_000_000) is None


def test_bytes_already_on_disk_do_not_count_as_speed():
    rate = Rate()
    rate.add(0, 900_000_000)                       # a resumed download starts here
    rate.add(5, 905_000_000)
    assert rate.bytes_per_sec() == 1_000_000
