# SPDX-License-Identifier: Apache-2.0
"""Tests for the per-stage metric extractor.

These run against the synthetic fixtures in tests/fixtures/ -- see the README
there. They assert the *shape* of the extraction: naming, ordering, unit
renaming, and above all that a metric which was not measured is absent rather
than zero. That last property is the one that keeps an episode honest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from extractors.metrics_from_state import (
    discover_step_dirs,
    extract_run,
    normalize_metrics,
    scrape_overflow,
    slug_to_step_id,
    stage_name,
    write_jsonl,
)

FIXTURES = Path(__file__).parent / "fixtures"
RUN_OK = FIXTURES / "synthetic-run"
RUN_FAILED = FIXTURES / "synthetic-run-failed"


# --------------------------------------------------------------------------
# Naming
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("OpenROAD-GlobalPlacement", "OpenROAD.GlobalPlacement"),
        ("Yosys-Synthesis", "Yosys.Synthesis"),
        ("Verilator-Lint", "Verilator.Lint"),
    ],
)
def test_slug_recovers_step_id(slug: str, expected: str) -> None:
    assert slug_to_step_id(slug) == expected


@pytest.mark.parametrize(
    ("step_id", "expected"),
    [
        ("OpenROAD.GlobalPlacement", "global_placement"),
        ("OpenROAD.STAMidPNR", "sta_mid_pnr"),
        ("OpenROAD.DetailedRouting", "detailed_routing"),
        ("Yosys.Synthesis", "synthesis"),
        ("Checker.TrDRC", "tr_drc"),
        ("Magic.DRC", "drc"),
    ],
)
def test_stage_name_is_short_and_snake_case(step_id: str, expected: str) -> None:
    assert stage_name(step_id) == expected


def test_step_dirs_are_found_in_flow_order() -> None:
    found = discover_step_dirs(RUN_OK)
    ordinals = [item[0] for item in found]
    assert ordinals == sorted(ordinals)
    slugs = [item[1] for item in found]
    # `final/` is a snapshot directory, not a step; it must not appear.
    assert "final" not in slugs
    assert "OpenROAD-STAMidPNR" in slugs


# --------------------------------------------------------------------------
# Metric projection
# --------------------------------------------------------------------------


def test_unmeasured_metrics_are_absent_not_zero() -> None:
    """The load-bearing invariant of the whole extractor."""
    metrics = normalize_metrics({"design__instance__count": 10}, {})
    assert "wns_ns" not in metrics
    assert "tns_ns" not in metrics
    assert "wirelength_um" not in metrics
    assert "drc_count" not in metrics
    assert "lvs_status" not in metrics
    assert "overflow_edge_count" not in metrics
    assert "overflow_pct" not in metrics


def test_metric_names_carry_their_units() -> None:
    metrics = normalize_metrics(
        {
            "timing__setup__wns": -1.5,
            "timing__setup__tns": -120.0,
            "route__wirelength__estimated": 400000.0,
            "design__instance__count": 10600,
            "design__instance__utilization": 0.22,
        },
        {},
    )
    assert metrics["wns_ns"] == -1.5
    assert metrics["tns_ns"] == -120.0
    assert metrics["wirelength_um"] == 400000.0
    assert metrics["cell_count"] == 10600
    assert metrics["utilization"] == 0.22


def test_lvs_zero_errors_is_clean_and_absent_means_not_run() -> None:
    assert normalize_metrics({"design__lvs_error__count": 0}, {})["lvs_status"] == "clean"
    assert normalize_metrics({"design__lvs_error__count": 5}, {})["lvs_status"] == "failed"
    assert "lvs_status" not in normalize_metrics({}, {})


def test_drc_prefers_magic_and_falls_back_to_klayout() -> None:
    assert normalize_metrics({"magic__drc_error__count": 7}, {})["drc_count"] == 7
    assert normalize_metrics({"klayout__drc_error__count": 3}, {})["drc_count"] == 3
    # Both present -> Magic wins, values are not added together.
    assert (
        normalize_metrics({"magic__drc_error__count": 7, "klayout__drc_error__count": 3}, {})[
            "drc_count"
        ]
        == 7
    )


def test_cumulative_state_wins_over_openroad_metrics() -> None:
    """The state is what LibreLane carried forward; the OR report is a snapshot."""
    metrics = normalize_metrics(
        {"timing__setup__wns": -0.5},
        {"timing__setup__wns": -9.0},
    )
    assert metrics["wns_ns"] == -0.5


def test_openroad_only_metrics_still_surface() -> None:
    metrics = normalize_metrics({}, {"design__core__area": 250000.0})
    assert metrics["core_area_um2"] == 250000.0


def test_infinity_survives_as_a_string() -> None:
    """OpenROAD reports out-of-range timing as "Infinity", not as a number."""
    metrics = normalize_metrics({}, {"timing__setup__wns": "Infinity"})
    assert metrics["wns_ns"] == "Infinity"


def test_booleans_are_not_measurements() -> None:
    assert "utilization" not in normalize_metrics({"design__instance__utilization": True}, {})


# --------------------------------------------------------------------------
# Overflow scraping
# --------------------------------------------------------------------------


def test_overflow_is_scraped_from_the_step_log() -> None:
    value, pattern = scrape_overflow(RUN_OK / "39-OpenROAD-GlobalRouting")
    assert value == 1234.0
    assert pattern == "total_overflow"


def test_overflow_falls_back_to_a_congestion_percentage() -> None:
    value, pattern = scrape_overflow(RUN_FAILED / "39-OpenROAD-GlobalRouting")
    assert value == 87.0
    assert pattern == "congestion_pct"


def test_overflow_is_absent_when_the_log_says_nothing() -> None:
    step_dir = RUN_OK / "28-OpenROAD-GlobalPlacement"
    # Guard against this test passing for the wrong reason. A missing log also
    # yields (None, None), so without this the test cannot distinguish "the
    # log said nothing" from "there was no log to read".
    assert any(step_dir.glob("*.log")), f"no step log in fixture {step_dir}"
    value, pattern = scrape_overflow(step_dir)
    assert value is None
    assert pattern is None


@pytest.mark.parametrize("run_dir", [RUN_OK, RUN_FAILED])
def test_every_fixture_step_dir_carries_a_committed_log(run_dir: Path) -> None:
    """Fixture step logs must be in the repository, not just on someone's disk.

    `.gitignore` excludes `*.log` so real LibreLane run output stays out. If a
    fixture log is not explicitly un-ignored, `scrape_overflow` finds nothing
    and returns `(None, None)` -- which is indistinguishable from a log that
    genuinely says nothing. The suite then passes locally, where the file
    happens to exist, and fails in CI, where the checkout does not have it.
    """
    for _ordinal, _slug, step_dir in discover_step_dirs(run_dir):
        assert any(step_dir.glob("*.log")), f"no step log in fixture {step_dir}"


# --------------------------------------------------------------------------
# Whole-run extraction
# --------------------------------------------------------------------------


def test_extract_run_produces_one_record_per_step() -> None:
    records = extract_run(RUN_OK)
    assert len(records) == len(discover_step_dirs(RUN_OK))


def test_repeated_step_ids_get_distinct_stage_labels() -> None:
    stages = [r["stage"] for r in extract_run(RUN_OK)]
    assert stages.count("sta_mid_pnr") == 1
    assert "sta_mid_pnr.2" in stages
    assert len(stages) == len(set(stages))


def test_metrics_accumulate_across_stages() -> None:
    by_stage = {r["stage"]: r for r in extract_run(RUN_OK)}
    # Timing first appears at CTS; it is absent at floorplan, not zero.
    assert "wns_ns" not in by_stage["floorplan"]
    assert "wns_ns" in by_stage["cts"]
    # Wirelength only exists once routing has happened.
    assert "wirelength_um" not in by_stage["global_placement"]
    assert "wirelength_um" in by_stage["global_routing"]
    # The second STA run improved on the first.
    assert by_stage["sta_mid_pnr.2"]["wns_ns"] > by_stage["sta_mid_pnr"]["wns_ns"]


def test_failed_run_records_what_it_measured_and_nothing_more() -> None:
    by_stage = {r["stage"]: r for r in extract_run(RUN_FAILED)}
    routing = by_stage["global_routing"]
    assert routing["utilization"] == 0.85
    assert routing["overflow_pct"] == 87.0
    # Never got to routing detail, DRC, or timing analysis.
    assert "drc_count" not in routing
    assert "wns_ns" not in routing
    assert "cell_count" not in routing


def test_records_are_json_serialisable_and_line_delimited(tmp_path: Path) -> None:
    destination = tmp_path / "metrics.jsonl"
    count = write_jsonl(extract_run(RUN_OK), destination)
    lines = destination.read_text(encoding="utf-8").splitlines()
    assert count == len(lines) > 0
    for line in lines:
        assert json.loads(line)["stage"]
