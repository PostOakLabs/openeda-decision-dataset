# SPDX-License-Identifier: Apache-2.0
"""Tests for the episode scaffolder.

The load-bearing claim is that a scaffolded episode is a *valid* episode that
is honestly marked unfinished -- not an invalid one. So the first test here
runs a fresh scaffold through edi_schema.validate_episode and expects a clean
result, and the rest check that nothing mechanical was invented.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from edi_schema import validate_episode

from tools import find_todo_markers
from tools.new_episode import (
    DEFAULT_ASSESSMENT,
    DEFAULT_CONFIDENCE,
    DEFAULT_PROVENANCE,
    DEFAULT_SEVERITY,
    build_episode,
    main,
    next_episode_id,
    pick_stage,
    state_from_record,
)

FIXTURE_RUN = Path(__file__).resolve().parent / "fixtures" / "synthetic-run"


def test_a_fresh_scaffold_is_schema_valid() -> None:
    """A scaffold must validate. It is unfinished, not malformed."""
    episode = build_episode(
        episode_id="EP-IBEX-001",
        owner="expert",
        design_name="ibex",
        provenance="retrospective",
        failure_class="FAIL_TIMING",
        pdk="sky130",
    )
    errors = validate_episode(episode)
    assert errors == [], [str(e) for e in errors]


def test_judgment_fields_are_marked_not_invented() -> None:
    episode = build_episode(
        episode_id="EP-IBEX-001",
        owner="expert",
        design_name="ibex",
        provenance="retrospective",
        failure_class="FAIL_TIMING",
        pdk="sky130",
    )
    markers = dict(find_todo_markers(episode))
    for path in (
        "$.hypothesis",
        "$.rationale",
        "$.observation.metric",
        "$.observation.value",
        "$.observation.target",
        "$.chosen_intervention.parameter",
        "$.candidates_considered[0].intervention",
        "$.candidates_considered[1].rejected_because",
    ):
        assert path in markers, f"{path} should be marked TODO, got {markers}"
        assert markers[path] == "TODO(expert)"


def test_enum_defaults_are_the_least_committal_member() -> None:
    """Enums cannot hold a marker, so they default to 'no claim yet'."""
    episode = build_episode(
        episode_id="EP-IBEX-001",
        owner="expert",
        design_name="ibex",
        provenance=DEFAULT_PROVENANCE,
        failure_class="FAIL_FLOW",
        pdk="sky130",
    )
    assert episode["observation"]["severity"] == DEFAULT_SEVERITY
    assert episode["expert_assessment"] == DEFAULT_ASSESSMENT
    # 0.0 rather than any other number: a scaffolded confidence is "not
    # assessed", and any other value would be a fabricated judgment.
    assert episode["confidence"] == DEFAULT_CONFIDENCE


def test_exactly_one_candidate_is_the_chosen_one() -> None:
    """The schema cannot express this; the Python validator does."""
    episode = build_episode(
        episode_id="EP-IBEX-001",
        owner="expert",
        design_name="ibex",
        provenance="retrospective",
        failure_class="FAIL_FLOW",
        pdk="sky130",
    )
    chosen = [c for c in episode["candidates_considered"] if c["rejected_because"] is None]
    assert len(chosen) == 1


def test_retrospective_episodes_carry_no_environment_or_pins() -> None:
    """No run artifact means no tool versions to claim, so none are claimed."""
    episode = build_episode(
        episode_id="EP-IBEX-001",
        owner="expert",
        design_name="ibex",
        provenance="retrospective",
        failure_class="FAIL_FLOW",
        pdk="sky130",
    )
    assert "environment" not in episode
    assert "run_manifest_ref" not in episode
    assert episode["design"] == {"name": "ibex", "pdk": "sky130"}


def test_next_episode_id_counts_per_domain(tmp_path: Path) -> None:
    assert next_episode_id(tmp_path, "IBEX") == "EP-IBEX-001"

    (tmp_path / "a.json").write_text(json.dumps({"episode_id": "EP-IBEX-001"}), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"episode_id": "EP-IBEX-007"}), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"episode_id": "EP-SPM-004"}), encoding="utf-8")
    assert next_episode_id(tmp_path, "IBEX") == "EP-IBEX-008"
    assert next_episode_id(tmp_path, "SPM") == "EP-SPM-005"


def test_next_episode_id_ignores_unreadable_and_unrelated_files(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("EP-IBEX-999", encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert next_episode_id(tmp_path, "IBEX") == "EP-IBEX-001"


# --------------------------------------------------------------------------
# Scaffolding from a real run
# --------------------------------------------------------------------------


def _run_dir_with_manifest(tmp_path: Path) -> Path:
    """The synthetic fixture plus the manifest flow/run.py would have written."""
    run_dir = tmp_path / "RUN_2026-08-28_00-00-00"
    shutil.copytree(FIXTURE_RUN, run_dir)
    manifest = {
        "design": {"name": "ibex", "rtl_commit": "8b8ee086aef72e0833b7f0493d9d33f1e4d3c8e2"},
        "environment": {
            "librelane_version": "3.0.11",
            "openroad_version": "v2.0-12345",
            "yosys_version": "Yosys 0.40",
        },
        "pdk": {"name": "sky130", "commit": "8afc8346a57fe1ab7934ba5a6056ea8b43078e71"},
        "inputs": {"config_hash": "a" * 64},
        "run_id": run_dir.name,
        "started_at": "2026-08-28T00:00:00+00:00",
        "host": {"os": "Linux", "cpu": "x86_64"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return run_dir


def test_from_run_fills_provenance_and_pins(tmp_path: Path) -> None:
    run_dir = _run_dir_with_manifest(tmp_path)
    out = tmp_path / "episode.json"

    code = main(
        [
            "--from-run",
            str(run_dir),
            "--failure-class",
            "FAIL_CONGESTION",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    episode = json.loads(out.read_text(encoding="utf-8"))

    assert episode["provenance"] == "reproduced"
    assert episode["design"]["rtl_commit"] == "8b8ee086aef72e0833b7f0493d9d33f1e4d3c8e2"
    assert episode["design"]["pdk_commit"] == "8afc8346a57fe1ab7934ba5a6056ea8b43078e71"
    assert episode["environment"]["librelane_version"] == "3.0.11"
    assert episode["run_manifest_ref"] == run_dir.name
    assert episode["failure_class"] == "FAIL_CONGESTION"
    # A reproduced episode is exactly the case the schema's if/then polices.
    assert validate_episode(episode) == []


def test_from_run_takes_states_from_the_named_stages(tmp_path: Path) -> None:
    run_dir = _run_dir_with_manifest(tmp_path)
    out = tmp_path / "episode.json"

    code = main(
        [
            "--from-run",
            str(run_dir),
            "--prior-stage",
            "global_placement",
            "--post-stage",
            "detailed_routing",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    episode = json.loads(out.read_text(encoding="utf-8"))

    assert episode["prior_state"]["stage"] == "global_placement"
    assert episode["post_state"]["stage"] == "detailed_routing"
    # Wirelength is not measured at global placement in this fixture and so
    # must be absent, not zero.
    assert "wirelength_um" not in episode["prior_state"]["metrics"]
    assert "wirelength_um" in episode["post_state"]["metrics"]
    assert episode["prior_state"]["metrics"]["utilization"] > 0


def test_state_from_record_drops_identity_keys() -> None:
    state = state_from_record(
        {
            "stage": "cts",
            "step_id": "OpenROAD.CTS",
            "step_dir": "35-OpenROAD-CTS",
            "index": 35,
            "wns_ns": -0.5,
            "cell_count": 12345,
        }
    )
    assert state == {"stage": "cts", "metrics": {"wns_ns": -0.5, "cell_count": 12345}}


def test_pick_stage_matches_repeated_stages_by_base_name() -> None:
    """Repeated steps are disambiguated as sta_mid_pnr / sta_mid_pnr.2."""
    records = [
        {"stage": "sta_mid_pnr", "wns_ns": -1.0},
        {"stage": "sta_mid_pnr.2", "wns_ns": -0.25},
    ]
    assert pick_stage(records, "sta_mid_pnr", occurrence="first")["wns_ns"] == -1.0
    assert pick_stage(records, "sta_mid_pnr", occurrence="last")["wns_ns"] == -0.25
    with pytest.raises(KeyError, match="available:"):
        pick_stage(records, "nonexistent", occurrence="last")


def test_from_run_without_a_manifest_is_refused(tmp_path: Path) -> None:
    bare = tmp_path / "RUN_bare"
    bare.mkdir()
    code = main(["--from-run", str(bare), "--out", str(tmp_path / "ep.json")])
    assert code == 2


def test_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    out = tmp_path / "episode.json"
    out.write_text("{}", encoding="utf-8")
    code = main(["--design", "ibex", "--out", str(out)])
    assert code == 1
    assert out.read_text(encoding="utf-8") == "{}"

    assert main(["--design", "ibex", "--out", str(out), "--force"]) == 0
