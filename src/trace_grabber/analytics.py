"""Team analytics from Trace's per-game event feed (the user's own data).

Pure compute functions (unit-tested) plus thin fetch helpers over the app's
authenticated Playwright request context. See
docs/superpowers/specs/2026-09-14-team-analytics-design.md.
"""
import csv
import html as _html
import json
from dataclasses import dataclass, replace
from pathlib import Path

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
    our_side: str          # "home" or "away"
    match_secs: float = 0.0  # nominal match length (2 x approx_half_duration); 0 = unknown


@dataclass
class GameStats:
    game_id: int
    date: str
    opponent: str
    # Ball-control seconds in our tracked possession sequences. Trace's feed
    # only carries our own team's touch-chains (never the opponent's), so a
    # vs-opponent possession % is not derivable — we report our control time.
    poss_secs_us: float
    # Our ball-control as a share of nominal match time (poss_secs / match_secs),
    # or None when match length is unknown. Reads low because touch-chains are
    # notable sequences, not every touch — it's a "tracked-possession share".
    poss_pct_us: float | None
    passes_us: int
    shots_us: int
    shots_them: int
    box_us: int
    att_third_us: int
    packing_us: int
    territory_us: Territory
    # How many of our touch-chains these numbers rest on. Trace flags only a
    # handful per game (often 1-2 per half), so with a tiny count the territory
    # and per-half figures are noise — the UI shows this and flags low samples.
    sequences_us: int = 0
    match_secs_us: float = 0.0  # carried for season-level % aggregation


def compute_game_stats(moments: list[dict], meta: GameMeta) -> GameStats:
    us, them = meta.our_side, ("away" if meta.our_side == "home" else "home")
    chains = [m for m in moments if _is_touch_chain(m)]
    ours = [m for m in chains if m.get("side") == us]
    poss_secs = round(sum(m.get("duration") or 0 for m in ours), 1)
    poss_pct = (round(min(poss_secs / meta.match_secs * 100, 100.0), 1)
                if meta.match_secs else None)

    return GameStats(
        game_id=meta.game_id, date=meta.date, opponent=meta.opponent,
        poss_secs_us=poss_secs,
        poss_pct_us=poss_pct,
        sequences_us=len(ours),
        match_secs_us=meta.match_secs,
        passes_us=sum(_touches(m) for m in ours),
        shots_us=sum(1 for m in moments if _has_kw(m, f"{us}-shot")),
        shots_them=sum(1 for m in moments if _has_kw(m, f"{them}-shot")),
        box_us=sum(1 for m in ours if _has_kw(m, f"{them}-box")),
        att_third_us=sum(1 for m in ours if m.get("end_third") == "offensive"),
        packing_us=sum(1 for m in ours if _has_kw(m, "packing")),
        territory_us=compute_territory(moments, us),
    )


@dataclass
class GameSplit:
    """One game's stats for the whole match and each half."""
    whole: GameStats
    first: GameStats   # half 1
    second: GameStats  # half 2


def compute_split(moments: list[dict], meta: GameMeta) -> GameSplit:
    """Whole-game plus per-half stats. Per-half possession % divides by one half
    (match_secs / 2); whole divides by the full match."""
    half_secs = (meta.match_secs / 2) if meta.match_secs else 0.0
    half_meta = replace(meta, match_secs=half_secs)
    h1 = [m for m in moments if m.get("half") == 1]
    h2 = [m for m in moments if m.get("half") == 2]
    return GameSplit(
        whole=compute_game_stats(moments, meta),
        first=compute_game_stats(h1, half_meta),
        second=compute_game_stats(h2, half_meta),
    )


@dataclass
class SeasonStats:
    games: int
    poss_secs_us: float          # total ball-control seconds across all games
    poss_pct_us: float | None    # total ball-control / total nominal match time
    passes_us: int
    shots_us: int
    shots_them: int
    box_us: int
    att_third_us: int
    packing_us: int
    territory: Territory
    sequences_us: int = 0        # total tracked touch-chains behind these figures


