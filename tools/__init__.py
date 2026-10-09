# SPDX-License-Identifier: Apache-2.0
"""Episode authoring tools.

The episodes themselves are written by an expert, not generated. These tools
handle the parts that are mechanical -- ids, provenance, state snapshots taken
from a real run -- and mark the parts that are judgment, so that nothing that
looks finished is actually empty.

``new_episode.py``   scaffolds one episode, prefilled where it can be.
``check_episodes.py`` refuses to let a draft be mistaken for a filled-in one.

The marker convention is ``TODO(expert)`` / ``TODO(maintainer)`` inside the string
value of a judgment field. It lives in a string rather than in a sibling key
because the episode schema is closed (``additionalProperties: false``), so
there is nowhere else to put it -- and because a marker inside the value
cannot be separated from the value by accident.

Enum fields cannot carry a marker: ``TODO(expert)`` is not a valid
``failure_class``. Those are scaffolded to a documented default instead, which
is why the checker treats *any* TODO marker in a document as making the whole
document a draft -- a scaffolded episode always has markers somewhere.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: The domain expert owns the physical-design episodes; the maintainer owns the
#: proving episodes (zkprof-harness). Same schema, same convention, different
#: name in the marker.
OWNERS: tuple[str, ...] = ("expert", "maintainer")

_TODO_RE = re.compile(r"TODO\((?:expert|maintainer)\)")

__all__ = ["OWNERS", "find_todo_markers", "is_todo", "todo_marker"]


def todo_marker(owner: str, what: str) -> str:
    """A marker naming the person who has to supply this value."""
    if owner not in OWNERS:
        msg = f"unknown owner {owner!r}; expected one of {', '.join(OWNERS)}"
        raise ValueError(msg)
    return f"TODO({owner}): {what}"


def is_todo(value: Any) -> bool:
    """True if a value is, or contains, a TODO marker."""
    return isinstance(value, str) and _TODO_RE.search(value) is not None


def find_todo_markers(document: Any, path: str = "$") -> list[tuple[str, str]]:
    """Every TODO marker in a decoded document, as ``(path, marker)`` pairs.

    Paths are JSON-pointer-ish and walk the document top to bottom, which is
    the order a human wants to fill it in.
    """
    found: list[tuple[str, str]] = []
    if isinstance(document, Mapping):
        for key, value in document.items():
            found.extend(find_todo_markers(value, f"{path}.{key}"))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            found.extend(find_todo_markers(value, f"{path}[{index}]"))
    elif is_todo(document):
        match = _TODO_RE.search(document)
        assert match is not None
        found.append((path, match.group(0)))
    return found
