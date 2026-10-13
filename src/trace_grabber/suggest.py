"""A first guess at a game's clock marks, from Trace's player tracking.

The tracking files ('radar<half>_dynamic.json', see radar.py) say where every
tracked person stood, twice a second. Three things in them show the shape of a
game:

- a break: the field empties, and stays nearly empty for a while;
- a kick-off or restart: everyone is back on the field and standing still,
  then all of them move at once;
- the end of a half or of the game: everyone sets off across the field
  together (it need not empty after the last whistle: there are handshakes,
  and the next game's teams come on to warm up).

The guesses are a place to start from, not an answer, and lean to the safe
side: a start or restart a little early and a break or the end a little late,
so that a guess that is off leaves some standing about in, and cuts no play.

The referee's whistle settles a guess when one is heard close by (whistle.py):
play starts just after a whistle and stops at one, whatever the players are
doing. Not every whistle is heard, so the tracking stays the main thing.
"""
import statistics

FIELD = 1000
INNER_X = (60, 940)         # on the field itself, not standing at its edge
INNER_Y = (100, 900)
SMOOTH = 2                  # seconds either side that each second is averaged with

FULL = 0.85                 # of the usual number of people: the field is full
EMPTY = 0.45                # ... and nearly empty
ON_FIELD = 0.6              # of the usual number on the field itself: lined up to play, not gathered at the side
BREAK_SECS = 20             # the field stays empty at least this long in a break
FULL_SECS = 30              # "still full" is judged over this long

SURGE = 25.0                # field units a second, averaged over everyone: all moving at once
LULL = 10.0                 # ... and everyone standing
LULL_BEFORE = 30            # how long before the surge the standing may be
ACROSS = 170.0              # spread across the field when everyone walks off together
WALK_BACK = 60              # how far back from the field emptying the walk-off may start
AFTER_END = (15, 75)        # after the last whistle the field is not full again over these seconds...
NOT_FULL = 0.8              # ... staying under this much of the usual number

EARLY = 8                   # seconds a start or restart is put before the guess
LATE = 3                    # seconds a break or the end is put after it

MIN_PEOPLE = 6              # fewer tracked than this at the best of times: nothing to go on

# A whistle near a guess. Players set off a little after the whistle that sends
# them, so it is looked for mostly before the moment the tracking shows.
KICK_WHISTLE = (-13, 3)     # seconds around a start or restart
STOP_WHISTLE = (-12, 3)     # ... and around a break or the end
STOP_WHISTLE_SECS = 0.3     # the whistle for a break is a long one, or several: a short peep is a foul
BESIDE = 1.0                # seconds a mark is put clear of its whistle
LISTEN_WIDER = 12           # seconds more each side that are listened to, to know what is usual there


def _frames(tracking: dict):
    """(seconds into the half, {person: (x, y)}) for each frame of a tracking file."""
    fps = (tracking.get("setup") or {}).get("fps") or 2
    for index, frame in enumerate(tracking.get("frm") or []):
        if not isinstance(frame, dict):
            continue
        t = frame.get("t")
        seconds = t / 100 if isinstance(t, (int, float)) and not isinstance(t, bool) else index / fps
        people = {}
        for who, seen in (frame.get("a") or {}).items() if isinstance(frame.get("a"), dict) else []:
            where = seen.get("l") if isinstance(seen, dict) else None
            if isinstance(where, list) and len(where) >= 2:
                people[who] = (where[0], where[1])
        yield seconds, people


def half_length(tracking: dict) -> float:
    """How long a half's tracking runs, in seconds."""
    last = 0.0
    for seconds, _ in _frames(tracking):
        last = seconds
    fps = (tracking.get("setup") or {}).get("fps") or 2
    return last + 1 / fps if last else 0.0


