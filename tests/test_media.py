import urllib.error
import urllib.request

import pytest

from gui.media import MediaServer


@pytest.fixture
def server():
    s = MediaServer()
    yield s
    s.stop()


def _get(url, headers=None):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5)


def test_a_registered_video_plays_from_a_local_address(server, tmp_path):
    video = tmp_path / "Full Game" / "game one.mp4"
    video.parent.mkdir()
    video.write_bytes(bytes(range(256)) * 4)
    url = server.url_for(video)
    assert url.startswith("http://127.0.0.1:") and url.endswith(".mp4")
    resp = _get(url)
    assert resp.status == 200 and resp.read() == video.read_bytes()
    assert resp.headers["Content-Type"] == "video/mp4" and resp.headers["Accept-Ranges"] == "bytes"
    assert server.url_for(video) == url                         # the same file keeps its address


def test_scrubbing_asks_for_part_of_the_file_and_gets_just_that(server, tmp_path):
    video = tmp_path / "g.mp4"
    video.write_bytes(bytes(range(256)) * 4)                     # 1024 bytes
    url = server.url_for(video)
    middle = _get(url, {"Range": "bytes=100-199"})
    assert middle.status == 206 and middle.read() == video.read_bytes()[100:200]
    assert middle.headers["Content-Range"] == "bytes 100-199/1024"
    tail = _get(url, {"Range": "bytes=1000-"})
    assert tail.status == 206 and tail.read() == video.read_bytes()[1000:]
    last = _get(url, {"Range": "bytes=-24"})
    assert last.read() == video.read_bytes()[-24:]


def test_only_registered_files_are_served(server, tmp_path):
    video = tmp_path / "g.mp4"
    video.write_bytes(b"x")
    url = server.url_for(video)
    base = url.rsplit("/", 2)[0]
    for bad in (base + "/not-a-real-token/g.mp4", base + "/", url.rsplit("/", 1)[0] + "/../../etc/passwd"):
        with pytest.raises(urllib.error.HTTPError) as err:
            _get(bad)
        assert err.value.code == 404
    video.unlink()
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(url)                                               # the file was moved or deleted
    assert err.value.code == 404
