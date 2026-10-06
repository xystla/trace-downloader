"""Write the CHANGELOG.md section for a version to a file, for use as the
GitHub release notes:  python packaging/release_notes.py v1.4.0 RELEASE_NOTES.md"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trace_grabber.updates import notes_for  # noqa: E402


def main(version: str, out: str) -> None:
    notes = notes_for(version, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    # Written as UTF-8 here (not via shell redirection, which is UTF-16 on Windows).
    Path(out).write_text("".join(f"- {line}\n" for line in notes), encoding="utf-8")
    print(f"{len(notes)} change(s) for {version}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
