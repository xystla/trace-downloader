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

class _Asked:
    def __init__(self, url): self.url = url

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
    """Minimal fake Playwright page for fallback tests. `requests` are the
    addresses the page asks for as it loads."""
    def __init__(self, html="", requests=()):
        self._html = html; self.url = ""; self._requests = requests
        self._listeners = []; self.clicked = []
    def on(self, event, fn): self._listeners.append(fn)
    def remove_listener(self, event, fn): self._listeners.remove(fn)
    def goto(self, *a, **k):
        self.url = "https://go.traceup.com/traceid/athlete/X/watch/9/items/"
        for url in self._requests:
            for fn in list(self._listeners):
                fn(_Asked(url))
    def wait_for_selector(self, *a, **k): pass
    def wait_for_timeout(self, *a, **k): pass
    def click(self, selector, *a, **k): self.clicked.append(selector)
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

def test_prefix_from_base_path():
    from trace_grabber.streams import prefix_from_base_path
    assert prefix_from_base_path("/us-west-1/soccer/api/teams/t/games/t-9/") == "us-west-1/soccer/api"
    assert prefix_from_base_path("/api/teams/t/games/t-9/") == "api"
    assert prefix_from_base_path(None) is None
    assert prefix_from_base_path("/somewhere/else/") is None

def test_resolve_prefix_tries_the_games_own_place_first():
    # A region that is not in PREFIXES: only what Trace said about the game finds it.
    request = _Req(["/us-west-1/soccer/api/"])
    assert resolve_prefix(request, "t", "t-9") is None
    assert resolve_prefix(request, "t", "t-9", "us-west-1/soccer/api") == "us-west-1/soccer/api"

def test_resolve_prefix_falls_back_when_the_games_own_place_fails():
    assert resolve_prefix(_Req(["/us-west-2/soccer/api/"]), "t", "t-9", "gone/away") == "us-west-2/soccer/api"

def test_resolve_masters_in_an_unlisted_region():
    from trace_grabber.streams import resolve_masters
    masters = resolve_masters(_Req(["/us-west-1/soccer/api/"]), _Page(""), lambda: None, "t", "t-9",
                              "us-west-1/soccer/api")
    assert len(masters) == 2 and all("/us-west-1/soccer/api/" in m for m in masters)

def test_prefix_from_url():
    from trace_grabber.streams import prefix_from_url
    url = "https://go.traceup.com/eu-north-9/soccer/api/teams/t/games/t-9/animations/a.webp?x=1"
    assert prefix_from_url(url, "t", "t-9") == "eu-north-9/soccer/api"
    assert prefix_from_url("https://go.traceup.com/api/teams/t/games/t-9/poster.jpg", "t", "t-9") == "api"
    assert prefix_from_url("https://go.traceup.com/api/teams/t/games/t-8/poster.jpg", "t", "t-9") is None
    assert prefix_from_url("https://elsewhere.example/x/teams/t/games/t-9/poster.jpg", "t", "t-9") is None

def test_resolve_masters_reads_the_place_off_what_the_watch_page_asks_for():
    # Since Trace's Oct 2026 redesign the watch page's HTML no longer names the
    # video; the page still fetches the game's files from its real place.
    from trace_grabber.streams import resolve_masters
    page = _Page("<html></html>", requests=[
        "https://go.traceup.com/static/app.js",
        "https://go.traceup.com/eu-north-9/soccer/api/teams/t/games/t-9/animations/a.webp"])
    masters = resolve_masters(_Req(["/eu-north-9/soccer/api/"]), page, lambda: "ATH", "t", "t-9")
    assert len(masters) == 2 and all("/eu-north-9/soccer/api/" in m for m in masters)
    assert page._listeners == []                     # stops listening once it has looked

def test_discover_athlete_opens_a_game_card_as_trace_draws_them_now():
    from trace_grabber.streams import discover_athlete
    page = _Page()
    assert discover_athlete(page, "https://go.traceup.com/traceid/team/t") == "X"
    assert page.clicked == [".GameCard .thumbnail"]
