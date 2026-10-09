# SPDX-License-Identifier: Apache-2.0
"""Tests for the episode checker.

The checker exists for the rules the schema cannot express. Each test here
corresponds to one of them: drafts, corpus-wide id uniqueness, and keeping
synthetic fixtures out of the real episode set.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.check_episodes import check_directory, main


def _write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def _filled(episode_id: str = "EP-IBEX-001", **overrides) -> dict:
    """A complete episode with no TODO markers: what a finished one looks like."""
    episode = {
        "$schema": "https://postoaklabs.github.io/engineering-decision-schema/episode.schema.json",
        "episode_id": episode_id,
        "provenance": "retrospective",
        "design": {"name": "ibex", "pdk": "sky130"},
        "prior_state": {"stage": "global_placement", "metrics": {"utilization": 0.72}},
        "post_state": {"stage": "detailed_routing", "metrics": {"utilization": 0.61}},
        "observation": {
            "metric": "congestion_pct",
            "value": 12.5,
            "target": 5.0,
            "severity": "blocking",
        },
        "hypothesis": "The macro placement funnels routing through one channel.",
        "candidates_considered": [
            {"intervention": "Spread the macros along the top edge.", "rejected_because": None},
            {
                "intervention": "Lower FP_CORE_UTIL to 60.",
                "rejected_because": "Area budget was already fixed with the package.",
            },
        ],
        "chosen_intervention": {
            "parameter": "macro placement",
            "before": "clustered",
            "after": "spread along top edge",
        },
        "expert_assessment": "preferred",
        "rationale": "Area was fixed; macro placement was the only free variable.",
        "confidence": 0.8,
        "failure_class": "FAIL_CONGESTION",
    }
    episode.update(overrides)
    return episode


def test_a_finished_episode_passes(tmp_path: Path) -> None:
    _write(tmp_path / "EP-IBEX-001.json", _filled())
    results = check_directory(tmp_path)
    assert [r.errors for r in results] == [[]]


def test_a_draft_is_rejected_unless_drafts_are_allowed(tmp_path: Path) -> None:
    episode = _filled()
    episode["hypothesis"] = "TODO(expert): your causal reading"
    _write(tmp_path / "EP-IBEX-001.json", episode)

    results = check_directory(tmp_path)
    assert len(results) == 1
    assert results[0].draft is True
    assert any("E_DRAFT" in message for message in results[0].errors)

    allowed = check_directory(tmp_path, allow_draft=True)
    assert allowed[0].errors == []
    assert allowed[0].draft is True


def test_duplicate_ids_are_reported_on_both_files(tmp_path: Path) -> None:
    _write(tmp_path / "a.json", _filled("EP-IBEX-001"))
    _write(tmp_path / "b.json", _filled("EP-IBEX-001"))

    results = {r.path.name: r for r in check_directory(tmp_path)}
    for name in ("a.json", "b.json"):
        assert any("E_DUPLICATE_EPISODE_ID" in m for m in results[name].errors)


def test_distinct_ids_are_fine(tmp_path: Path) -> None:
    _write(tmp_path / "a.json", _filled("EP-IBEX-001"))
    _write(tmp_path / "b.json", _filled("EP-IBEX-002"))
    assert all(r.errors == [] for r in check_directory(tmp_path))


def test_a_fixture_outside_a_fixture_directory_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path / "episodes" / "EP-IBEX-001.json", _filled(provenance="synthetic-fixture"))
    results = check_directory(tmp_path)
    assert any("E_FIXTURE_OUTSIDE_FIXTURE_DIR" in m for r in results for m in r.errors)


def test_a_fixture_inside_a_fixture_directory_is_accepted(tmp_path: Path) -> None:
    _write(
        tmp_path / "fixtures" / "EP-IBEX-001.json",
        _filled(provenance="synthetic-fixture"),
    )
    assert all(r.errors == [] for r in check_directory(tmp_path))


def test_the_fixture_rule_matches_directory_components_not_substrings(tmp_path: Path) -> None:
    """A scratch path that merely contains the word is not a fixtures directory."""
    # pytest's own tmp_path is named after the test, so a substring rule would
    # see "fixture" in the directory name and wave this through.
    misleading = tmp_path / "a-fixture-adjacent-place"
    _write(misleading / "EP-IBEX-001.json", _filled(provenance="synthetic-fixture"))
    results = check_directory(tmp_path)
    assert any("E_FIXTURE_OUTSIDE_FIXTURE_DIR" in m for r in results for m in r.errors)

    proper = tmp_path / "fixtures"
    _write(proper / "EP-IBEX-002.json", _filled("EP-IBEX-002", provenance="synthetic-fixture"))
    assert check_directory(proper)[0].errors == []


def test_unreadable_json_is_reported_not_raised(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    results = check_directory(tmp_path)
    assert len(results) == 1
    assert any("E_UNREADABLE" in m for m in results[0].errors)


def test_a_json_array_is_reported_not_raised(tmp_path: Path) -> None:
    (tmp_path / "array.json").write_text("[]", encoding="utf-8")
    results = check_directory(tmp_path)
    assert any("E_NOT_AN_OBJECT" in m for m in results[0].errors)


def test_exit_code_is_1_when_anything_fails(tmp_path: Path) -> None:
    _write(tmp_path / "broken.json", _filled())
    (tmp_path / "broken.json").write_text("{}", encoding="utf-8")
    assert main([str(tmp_path)]) == 1


def test_exit_code_is_0_on_a_clean_corpus(tmp_path: Path) -> None:
    _write(tmp_path / "a.json", _filled("EP-IBEX-001"))
    assert main([str(tmp_path)]) == 0


def test_missing_path_is_a_usage_error(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope")]) == 2
