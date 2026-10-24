"""Download the CMU keystroke benchmark CSV if not already present."""
import sys
from pathlib import Path

URL = "https://www.cs.cmu.edu/~keystroke/DSL-StrongPasswordData.csv"
DEST = Path(__file__).resolve().parent.parent / "data" / "raw" / "cmu" / "DSL-StrongPasswordData.csv"


def main() -> int:
    if DEST.exists() and DEST.stat().st_size > 1_000_000:
        print(f"CMU dataset already present: {DEST}")
        return 0
    DEST.parent.mkdir(parents=True, exist_ok=True)
    try:
        import httpx

        print(f"Downloading {URL} ...")
        with httpx.stream("GET", URL, timeout=60, follow_redirects=True) as r:
            r.raise_for_status()
            with open(DEST, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        print(f"Saved {DEST} ({DEST.stat().st_size} bytes)")
        return 0
    except Exception as e:  # non-fatal: tests skip if missing
        print(f"CMU download failed ({e}); tests depending on it will skip.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
