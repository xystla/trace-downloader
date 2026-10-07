import re

_EXTINF = re.compile(r"#EXTINF:([\d.]+)")
_OUT_TIME = re.compile(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_TOTAL_SIZE = re.compile(r"total_size=(\d+)")

def playlist_duration(media_playlist_text: str) -> float:
    return sum(float(m) for m in _EXTINF.findall(media_playlist_text))

def parse_out_time(line: str) -> float | None:
    m = _OUT_TIME.search(line)
    if not m:
        return None
    h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mnt * 60 + s

def parse_total_size(line: str) -> int | None:
    m = _TOTAL_SIZE.search(line)
    return int(m.group(1)) if m else None

def percent(done_seconds: float, total_seconds: float) -> int:
    if total_seconds <= 0:
        return 0
    return max(0, min(100, int(done_seconds / total_seconds * 100)))


class Rate:
    """Download speed over the last `window` seconds, and the time left at that
    speed. Fed with (clock, bytes done so far); bytes that were already on disk
    when a download resumed are in the first sample, so they never count as speed."""

    def __init__(self, window: float = 10.0):
        self._window = window
        self._samples: list[tuple[float, int]] = []

    def add(self, now: float, done_bytes: int) -> None:
        self._samples.append((now, done_bytes))
        # Keep one sample at or before the start of the window to measure from.
        while len(self._samples) > 2 and self._samples[1][0] <= now - self._window:
            self._samples.pop(0)

    def _span(self) -> float:
        return self._samples[-1][0] - self._samples[0][0] if len(self._samples) > 1 else 0.0

    def bytes_per_sec(self) -> float:
        span = self._span()
        if span <= 0:
            return 0.0
        return max(0.0, (self._samples[-1][1] - self._samples[0][1]) / span)

    def eta(self, remaining_bytes: int) -> int | None:
        """Seconds left, or None when there is too little to go on."""
        speed = self.bytes_per_sec()
        if self._span() < 3 or speed <= 0:
            return None
        return int(max(0, remaining_bytes) / speed)
