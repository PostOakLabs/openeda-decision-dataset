# SPDX-License-Identifier: Apache-2.0
"""Tests for the dataset metadata generator (W2.9).

Three claims are load-bearing, and each gets a test:

**The output is deterministic.** The CI gate diffs the committed artifacts
against a regeneration, so a value that changes between two runs -- a clock, an
interpreter version -- is not a staleness signal, it is noise that would make
the gate fail for a reason unrelated to the corpus.

**Drafts never reach the export, but they are accounted for.** A card that said
"0 episodes" without saying "3 drafts" would read as a bug rather than as the
corpus being young.

**The gate fails when it should.** A freshness check that only ever passes is
worse than none, because it looks like protection.

The generator is exercised through its own fixtures, not the repository's real
``episodes/`` tree, so these tests survive the seeds being filled in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from edi_schema import validate_episode

from tools import gen_dataset_meta as gen

__all__: list[str] = []


def _episode(
    episode_id: str,
    *,
    provenance: str = "reproduced",
    failure_class: str = "FAIL_TIMING",
    draft: bool = False,
) -> dict[str, Any]:
    """A schema-valid episode, optionally still carrying TODO markers.

    Enum fields cannot hold a marker -- ``TODO(expert)`` is not a valid
    ``failure_class`` -- so the draft flag only marks the free-text fields,
    which is exactly how the real seeds are written.
    """
    todo = "TODO(expert): "
    design = {
        "name": f"{todo}ibex" if draft else "ibex",
        "pdk": f"{todo}process node" if draft else "sky130",
    }
    episode: dict[str, Any] = {
        "episode_id": episode_id,
        "provenance": provenance,
        "design": design,
        "prior_state": {"stage": "synthesis", "metrics": {}},
        "post_state": {"stage": "cts", "metrics": {}},
        "observation": {
            "metric": "wns_ns",
            "value": -0.42,
            "target": 0.0,
            "severity": "degrading",
        },
        "hypothesis": f"{todo}clock skew dominated" if draft else "clock skew dominated",
        "candidates_considered": [
            {"intervention": "raise FP_CORE_UTIL", "rejected_because": None},
            {"intervention": "lower target density", "rejected_because": "worse congestion"},
        ],
        "chosen_intervention": {"parameter": "FP_CORE_UTIL", "before": "40", "after": "45"},
        "expert_assessment": "preferred",
        "rationale": f"{todo}it closed timing" if draft else "it closed timing",
        "confidence": 0.8,
        "failure_class": failure_class,
    }

    # edi-schema enforces these cross-field: a "reproduced" episode must pin the
    # commits and record the tool versions it was reproduced from. A fixture
    # that skipped them would be counted schema-invalid instead of admitted,
    # which would silently make every assertion below vacuous.
    if provenance == "reproduced":
        design["rtl_commit"] = "a" * 40
        design["pdk_commit"] = "b" * 40
        episode["environment"] = {
            "librelane_version": "2.4.0",
            "openroad_version": "2.0.0",
            "yosys_version": "0.36",
        }
    return episode


def _write_corpus(root: Path, episodes: list[dict[str, Any]]) -> Path:
    """Write ``episodes`` as one JSON file each under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    for episode in episodes:
        (root / f"{episode['episode_id']}.json").write_text(
            json.dumps(episode, indent=2) + "\n", encoding="utf-8"
        )
    return root


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the generator's repo-root paths at a scratch directory."""
    monkeypatch.setattr(gen, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gen, "CROISSANT_PATH", tmp_path / "croissant.json")
    monkeypatch.setattr(gen, "CARD_PATH", tmp_path / "DATASET_CARD.md")
    return tmp_path


def test_the_fixture_episode_is_schema_valid() -> None:
    """Guards the guard: if the fixture were invalid, every count below would
    be measuring the wrong thing."""
    assert list(validate_episode(_episode("EP-T-001"))) == []


def test_output_is_deterministic(repo: Path) -> None:
    corpus = _write_corpus(
        repo / "episodes",
        [_episode("EP-T-001"), _episode("EP-T-002", provenance="retrospective")],
    )
    first = gen.render_croissant(gen.build_dataset(corpus))
    second = gen.render_croissant(gen.build_dataset(corpus))
    assert first == second

    dataset = gen.build_dataset(corpus)
    assert gen.render_card(gen.corpus_stats(corpus, dataset), dataset) == gen.render_card(
        gen.corpus_stats(corpus, dataset), dataset
    )


