# SPDX-License-Identifier: Apache-2.0
"""Tests for the checked-in episode template.

The property that matters is that the template contains structure and nothing
else. A template that quietly acquired a number would be indistinguishable from
one someone filled in from experience, and there is no way to tell the
difference later. So it is asserted mechanically: every string in it is either
a TODO marker or one of a handful of scaffolded enum defaults.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from edi_schema import validate_episode

from tools import find_todo_markers, todo_marker
from tools.check_episodes import check_directory
from tools.new_episode import build_episode

EPISODES = Path(__file__).resolve().parent.parent / "episodes"
TEMPLATE = EPISODES / "templates" / "retrospective.template.json"

#: The only strings a scaffold may contain that are not TODO markers. Each is
#: either a fixed identifier or the least committal member of an enum.
SCAFFOLD_STRINGS = frozenset(
    {
        "https://postoaklabs.github.io/engineering-decision-schema/episode.schema.json",
        "retrospective",
        "degrading",
        "inconclusive",
        "FAIL_FLOW",
        "FAIL_CONGESTION",
        "FAIL_TIMING",
    }
)
_IDENTIFIER_PATHS = frozenset({"$.$schema", "$.episode_id"})


def _string_leaves(document: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(document, dict):
        for key, value in document.items():
            yield from _string_leaves(value, f"{path}.{key}")
    elif isinstance(document, list):
        for index, value in enumerate(document):
            yield from _string_leaves(value, f"{path}[{index}]")
    elif isinstance(document, str):
        yield path, document


def test_the_template_is_where_the_readme_says_it_is() -> None:
    assert TEMPLATE.is_file()


def test_the_template_matches_what_the_scaffolder_emits() -> None:
    """A hand-edited template that drifts from the tool is worse than none."""
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    rebuilt = build_episode(
        episode_id="EP-TEMPLATE-000",
        owner="expert",
        design_name=todo_marker("expert", "design name"),
        provenance="retrospective",
        failure_class="FAIL_FLOW",
        pdk=todo_marker("expert", "process node / PDK"),
    )
    assert template == rebuilt


def test_the_template_is_a_valid_draft() -> None:
    """Schema-valid, and a draft -- unfinished, not malformed."""
    document = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert validate_episode(document) == []

    results = check_directory(TEMPLATE, allow_draft=True)
    assert len(results) == 1
    assert results[0].draft is True
    assert results[0].errors == []


def test_the_template_carries_no_invented_content() -> None:
    document = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for leaf_path, value in _string_leaves(document):
        if leaf_path in _IDENTIFIER_PATHS:
            continue
        assert "TODO(" in value or value in SCAFFOLD_STRINGS, (
            f"{TEMPLATE.name}: {leaf_path} holds {value!r}, which is neither a TODO "
            "marker nor a scaffolded default"
        )

    # No measurements, and no confidence claim, in a skeleton.
    assert document["prior_state"]["metrics"] == {}
    assert document["post_state"]["metrics"] == {}
    assert document["confidence"] == 0.0


def test_every_template_marker_is_an_expert_marker() -> None:
    """Physical-design episodes are the domain expert's to fill in."""
    document = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    markers = find_todo_markers(document)
    assert markers
    assert {marker for _, marker in markers} == {"TODO(expert)"}
