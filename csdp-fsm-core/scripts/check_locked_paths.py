from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from fnmatch import fnmatch


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def _get_commit_message() -> str:
    return _run(["git", "log", "-1", "--pretty=%B"])


def _get_changed_files() -> list[str]:
    try:
        diff = _run(["git", "diff", "--name-only", "origin/main...HEAD"])
    except Exception:
        diff = _run(["git", "diff", "--name-only", "HEAD~1..HEAD"])
    return [line for line in diff.splitlines() if line]


def _load_locked_patterns() -> list[str]:
    path = Path(__file__).with_name("locked_paths.txt")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _is_locked(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if "*" in pattern:
        return fnmatch(path, pattern)
    return path == pattern


def main() -> int:
    if "[ALLOW_CORE_EDIT]" in _get_commit_message():
        return 0
    changed = _get_changed_files()
    patterns = _load_locked_patterns()
    violations = []
    for path in changed:
        for pattern in patterns:
            if _is_locked(path, pattern):
                violations.append(path)
                break
    if violations:
        print("Locked path modifications detected:")
        for path in sorted(set(violations)):
            print(f"- {path}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
