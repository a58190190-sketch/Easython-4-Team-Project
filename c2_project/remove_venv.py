"""Remove only Easython's own virtual environment after checking its path."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / ".venv"


def main() -> int:
    if not TARGET.exists():
        print("No Easython .venv exists.")
        return 0
    is_junction = getattr(TARGET, "is_junction", lambda: False)()
    if TARGET.is_symlink() or is_junction:
        print("[ERROR] Refusing to remove .venv because it is a link or junction.")
        return 2
    try:
        resolved = TARGET.resolve(strict=True)
    except OSError as exc:
        print(f"[ERROR] Cannot resolve the .venv path safely: {exc}")
        return 2
    if resolved.parent != ROOT or resolved.name.casefold() != ".venv" or resolved == ROOT:
        print(f"[ERROR] Refusing to remove a path outside the project: {resolved}")
        return 2
    if not (resolved / "pyvenv.cfg").is_file():
        print("[ERROR] The target does not contain a Python virtual-environment marker.")
        return 2
    try:
        shutil.rmtree(resolved)
    except OSError as exc:
        print(f"[ERROR] Could not remove Easython .venv: {exc}")
        return 1
    print("Easython .venv and its libraries were removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
