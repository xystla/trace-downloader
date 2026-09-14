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
