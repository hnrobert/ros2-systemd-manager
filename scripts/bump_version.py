#!/usr/bin/env python3
"""Bump project version in source files.

This script updates version strings in:
 - pyproject.toml ([project].version)

Usage:
    python scripts/bump_version.py 1.2.3

It prints the normalized version on the first line and exits with:
 - 0 when changes were made and files updated
 - 2 when no changes required (already at requested version)
 - 1 on validation or other errors
"""

import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[\-+].*)?$")


def validate_version(v: str) -> bool:
    return bool(VERSION_RE.match(v.strip()))


def replace_in_file(path: Path, pattern: re.Pattern, repl: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text, n = pattern.subn(repl, text)
    if n and new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: bump_version.py <new-version>")
        return 1

    raw_version = sys.argv[1].strip()
    # Allow leading 'v' or 'V'
    if raw_version.startswith(("v", "V")):
        new_version = raw_version[1:]
    else:
        new_version = raw_version

    # Print normalized version first for workflow parsing contract.
    print(new_version)

    if not validate_version(new_version):
        print(
            f"Invalid version: {raw_version}. Expect semantic version like 1.2.3 or v1.2.3"
        )
        return 1

    repo_root = Path(__file__).resolve().parents[1]
    files_changed = []

    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        print("pyproject.toml not found")
        return 1

    # Update [project].version in pyproject.toml (single expected match).
    pattern = re.compile(r'^(version\s*=\s*")[^"]+("\s*)$', re.MULTILINE)
    repl = rf'\g<1>{new_version}\2'
    if replace_in_file(pyproject, pattern, repl):
        files_changed.append(str(pyproject))

    if not files_changed:
        print(f"No files needed updating; already at version {new_version}.")
        return 2

    print("Updated files:")
    for file_path in files_changed:
        print(" -", file_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
