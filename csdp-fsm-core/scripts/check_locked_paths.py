from __future__ import annotations

import os
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, Sequence


def _run(cmd: Sequence[str]) -> tuple[int, str, str]:
    result = subprocess.run(cmd, text=True, capture_output=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _run_lines(cmd: Sequence[str]) -> list[str] | None:
    code, stdout, _ = _run(cmd)
    if code != 0:
        return None
    return [line for line in stdout.splitlines() if line]


def _get_commit_message() -> str:
    result = _run_lines(["git", "log", "-1", "--pretty=%B"])
    return "\n".join(result or [])


def _fetch_base_ref(base_ref: str) -> None:
    _run(["git", "fetch", "--no-tags", "--prune", "--depth=50", "origin", base_ref])


def _diff_with_merge_base(base_ref: str) -> list[str] | None:
    code, merge_base, _ = _run(["git", "merge-base", "HEAD", f"origin/{base_ref}"])
    if code != 0 or not merge_base:
        return None
    return _run_lines(["git", "diff", "--name-only", f"{merge_base}..HEAD"])


def _fallback_diffs() -> Iterable[list[str]]:
    for cmd in (
        ["git", "diff", "--name-only", "--staged"],
        ["git", "diff", "--name-only"],
        ["git", "show", "--name-only", "--pretty=", "HEAD"],
    ):
        result = _run_lines(cmd)
        if result is not None:
            yield result


def _get_changed_files() -> list[str] | None:
    base_ref = os.getenv("GITHUB_BASE_REF") or os.getenv("LOCK_BASE_REF") or "main"
    _fetch_base_ref(base_ref)
    changed = _diff_with_merge_base(base_ref)
    if changed is not None:
        return changed
    saw_result = False
    for result in _fallback_diffs():
        saw_result = True
        if result:
            return result
    if saw_result:
        return []
    return None


def _load_locked_patterns() -> list[str]:
    path = Path(__file__).with_name("locked_paths.txt")
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


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
    if changed is None:
        print("LOCK VIOLATION: unable to determine changed files.")
        return 1
    if not changed:
        return 0
    patterns = _load_locked_patterns()
    violations = []
    for path in changed:
        for pattern in patterns:
            if _is_locked(path, pattern):
                violations.append(path)
                break
    if violations:
        print("LOCK VIOLATION:")
        for path in sorted(set(violations)):
            print(f"  - {path}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
