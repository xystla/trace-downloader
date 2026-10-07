"""Will a game fit? How big it should be, how much room it needs while it is
being put together, and how much the disk has."""
import shutil
from pathlib import Path

MARGIN = 500_000_000         # room left over, so the disk is never filled to the last byte
LOW = 10_000_000_000         # below this, the Downloads page shows free space as a warning


class NotEnoughSpace(RuntimeError):
    """The disk can't hold this download. Raised before anything is fetched."""


def estimate(bandwidth: int, seconds: float) -> int:
    """Bytes for a stream of `bandwidth` bits per second lasting `seconds`."""
    return int(bandwidth / 8 * seconds)


def needed(halves: list[tuple[int, int, bool]], combine: bool) -> int:
    """Free bytes a game needs to finish. Each half is (estimated size, bytes of
    its pieces already on disk, already finished). Besides what is still to be
    fetched there must be room to join a half (its pieces and its video exist
    side by side for a moment) and, when the halves are combined, for the
    combined file beside them."""
    unfinished = [(size, have) for size, have, finished in halves if not finished]
    to_fetch = sum(max(0, size - have) for size, have in unfinished)
    join = max((size for size, _ in unfinished), default=0)
    combined = sum(size for size, _, _ in halves) if combine and len(halves) == 2 else 0
    return to_fetch + join + combined + MARGIN


def free(folder) -> int:
    """Free bytes on the disk `folder` is on. The folder may not exist yet (or its
    drive may not be connected), so the nearest folder that does exist is measured."""
    folder = Path(folder)
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    return shutil.disk_usage(folder).free


def size_text(n: int) -> str:
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.0f} MB"
    if n < 10_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    return f"{n / 1_000_000_000:.0f} GB"


def check(folder, need: int) -> None:
    have = free(folder)
    if have < need:
        raise NotEnoughSpace(f"Not enough disk space: this game needs about {size_text(need)} "
                             f"and {size_text(have)} is free.")
