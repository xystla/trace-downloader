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


@dataclass
class SeasonStats:
    games: int
    poss_pct_us: float
    passes_us: int
    passes_them: int
    shots_us: int
    shots_them: int
    box_us: int
    att_third_us: int
    packing_us: int
    territory: Territory


def aggregate(stats: list[GameStats]) -> SeasonStats:
    n = len(stats)
    if not n:
        return SeasonStats(0, 0.0, 0, 0, 0, 0, 0, 0, 0, Territory(0.0, 0.0, 0.0))
    mean = lambda xs: round(sum(xs) / n, 1)
    return SeasonStats(
        games=n,
        poss_pct_us=mean([s.poss_pct_us for s in stats]),
        passes_us=sum(s.passes_us for s in stats),
        passes_them=sum(s.passes_them for s in stats),
        shots_us=sum(s.shots_us for s in stats),
        shots_them=sum(s.shots_them for s in stats),
        box_us=sum(s.box_us for s in stats),
        att_third_us=sum(s.att_third_us for s in stats),
        packing_us=sum(s.packing_us for s in stats),
        territory=Territory(
            mean([s.territory_us.defensive for s in stats]),
            mean([s.territory_us.middle for s in stats]),
            mean([s.territory_us.offensive for s in stats]),
        ),
    )


def territory_svg(t: Territory, *, dark: bool = False) -> str:
    W, H = 360, 200
    band_w = W / 3
    stroke = "#e8e8e8" if dark else "#20303a"
    label = "#ffffff" if dark else "#0d1b22"
    base = "20,120,90"  # green, opacity carries the share
    shares = ((t.defensive, "Def"), (t.middle, "Mid"), (t.offensive, "Att"))
    peak = max((s for s, _ in shares), default=0) or 1
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'width="{W}" height="{H}" role="img" aria-label="Territory by third">']
    parts.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="none" '
                 f'stroke="{stroke}" stroke-width="2"/>')
    for i, (share, name) in enumerate(shares):
        x = i * band_w
        op = round(0.12 + 0.78 * (share / peak), 3)
        parts.append(f'<rect x="{x:.1f}" y="0" width="{band_w:.1f}" height="{H}" '
                     f'fill="rgba({base},{op})"/>')
        parts.append(f'<text x="{x + band_w/2:.1f}" y="{H/2 - 6:.0f}" '
                     f'text-anchor="middle" font-size="20" font-weight="700" '
                     f'fill="{label}">{share:g}%</text>')
        parts.append(f'<text x="{x + band_w/2:.1f}" y="{H/2 + 16:.0f}" '
                     f'text-anchor="middle" font-size="12" fill="{label}">{name}</text>')
    # centre line + goal boxes
    parts.append(f'<line x1="{W/2}" y1="0" x2="{W/2}" y2="{H}" stroke="{stroke}" '
                 f'stroke-width="1"/>')
    parts.append(f'<rect x="0" y="{H/2-40}" width="26" height="80" fill="none" '
                 f'stroke="{stroke}" stroke-width="2"/>')
    parts.append(f'<rect x="{W-26}" y="{H/2-40}" width="26" height="80" fill="none" '
                 f'stroke="{stroke}" stroke-width="2"/>')
    parts.append("</svg>")
    return "".join(parts)
