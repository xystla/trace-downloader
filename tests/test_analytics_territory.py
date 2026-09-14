import json
from pathlib import Path
from trace_grabber.analytics import compute_territory, Territory

FIX = Path(__file__).parent / "fixtures" / "game_moments.json"
MOMENTS = json.loads(FIX.read_text())

def test_territory_home():
    t = compute_territory(MOMENTS, "home")
    # H1 dur60 -> 30 defensive + 30 middle; H2 dur40 -> 40 offensive; total 100
    assert t == Territory(defensive=30.0, middle=30.0, offensive=40.0)

def test_territory_away_uses_thirds_fallback():
    t = compute_territory(MOMENTS, "away")
    # A1 dur30 -> 15 middle + 15 offensive; A2 thirds=[] falls back to start/end
    # (defensive) -> 20 defensive; total 50 -> def 40, mid 30, off 30
    assert t == Territory(defensive=40.0, middle=30.0, offensive=30.0)

def test_territory_empty_when_no_chains():
    assert compute_territory([], "home") == Territory(0.0, 0.0, 0.0)