def _spread(values) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def activity(halves) -> dict:
    """What the tracking shows for each second of the game clock, smoothed:
    {"people", "on_field", "speed", "across"}, each a list with one number a
    second. `halves` is [(tracking, seconds into the game that half starts)]."""
    seconds = {}
    for tracking, starts in halves:
        before = {}
        for t, people in _frames(tracking):
            inner = [p for p in people.values()
                     if INNER_X[0] <= p[0] <= INNER_X[1] and INNER_Y[0] <= p[1] <= INNER_Y[1]]
            fps = (tracking.get("setup") or {}).get("fps") or 2
            moved = [((p[0] - before[who][0]) ** 2 + (p[1] - before[who][1]) ** 2) ** 0.5 * fps
                     for who, p in people.items() if who in before]
            before = people
            row = seconds.setdefault(int(t + starts), {"people": [], "on_field": [], "speed": [], "across": []})
            row["people"].append(len(people))
            row["on_field"].append(len(inner))
            row["speed"].append(sum(moved) / len(moved) if moved else 0.0)
            row["across"].append(_spread([p[1] for p in inner]))
    if not seconds:
        return {"people": [], "on_field": [], "speed": [], "across": []}
    last = max(seconds)
    out = {}
    for key in ("people", "on_field", "speed", "across"):
        raw = [sum(seconds[s][key]) / len(seconds[s][key]) if s in seconds else None for s in range(last + 1)]
        smooth = []
        for s in range(last + 1):
            near = [v for v in raw[max(0, s - SMOOTH):s + SMOOTH + 1] if v is not None]
            smooth.append(sum(near) / len(near) if near else 0.0)
        out[key] = smooth
    return out


def _empty_stretches(people, usual):
    """[(first second, last second)] of each time the field stays nearly empty."""
    found, s, last = [], 0, len(people) - 1
    while s <= last:
        if people[s] < EMPTY * usual:
            e = s
            while e < last and people[e + 1] < EMPTY * usual:
                e += 1
            if e - s >= BREAK_SECS:
                found.append((s, e))
            s = e + 1
        else:
            s += 1
    return found


def _walk_off(act, usual, emptied):
    """The second everyone set off across the field, before it emptied at `emptied`."""
    people, across = act["people"], act["across"]
    t = emptied
    while t > FULL_SECS and sum(people[t - FULL_SECS:t]) / FULL_SECS < FULL * usual:
        t -= 1                                  # the last second it had been full for a while
    for s in range(t, max(1, t - WALK_BACK), -1):
        if across[s] >= ACROSS > across[s - 1]:
            return s
    return t


def _kick_off(act, usual, usual_on, start, until):
    """The last second everyone stood still before all moving at once, looking
    from `start` up to `until`: the earliest such moment. Failing that, the
    second the field was full again; None when it never was."""
    people, on_field, speed = act["people"], act["on_field"], act["speed"]
    t = start
    while t < until and people[t] < FULL * usual:
        t += 1
    if t >= until:
        return None
    ready = lambda s: people[s] >= FULL * usual and on_field[s] >= ON_FIELD * usual_on
    for s in range(t, until):
        if speed[s] >= SURGE and ready(s):
            still = [x for x in range(max(t, s - LULL_BEFORE), s) if speed[x] <= LULL and ready(x)]
            if still:
                return max(still)
    return t


def _last_whistle(act, usual, start):
    """After the last restart: the first time everyone sets off across the field
    and it is not full again over the next minute."""
    people, across = act["people"], act["across"]
    for s in range(start + FULL_SECS, len(people) - AFTER_END[0]):
        if across[s] >= ACROSS > across[s - 1]:
            after = people[s + AFTER_END[0]:s + AFTER_END[1]]
            if after and sum(after) / len(after) < NOT_FULL * usual:
                return s
    return None


