from pathlib import Path
from trace_grabber.analytics import (export_csv, export_html, GameStats,
                                     SeasonStats, Territory)

def _sample():
    g = GameStats(game_id=1, date="2026-09-12", opponent="Latterman",
                  poss_pct_us=66.7, passes_us=7, passes_them=3, shots_us=2,
                  shots_them=1, box_us=1, att_third_us=1, packing_us=1,
                  territory_us=Territory(30.0, 30.0, 40.0))
    season = SeasonStats(1, 66.7, 7, 3, 2, 1, 1, 1, 1, Territory(30.0, 30.0, 40.0))
    return [g], season

def test_csv_has_header_row_and_game(tmp_path):
    games, season = _sample()
    p = tmp_path / "stats.csv"
    export_csv(games, season, p)
    lines = p.read_text().strip().splitlines()
    assert lines[0].startswith("date,opponent,possession_pct,passes")
    assert "Latterman" in lines[1]
    assert any(row.lower().startswith("season") or "TOTAL" in row for row in lines)

def test_html_is_self_contained_with_svg(tmp_path):
    games, season = _sample()
    p = tmp_path / "report.html"
    export_html(games, season, p)
    html = p.read_text()
    assert "<html" in html.lower() and "</html>" in html.lower()
    assert "<svg" in html                         # territory map embedded
    assert "Latterman" in html and "Passes (touches)" in html
    # no external assets (the SVG xmlns http://www.w3.org/2000/svg is not a fetch)
    assert 'src="http' not in html and 'href="http' not in html