def test_artifacts_carry_no_clock_or_interpreter_version(repo: Path) -> None:
    """A timestamp would make the committed file stale every day, and a Python
    version would make it differ between a dev machine and the runner. Either
    would turn the freshness gate into a coin flip."""
    corpus = _write_corpus(repo / "episodes", [_episode("EP-T-001")])
    dataset = gen.build_dataset(corpus)

    assert "datePublished" not in dataset
    card = gen.render_card(gen.corpus_stats(corpus, dataset), dataset)
    assert "generated on" not in card.lower()
    assert "generated at" not in card.lower()


def test_drafts_are_excluded_but_still_counted(repo: Path) -> None:
    corpus = _write_corpus(
        repo / "episodes",
        [_episode("EP-T-001"), _episode("EP-T-002", draft=True)],
    )
    dataset = gen.build_dataset(corpus)
    stats = gen.corpus_stats(corpus, dataset)

    assert stats["admitted"] == 1
    assert stats["excluded_drafts"] == 1
    assert stats["schema_invalid"] == 0
    assert stats["files_scanned"] == 2
    # The draft's id must not appear anywhere in the export.
    assert "EP-T-002" not in gen.render_croissant(dataset)


def test_counts_are_broken_out_by_provenance_and_failure_class(repo: Path) -> None:
    corpus = _write_corpus(
        repo / "episodes",
        [
            _episode("EP-T-001", provenance="reproduced"),
            _episode("EP-T-002", provenance="reproduced"),
            _episode("EP-T-003", provenance="retrospective", failure_class="FAIL_CONGESTION"),
        ],
    )
    dataset = gen.build_dataset(corpus)
    stats = gen.corpus_stats(corpus, dataset)

    assert dict(stats["by_provenance"]) == {"reproduced": 2, "retrospective": 1}
    assert dict(stats["by_failure_class"]) == {"FAIL_CONGESTION": 1, "FAIL_TIMING": 2}


def test_an_empty_corpus_still_produces_an_honest_card(repo: Path) -> None:
    """The current state of the repository: every episode is still a draft. The
    card must say so rather than rendering an empty table and looking broken."""
    corpus = _write_corpus(repo / "episodes", [_episode("EP-T-001", draft=True)])
    dataset = gen.build_dataset(corpus)
    card = gen.render_card(gen.corpus_stats(corpus, dataset), dataset)

    assert "Episodes admitted | 0" in card
    assert "Excluded as drafts | 1" in card
    assert "No episodes are admitted yet" in card


def test_check_passes_when_the_artifacts_are_fresh(repo: Path) -> None:
    corpus = _write_corpus(repo / "episodes", [_episode("EP-T-001")])
    assert gen.main([str(corpus)]) == 0
    assert gen.main(["--check", str(corpus)]) == 0


def test_check_fails_when_the_corpus_has_moved_on(repo: Path) -> None:
    corpus = _write_corpus(repo / "episodes", [_episode("EP-T-001")])
    assert gen.main([str(corpus)]) == 0

    # A new episode lands and nobody regenerates. That is the exact drift the
    # CI step exists to catch.
    _write_corpus(corpus, [_episode("EP-T-002", provenance="retrospective")])
    assert gen.main(["--check", str(corpus)]) == 1


def test_check_fails_when_an_artifact_is_missing(repo: Path) -> None:
    corpus = _write_corpus(repo / "episodes", [_episode("EP-T-001")])
    assert gen.main([str(corpus)]) == 0
    gen.CARD_PATH.unlink()
    assert gen.main(["--check", str(corpus)]) == 1


def test_check_reports_a_missing_corpus_directory(repo: Path) -> None:
    assert gen.main(["--check", str(repo / "does-not-exist")]) == 2


def test_the_real_corpus_regenerates_to_the_committed_artifact() -> None:
    """The repository's own artifacts must be up to date. This is the same gate
    CI runs, so a stale commit fails locally before it wastes a runner."""
    assert gen.main(["--check"]) == 0