def guesses(act: dict) -> list[dict]:
    """What the tracking alone shows, in order and unpadded: [{"kind": "start"
    | "break" | "resume" | "end", "t": seconds}]. Empty when it shows too
    little to go on."""
    people = act.get("people") or []
    seen = [n for n in people if n > 0]
    if len(seen) < 2 * BREAK_SECS:
        return []
    usual = statistics.median(seen)
    if usual < MIN_PEOPLE:
        return []
    usual_on = statistics.median([n for n in act["on_field"] if n > 0] or [0])
    last = len(people) - 1
    # An empty stretch that runs to the end of the recording is after the game, not a break in it.
    breaks = [b for b in _empty_stretches(people, usual) if b[1] < last - 5]
    guess = [("start", _kick_off(act, usual, usual_on, 0, breaks[0][0] if breaks else last))]
    for i, (emptied, refilled) in enumerate(breaks):
        guess.append(("break", _walk_off(act, usual, emptied)))
        guess.append(("resume", _kick_off(act, usual, usual_on, refilled,
                                           breaks[i + 1][0] if i + 1 < len(breaks) else last)))
    restarts = [t for kind, t in guess if kind != "break" and t is not None]
    guess.append(("end", _last_whistle(act, usual, restarts[-1]) if restarts else None))
    return _in_order([{"kind": kind, "t": float(t)} for kind, t in guess if t is not None])


def _by_whistle(kind: str, t: float, heard) -> float | None:
    """Where a whistle heard near a guess puts the mark, or None with none to go by.
    `heard(start, seconds)` gives [(when a whistle starts, when it ends)] on the
    game clock, or None when there is no sound."""
    kick = kind in ("start", "resume")
    before, after = KICK_WHISTLE if kick else STOP_WHISTLE
    found = heard(t + before - LISTEN_WIDER, after - before + 2 * LISTEN_WIDER) or []
    near = [(a, b) for a, b in found if t + before <= a <= t + after
            and (kick or b - a >= STOP_WHISTLE_SECS)]
    if not near:
        return None
    # The safe side again: the first whistle play could have started on, the last it could have stopped on.
    return near[0][0] - BESIDE if kick else near[-1][1] + BESIDE


def marks(act: dict, length: float | None = None, heard=None) -> list[dict]:
    """The guessed clock marks, in order: [{"kind": "start" | "break" | "resume"
    | "end", "t": seconds}]. Empty when the tracking shows too little to go on.
    `length` is the video's, which no mark is put past; `heard`, when the video
    has sound, finds the whistles in a stretch of it (see _by_whistle)."""
    top = float(length) if length else float(len(act.get("people") or [1]) - 1)
    out = []
    for m in guesses(act):
        t = _by_whistle(m["kind"], m["t"], heard) if heard else None
        if t is None:
            t = m["t"] - EARLY if m["kind"] in ("start", "resume") else m["t"] + LATE
        out.append({"kind": m["kind"], "t": round(float(max(0.0, min(top, t))), 3)})
    return _in_order(out)


def _in_order(found: list[dict]) -> list[dict]:
    """Only marks that make a game: a start, then breaks each with its restart,
    then perhaps an end, each later than the one before."""
    out = []
    for m in found:
        if out and m["t"] <= out[-1]["t"]:
            continue
        wanted = {"start"} if not out else {"start": {"break", "end"}, "break": {"resume"},
                                             "resume": {"break", "end"}, "end": set()}[out[-1]["kind"]]
        if m["kind"] in wanted:
            out.append(m)
    if out and out[-1]["kind"] == "break":       # a break nothing came back from
        out.pop()
    return out


def from_tracking(halves: list[dict], first_half_length: float | None = None,
                  length: float | None = None, heard=None) -> list[dict]:
    """The guessed marks from each half's tracking file, in playing order.
    `first_half_length` is the first half's video's, when it is a file of its own."""
    timed, at = [], 0.0
    for i, tracking in enumerate(halves):
        timed.append((tracking, at))
        at += first_half_length if i == 0 and first_half_length else half_length(tracking)
    return marks(activity(timed), length, heard)
