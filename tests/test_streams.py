from trace_grabber.streams import master_url, resolve_prefix, available_masters, prefix_from_html

def test_prefix_from_html_qaapi():
    html = ('<a href="/us-east-2/soccer/qaapi/teams/demoteam1/games/'
            'demoteam1-1002/gamevideo1.hls/game_video.m3u8">')
    assert prefix_from_html(html, "demoteam1", "demoteam1-1002") == "us-east-2/soccer/qaapi"

def test_prefix_from_html_plain_api():
    html = '"video":"/api/teams/t/games/t-9/gamevideo2.hls/game_video.m3u8"'
    assert prefix_from_html(html, "t", "t-9") == "api"

def test_prefix_from_html_none():
    assert prefix_from_html("<html>nothing here</html>", "t", "t-9") is None

def test_master_url_shape():
    url = master_url("demoteam1", "demoteam1-1001", 1)
    assert url == (
        "https://go.traceup.com/api/teams/demoteam1/games/"
        "demoteam1-1001/gamevideo1.hls/game_video.m3u8"
    )

def test_master_url_second_half():
    assert master_url("t", "t-9", 2).endswith("/gamevideo2.hls/game_video.m3u8")

def test_master_url_old_prefix():
    url = master_url("t", "t-9", 1, prefix="us-east-2/soccer/api")
    assert url.startswith("https://go.traceup.com/us-east-2/soccer/api/teams/")

class _Resp:
    def __init__(self, ok): self.ok = ok

class _Req:
    """ok if any of the given substrings is in the requested URL."""
    def __init__(self, ok_substrings): self.ok = ok_substrings
    def get(self, url, timeout=0): return _Resp(any(s in url for s in self.ok))

def test_resolve_prefix_new_api():
    # Anchor on the host so the substring can't also match the regioned
    # ".../soccer/api/teams/" prefixes, which are tried first.
    assert resolve_prefix(_Req(["traceup.com/api/teams/"]), "t", "t-9") == "api"

def test_resolve_prefix_old_soccer():
    assert resolve_prefix(_Req(["/us-east-2/soccer/api/"]), "t", "t-9") == "us-east-2/soccer/api"

def test_resolve_prefix_qaapi():
    assert resolve_prefix(_Req(["/us-east-2/soccer/qaapi/"]), "t", "t-9") == "us-east-2/soccer/qaapi"

def test_resolve_prefix_us_west_api():
    # Games migrated to us-west-2 (Oct 2026); the old us-east-2 prefixes 403.
    assert resolve_prefix(_Req(["/us-west-2/soccer/api/"]), "t", "t-9") == "us-west-2/soccer/api"

def test_resolve_prefix_us_west_qaapi():
    assert resolve_prefix(_Req(["/us-west-2/soccer/qaapi/"]), "t", "t-9") == "us-west-2/soccer/qaapi"

def test_resolve_prefix_none():
    assert resolve_prefix(_Req([]), "t", "t-9") is None

def test_available_masters_both_new():
    masters = available_masters(_Req(["/api/teams/"]), "t", "t-9")
    assert len(masters) == 2 and all("/api/teams/" in m for m in masters)

def test_available_masters_old_prefix():
    masters = available_masters(_Req(["/us-east-2/soccer/api/"]), "t", "t-9")
    assert len(masters) == 2 and all("/us-east-2/soccer/api/" in m for m in masters)

def test_available_masters_none():
    assert available_masters(_Req([]), "t", "t-9") == []

class _Page:
    """Minimal fake Playwright page for fallback tests."""
    def __init__(self, html=""): self._html = html; self.url = ""
    def goto(self, *a, **k): self.url = "https://go.traceup.com/traceid/athlete/X/watch/9/items/"
    def wait_for_selector(self, *a, **k): pass
    def wait_for_timeout(self, *a, **k): pass
    def click(self, *a, **k): pass
    def content(self): return self._html

def test_resolve_masters_fast_path():
    from trace_grabber.streams import resolve_masters
    masters = resolve_masters(_Req(["/api/teams/"]), _Page(), lambda: "X", "t", "t-9")
    assert len(masters) == 2 and all("/api/teams/" in m for m in masters)

def test_resolve_masters_fallback_unknown_prefix():
    from trace_grabber.streams import resolve_masters
    html = 'x="/future/newpath/teams/t/games/t-9/gamevideo1.hls/game_video.m3u8"'
    masters = resolve_masters(_Req(["/future/newpath/"]), _Page(html), lambda: "ATH", "t", "t-9")
    assert len(masters) == 2 and all("/future/newpath/" in m for m in masters)

def test_resolve_masters_no_athlete():
    from trace_grabber.streams import resolve_masters
    assert resolve_masters(_Req([]), _Page(""), lambda: None, "t", "t-9") == []
