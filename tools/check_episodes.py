#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check every episode document in a directory tree.

    python tools/check_episodes.py                    # episodes/
    python tools/check_episodes.py --allow-draft      # drafts are ok
    python tools/check_episodes.py tests/fixtures

It enforces three things the schema cannot, which is the only reason this
exists as well as ``edi_schema.validate_episode``:

**Drafts are drafts.** Any ``TODO(expert)`` / ``TODO(maintainer)`` marker makes the
document a draft, and drafts are an error unless ``--allow-draft`` is passed.
The point is that a draft and a finished episode are different objects, and
the difference should be a red CI run rather than a reader's judgment. The
enum fields cannot carry a marker -- ``TODO(expert)`` is not a valid
``failure_class`` -- so scaffolds give those a documented default, and the
markers elsewhere in the document are what marks the whole thing unfinished.

**Ids are unique across the corpus.** JSON Schema validates one document at a
time and has no way to say "no other file may use this id". Two episodes
sharing an id silently overwrite each other in any index built over them.

**Fixtures stay where they belong.** An episode with
``provenance: synthetic-fixture`` is validator food, not data. If one is
committed outside a ``fixtures/`` directory, it will be read as a real expert
decision by anyone who does not open the file and check. That is the exact
failure mode the ``provenance`` field exists to prevent. The directory name is
matched as a whole path component, so a scratch directory that merely happens
to contain the word does not count.

Exit code is 1 if anything failed, so this can gate CI directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Runs as `python tools/check_episodes.py` as well as `python -m tools.check_episodes`.
# A direct script run puts <repo>/tools on sys.path, not the repo root, so the
# `tools` package would not be importable.
if __package__ in (None, ""):  # pragma: no cover - exercised by running the script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edi_schema import (  # noqa: E402
    Error,
    format_errors,
    validate_episode,
)

from tools import find_todo_markers  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO_ROOT / "episodes"

#: A synthetic fixture must live in a directory with one of these names.
#: Matched as a whole path component, not as a substring: a temp directory
#: called ``test_a_fixture_outside_a_fixture_directory_is_rejected0`` is not a
#: fixtures directory, and substring matching would happily say it was.
FIXTURE_DIR_NAMES = frozenset({"fixture", "fixtures"})


def in_fixture_dir(path: Path) -> bool:
    """True if any directory above ``path`` is named ``fixture(s)``."""
    return any(part.lower() in FIXTURE_DIR_NAMES for part in path.parent.parts)


__all__ = ["CheckResult", "check_directory", "main"]


@dataclass
class CheckResult:
    """Everything found wrong with one file, plus how it was classified."""

    path: Path
    errors: list[str] = field(default_factory=list)
    draft: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors


def _iter_episode_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    yield from sorted(root.rglob("*.json"))


def _dedupe_ids(results: Iterable[tuple[Path, dict[str, Any]]]) -> dict[Path, list[str]]:
    """Map each path to an error for any episode_id it shares with another."""
    seen: dict[str, list[Path]] = {}
    for path, document in results:
        episode_id = document.get("episode_id")
        if isinstance(episode_id, str) and episode_id:
            seen.setdefault(episode_id, []).append(path)

    problems: dict[Path, list[str]] = {}
    for episode_id, paths in seen.items():
        if len(paths) < 2:
            continue
        others = ", ".join(str(p) for p in paths if p != paths[0])
        for path in paths:
            problems.setdefault(path, []).append(
                f"E_DUPLICATE_EPISODE_ID at $.episode_id: id {episode_id!r} is also "
                f"used by {others}; ids are unique across the corpus"
            )
    return problems


def check_directory(
    root: Path,
    *,
    allow_draft: bool = False,
) -> list[CheckResult]:
    """Check every ``*.json`` under ``root``. Returns one result per file."""
    documents: list[tuple[Path, dict[str, Any]]] = []
    results: list[CheckResult] = []

    for path in _iter_episode_files(root):
        result = CheckResult(path=path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.errors.append(f"E_UNREADABLE at $: {exc}")
            results.append(result)
            continue

        if not isinstance(document, dict):
            result.errors.append("E_NOT_AN_OBJECT at $: episode documents are JSON objects")
            results.append(result)
            continue

        documents.append((path, document))

        schema_errors: list[Error] = validate_episode(document)
        if schema_errors:
            result.errors.append(format_errors(schema_errors))

        markers = find_todo_markers(document)
        if markers:
            result.draft = True
            if not allow_draft:
                joined = ", ".join(f"{p} ({m})" for p, m in markers)
                result.errors.append(
                    f"E_DRAFT: {len(markers)} TODO marker(s) remain: {joined}. "
                    "Fill them in, or pass --allow-draft if drafts are expected here."
                )

        if document.get("provenance") == "synthetic-fixture" and not in_fixture_dir(path):
            result.errors.append(
                "E_FIXTURE_OUTSIDE_FIXTURE_DIR at $.provenance: provenance is "
                f"'synthetic-fixture' but {path} is not inside a "
                f"{sorted(FIXTURE_DIR_NAMES)} directory; fixtures are not data and "
                "must not be committed where they can be read as real episodes"
            )

        results.append(result)

    for path, messages in _dedupe_ids(documents).items():
        for result in results:
            if result.path == path:
                result.errors.extend(messages)

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_episodes",
        description="Validate every episode document in a directory tree.",
    )
    parser.add_argument(
        "paths",
        type=Path,
        nargs="*",
        default=[DEFAULT_DIR],
        help=f"files or directories to check (default: {DEFAULT_DIR})",
    )
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="accept documents that still carry TODO markers",
    )
    args = parser.parse_args(argv)

    results: list[CheckResult] = []
    for path in args.paths:
        if not path.exists():
            print(f"error: {path} does not exist", file=sys.stderr)
            return 2
        results.extend(check_directory(path, allow_draft=args.allow_draft))

    if not results:
        print(f"no episode documents found under {', '.join(str(p) for p in args.paths)}")
        return 0

    drafts = 0
    failed = 0
    for result in results:
        if result.draft:
            drafts += 1
        if result.ok:
            suffix = "  (draft)" if result.draft else ""
            print(f"ok       {result.path}{suffix}")
            continue
        failed += 1
        print(f"FAIL     {result.path}")
        for message in result.errors:
            for line in message.splitlines():
                print(f"         {line}")

    total = len(results)
    print(f"\n{total - failed}/{total} ok", end="")
    if drafts:
        print(f", {drafts} draft(s)", end="")
    print()

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
