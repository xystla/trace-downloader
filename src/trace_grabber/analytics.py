"""Team analytics from Trace's per-game event feed (the user's own data).

Pure compute functions (unit-tested) plus thin fetch helpers over the app's
authenticated Playwright request context. See
docs/superpowers/specs/2026-09-14-team-analytics-design.md.
"""
from dataclasses import dataclass

_THIRDS = ("defensive", "middle", "offensive")


def _is_touch_chain(m: dict) -> bool:
    return "touch_chain" in (m.get("type") or "") \
        or "touch-chain" in (m.get("keywords") or [])


def _chain_thirds(m: dict) -> list[str]:
    ths = [t for t in (m.get("thirds") or []) if t in _THIRDS]
    if ths:
        return ths
    return [t for t in (m.get("start_third"), m.get("end_third")) if t in _THIRDS]


@dataclass
class Territory:
    defensive: float
    middle: float
    offensive: float


def compute_territory(moments: list[dict], our_side: str) -> Territory:
    acc = {t: 0.0 for t in _THIRDS}
    for m in moments:
        if not _is_touch_chain(m) or m.get("side") != our_side:
            continue
        ths = _chain_thirds(m)
        if not ths:
            continue
        share = (m.get("duration") or 0) / len(ths)
        for t in ths:
            acc[t] += share
    total = sum(acc.values())
    if not total:
        return Territory(0.0, 0.0, 0.0)
    return Territory(*(round(acc[t] / total * 100, 1) for t in _THIRDS))


def _touches(m: dict) -> int:
    return len([n for n in (m.get("trace_numbers") or []) if n != "?"])


def _has_kw(m: dict, kw: str) -> bool:
    return kw in (m.get("keywords") or [])


@dataclass
class GameMeta:
    game_id: int
    date: str
    opponent: str
    our_side: str   # "home" or "away"


@dataclass
class GameStats:
    game_id: int
    date: str
    opponent: str
    poss_pct_us: float
    passes_us: int
    passes_them: int
    shots_us: int
    shots_them: int
    box_us: int
    att_third_us: int
    packing_us: int
    territory_us: Territory


def compute_game_stats(moments: list[dict], meta: GameMeta) -> GameStats:
    us, them = meta.our_side, ("away" if meta.our_side == "home" else "home")
    chains = [m for m in moments if _is_touch_chain(m)]
    ours = [m for m in chains if m.get("side") == us]
    theirs = [m for m in chains if m.get("side") == them]

    dur_all = sum(m.get("duration") or 0 for m in chains)
    dur_us = sum(m.get("duration") or 0 for m in ours)
    poss = round(dur_us / dur_all * 100, 1) if dur_all else 0.0

    return GameStats(
        game_id=meta.game_id, date=meta.date, opponent=meta.opponent,
        poss_pct_us=poss,
        passes_us=sum(_touches(m) for m in ours),
        passes_them=sum(_touches(m) for m in theirs),
        shots_us=sum(1 for m in moments if _has_kw(m, f"{us}-shot")),
        shots_them=sum(1 for m in moments if _has_kw(m, f"{them}-shot")),
        box_us=sum(1 for m in ours if _has_kw(m, f"{them}-box")),
        att_third_us=sum(1 for m in ours if m.get("end_third") == "offensive"),
        packing_us=sum(1 for m in ours if _has_kw(m, "packing")),
        territory_us=compute_territory(moments, us),
    )
