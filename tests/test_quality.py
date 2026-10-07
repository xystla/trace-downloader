import pytest
from trace_grabber.quality import pick_from_master, pick_from_urls

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1000000
video_1000k.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000
video_3000k.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2000000
video_2000k.m3u8
"""

def test_master_highest_picks_top_bandwidth():
    url = pick_from_master(MASTER, "https://x.com/a/game_video.m3u8", "highest")
    assert url == "https://x.com/a/video_3000k.m3u8"

def test_master_specific_bitrate():
    url = pick_from_master(MASTER, "https://x.com/a/game_video.m3u8", "2000k")
    assert url == "https://x.com/a/video_2000k.m3u8"

def test_pick_from_urls_specific():
    urls = ["https://x.com/video_1000k.m3u8", "https://x.com/video_3000k.m3u8"]
    assert pick_from_urls(urls, "3000k") == "https://x.com/video_3000k.m3u8"

def test_pick_from_urls_highest_by_bitrate_in_name():
    urls = ["https://x.com/video_1000k.m3u8", "https://x.com/video_3000k.m3u8"]
    assert pick_from_urls(urls, "highest") == "https://x.com/video_3000k.m3u8"

def test_specific_match_ignores_base_url():
    # "2000k" appears in the host but only video_1000k is a real variant;
    # matching must look at the filename, not the whole URL.
    urls = ["https://2000k.cdn.example.com/a/video_1000k.m3u8"]
    assert pick_from_urls(urls, "1000k") == urls[0]
    with pytest.raises(ValueError):
        pick_from_urls(urls, "2000k")

def test_pick_from_master_raises_when_missing():
    with pytest.raises(ValueError, match="not found"):
        pick_from_master(MASTER, "https://x.com/a/game_video.m3u8", "9000k")

def test_pick_from_urls_raises_when_missing():
    with pytest.raises(ValueError):
        pick_from_urls(["https://x.com/video_1000k.m3u8"], "9000k")


from trace_grabber.quality import pick_variant


def test_variant_comes_with_its_bandwidth():
    assert pick_variant(MASTER, "https://x.com/a/game_video.m3u8", "highest") == (
        "https://x.com/a/video_3000k.m3u8", 3000000)
    assert pick_variant(MASTER, "https://x.com/a/game_video.m3u8", "1000k") == (
        "https://x.com/a/video_1000k.m3u8", 1000000)


def test_variant_without_a_stated_bandwidth_reports_zero():
    master = "#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1280x720\nvideo_2000k.m3u8\n"
    assert pick_variant(master, "https://x.com/a/m.m3u8", "2000k") == ("https://x.com/a/video_2000k.m3u8", 0)


def test_variant_for_a_quality_trace_does_not_offer_is_an_error():
    with pytest.raises(ValueError):
        pick_variant(MASTER, "https://x.com/a/game_video.m3u8", "9000k")