def aggregate(stats: list[GameStats]) -> SeasonStats:
    n = len(stats)
    if not n:
        return SeasonStats(0, 0.0, None, 0, 0, 0, 0, 0, 0, Territory(0.0, 0.0, 0.0), 0)
    poss_secs = round(sum(s.poss_secs_us for s in stats), 1)
    match_secs = sum(s.match_secs_us for s in stats)
    poss_pct = round(min(poss_secs / match_secs * 100, 100.0), 1) if match_secs else None
    # Territory is duration-weighted (a game with one short sequence shouldn't
    # count the same as a full game); this equals the true overall per-third share.
    tot = sum(s.poss_secs_us for s in stats)
    if tot:
        wt = lambda pick: round(sum(pick(s) * s.poss_secs_us for s in stats) / tot, 1)
        territory = Territory(wt(lambda s: s.territory_us.defensive),
                              wt(lambda s: s.territory_us.middle),
                              wt(lambda s: s.territory_us.offensive))
    else:
        territory = Territory(0.0, 0.0, 0.0)
    return SeasonStats(
        games=n,
        poss_secs_us=poss_secs,
        poss_pct_us=poss_pct,
        passes_us=sum(s.passes_us for s in stats),
        shots_us=sum(s.shots_us for s in stats),
        shots_them=sum(s.shots_them for s in stats),
        box_us=sum(s.box_us for s in stats),
        att_third_us=sum(s.att_third_us for s in stats),
        packing_us=sum(s.packing_us for s in stats),
        territory=territory,
        sequences_us=sum(s.sequences_us for s in stats),
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


def _mins(secs: float) -> float:
    """Seconds → minutes, 1dp (for display of ball-control time)."""
    return round(secs / 60, 1)


def _pct(p: float | None) -> str:
    """Possession % for display, or an em dash when match length is unknown."""
    return "—" if p is None else f"{p}%"


_CSV_HEADER = ["date", "opponent", "sequences", "ball_control_min", "possession_pct",
               "passes_us", "shots_us", "shots_them", "box_us", "att_third_us",
               "packing_us", "terr_def", "terr_mid", "terr_off"]


def _row(s: "GameStats") -> list:
    return [s.date, s.opponent, s.sequences_us, _mins(s.poss_secs_us),
            "" if s.poss_pct_us is None else s.poss_pct_us, s.passes_us,
            s.shots_us, s.shots_them, s.box_us, s.att_third_us, s.packing_us,
            s.territory_us.defensive, s.territory_us.middle, s.territory_us.offensive]


def export_csv(stats: list[GameStats], season: SeasonStats, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(_CSV_HEADER)
        for s in stats:
            w.writerow(_row(s))
        w.writerow(["SEASON", f"{season.games} games", season.sequences_us,
                    _mins(season.poss_secs_us),
                    "" if season.poss_pct_us is None else season.poss_pct_us,
                    season.passes_us, season.shots_us, season.shots_them,
                    season.box_us, season.att_third_us, season.packing_us,
                    season.territory.defensive, season.territory.middle,
                    season.territory.offensive])


def export_html(stats: list[GameStats], season: SeasonStats, path: Path) -> None:
    e = _html.escape
    rows = "".join(
        f"<tr><td>{e(s.date)}</td><td>{e(s.opponent)}</td><td>{s.sequences_us}</td>"
        f"<td>{_mins(s.poss_secs_us)}</td><td>{_pct(s.poss_pct_us)}</td>"
        f"<td>{s.passes_us}</td><td>{s.shots_us}</td><td>{s.shots_them}</td>"
        f"<td>{s.box_us}</td><td>{s.att_third_us}</td><td>{s.packing_us}</td></tr>"
        for s in stats)
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Team Analytics</title><style>
body{{font:14px system-ui;margin:24px;color:#0d1b22}}
table{{border-collapse:collapse;margin-top:16px}}
th,td{{border:1px solid #ccc;padding:6px 10px;text-align:center}}
th{{background:#f3f5f6}} .caption{{font-size:12px;color:#667;margin:6px 0}}
</style></head><body>
<h1>Team Analytics — {season.games} games</h1>
<p>Season ball-control {_mins(season.poss_secs_us)} min ({_pct(season.poss_pct_us)}) ·
 Passes (touches) {season.passes_us} · Shots {season.shots_us}-{season.shots_them}</p>
<h2>Where the ball was (season, by third)</h2>
{territory_svg(season.territory)}
<p class="caption">Based on {season.sequences_us} tracked sequence(s). Ball-control
= time in your team's tracked touch-chains; the % is that time as a share of a
nominal 90-minute match (reads low — touch-chains are notable sequences, not every
touch, and Trace doesn't feed opponent possession). "Seq" is how many sequences a
row rests on — with only a few, the territory and per-half figures are unreliable.
Territory is thirds-based, not pixel tracking.</p>
<table><thead><tr><th>Date</th><th>Opponent</th><th>Seq</th><th>Ball-control (min)</th>
<th>Poss %</th><th>Passes (touches)</th><th>Shots</th><th>Opp shots</th>
<th>Box</th><th>Att ⅓</th><th>Packing</th>
</tr></thead><tbody>{rows}</tbody></table>
</body></html>"""
    Path(path).write_text(doc, encoding="utf-8")


GQL_URL = "https://go.traceup.com/traceid-prod/graphql"
USERS_SELF_URL = "https://teams.traceup.com/webapp/users/self"
USERS_SELF_TOKEN_URL = "https://teams.traceup.com/webapp/users/self/token"

TEAM_GAMES_Q = ("query teamGames($team_id: Int!, $token: UserToken!) { "
                "teamGames(team_id: $team_id, token: $token) { "
                "game_id status full_date approx_half_duration access { allowed } "
                "home_team { team_id name title } away_team { team_id name title } } }")

# The `moments` field takes its own required `hash_key` argument, in addition
# to the one on `game`.
GAME_Q = ("query game($game_id: Int!, $hash_key: String!, $token: UserToken) { "
          "game(game_id: $game_id, hash_key: $hash_key, token: $token) { "
          "access { allowed } "
          "moments(hash_key: $hash_key) { type side half start_third end_third thirds "
          "duration trace_numbers keywords } } }")

# hash_key lives on the GraphQL profile, not the users/self REST payload.
PROFILE_Q = ("query myProfile($user_id: Int!, $token: UserToken!) { "
             "profile(user_id: $user_id, token: $token) { hash_key } }")


def graphql(request, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables})
    resp = request.post(GQL_URL, data=body,
                        headers={"content-type": "application/json"}, timeout=20000)
    j = resp.json()
    if j.get("errors") or "data" not in j:
        raise RuntimeError(f"graphql error: {j.get('errors')}")
    return j["data"]


def user_token(request) -> dict:
    self_j = request.get(USERS_SELF_URL, timeout=12000).json()
    user_id = ((self_j.get("data") or {}).get("user_id"))
    tok_j = request.get(USERS_SELF_TOKEN_URL, timeout=12000).json()
    data = tok_j.get("data") or {}
    return {"user_id": user_id,
            "token": data.get("token"),
            "timestamp": data.get("timestamp")}


def fetch_team_games(request, team_id: int, token: dict) -> dict[int, dict]:
    data = graphql(request, TEAM_GAMES_Q, {"team_id": team_id, "token": token})
    return {g["game_id"]: g for g in (data.get("teamGames") or [])}


def fetch_game_moments(request, game_id: int, hash_key: str, token: dict) -> tuple[bool, list[dict]]:
    data = graphql(request, GAME_Q,
                   {"game_id": game_id, "hash_key": hash_key, "token": token})
    game = data.get("game") or {}
    allowed = bool((game.get("access") or {}).get("allowed"))
    return allowed, (game.get("moments") or [])


USERS_SELF_TEAMS_URL = "https://teams.traceup.com/webapp/users/self/teams"


def user_hash_key(request, token: dict) -> str:
    data = graphql(request, PROFILE_Q,
                   {"user_id": token["user_id"], "token": token})
    return ((data.get("profile") or {}).get("hash_key")) or ""


def team_numeric_id(request, team_slug: str):
    j = request.get(USERS_SELF_TEAMS_URL, timeout=12000).json()
    for t in (j.get("data") or []):
        if t.get("name") == team_slug:
            return t.get("team_id") or t.get("id")
    return None


def our_side_for(game: dict, team_id: int):
    if (game.get("home_team") or {}).get("team_id") == team_id:
        return "home"
    if (game.get("away_team") or {}).get("team_id") == team_id:
        return "away"
    return None
