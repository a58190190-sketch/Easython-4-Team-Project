"""Check every active dependency declared in requirements.txt."""

from __future__ import annotations

import sys
from pathlib import Path
from importlib import metadata

try:
    from pip._vendor.packaging.requirements import Requirement
except ImportError as exc:
    print(f"[ERROR] pip requirement parser is unavailable: {exc}")
    raise SystemExit(2)


ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"


def read_requirements(path: Path, seen: set[Path] | None = None) -> list[Requirement]:
    seen = seen or set()
    path = path.resolve()
    if path in seen:
        return []
    seen.add(path)
    parsed: list[Requirement] = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r ", "--requirement ")):
            parsed.extend(read_requirements(path.parent / line.split(maxsplit=1)[1], seen))
            continue
        if line.startswith(("-c ", "--constraint ", "-")):
            # pip options and constraints do not declare additional packages.
            continue
        parsed.append(Requirement(line))
    return parsed


def main() -> int:
    if not REQUIREMENTS.is_file():
        print(f"[ERROR] Missing dependency list: {REQUIREMENTS}")
        return 2
    missing: list[str] = []
    try:
        requirements = read_requirements(REQUIREMENTS)
        for requirement in requirements:
            if requirement.marker and not requirement.marker.evaluate():
                continue
            try:
                installed = metadata.version(requirement.name)
            except metadata.PackageNotFoundError:
                missing.append(f"{requirement} (미설치)")
                continue
            if requirement.specifier and not requirement.specifier.contains(installed, prereleases=True):
                missing.append(f"{requirement} (설치 버전 {installed})")
    except (OSError, ValueError) as exc:
        print(f"[ERROR] requirements.txt를 읽거나 해석하지 못했습니다: {exc}")
        return 2

    if missing:
        print("[ERROR] 필수 Python 라이브러리가 없거나 버전 조건에 맞지 않습니다:")
        for item in missing:
            print(f"  - {item}")
        print("install.bat을 실행해 requirements.txt에 적힌 라이브러리를 설치/갱신하세요.")
        return 1
    print(f"필수 라이브러리 확인 완료 ({len(requirements)}개 항목).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
