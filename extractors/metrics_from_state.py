#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""LibreLane run directory -> one metrics record per flow stage.

    python -m extractors.metrics_from_state <run_dir> [-o metrics.jsonl]

LibreLane writes a ``<NN>-<Step-Id>/`` directory per step. Each one holds a
``state_out.json`` whose ``metrics`` object is the *cumulative* design state
after that step, plus (for OpenROAD steps) an ``or_metrics_out.json`` with the
metric names OpenROAD itself reports. Reading those in directory order gives
the state of the design at every stage of the flow, which is exactly what an
episode's ``prior_state`` and ``post_state`` need.

Output is JSON Lines: one object per stage, in flow order. A metric that was
not measured at a stage is **absent from the record, never reported as zero**.
That distinction is the whole point -- a stage that never ran LVS is not a
stage that passed LVS.

The overflow figure is the one metric neither state file carries, so it is
scraped from the step log. See ``OVERFLOW_PATTERNS`` and the note on it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "OVERFLOW_PATTERNS",
    "StageRecord",
    "discover_step_dirs",
    "extract_run",
    "main",
    "metrics_from_run_dir",
    "normalize_metrics",
    "scrape_overflow",
    "stage_name",
]

# --------------------------------------------------------------------------
# Metric name mapping
# --------------------------------------------------------------------------
#
# Left: the name this repository uses, with the unit in the key (the episode
# schema requires units in metric key names). Right: the LibreLane metric keys
# to try, in order -- the first one present wins.
#
# The LibreLane keys below were read out of LibreLane 3.0.11's metric library
# (librelane/common/metrics/library.py) and the steps that emit them. They are
# not guessed: every one is a real key that a real run produces.
METRIC_SOURCES: dict[str, tuple[str, ...]] = {
    "wns_ns": ("timing__setup__wns",),
    "tns_ns": ("timing__setup__tns",),
    "hold_wns_ns": ("timing__hold__wns",),
    "hold_tns_ns": ("timing__hold__tns",),
    "setup_violations": ("timing__setup_vio__count",),
    "hold_violations": ("timing__hold_vio__count",),
    "utilization": ("design__instance__utilization",),
    "wirelength_um": ("route__wirelength__estimated",),
    "cell_count": ("design__instance__count",),
    "core_area_um2": ("design__core__area",),
    "die_area_um2": ("design__die__area",),
    "ir_drop_worst_v": ("ir__drop__worst", "design_powergrid__drop__worst"),
    "antenna_violating_nets": ("antenna__violating__nets",),
}

# DRC is reported by whichever DRC tool ran. Prefer Magic (the default
# streamout/checker for sky130), fall back to KLayout.
DRC_SOURCES: tuple[str, ...] = (
    "magic__drc_error__count",
    "klayout__drc_error__count",
)

# LVS has no "status" metric in LibreLane; there is only an error count. Zero
# means LVS ran and the layout matched. Absent means LVS has not run yet.
LVS_ERROR_KEY = "design__lvs_error__count"

# --------------------------------------------------------------------------
# Overflow scraping
# --------------------------------------------------------------------------
#
# Neither state_out.json nor or_metrics_out.json carries routing overflow, so
# the only place it appears is the step log. OpenROAD's wording for it is not
# part of any stable interface, so this is a tolerant, ordered list of patterns
# rather than one precise regex -- and if none of them match, the metric is
# simply absent, which is the honest outcome.
#
# The first pattern that matches wins. Add patterns here rather than loosening
# the existing ones: an over-loose pattern is how an unrelated number in a log
# ends up recorded as a measurement.
OVERFLOW_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "total_overflow",
        re.compile(r"total\s+overflow\s*[:=]?\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE),
    ),
    (
        "grt_overflow",
        re.compile(
            r"\[(?:WARNING|ERROR)\s+GRT-\d+\][^\n]*?overflow[^\n]*?(-?\d+(?:\.\d+)?)\s*%?",
            re.IGNORECASE,
        ),
    ),
    (
        "congestion_pct",
        re.compile(r"congestion\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
    ),
)

# --------------------------------------------------------------------------
# Step directory discovery
# --------------------------------------------------------------------------

_STEP_DIR_RE = re.compile(r"^(\d+)-(.+)$")

# Directories LibreLane creates in a run directory that are not steps.
_NON_STEP_DIRS = {"final", "tmp", "logs", "reports", "error", "warning"}


@dataclass(frozen=True)
class StageRecord:
    """One flow stage: its identity plus the metrics measured at that point."""

    step_id: str
    stage: str
    step_dir: str
    index: int
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "stage": self.stage,
            "step_id": self.step_id,
            "step_dir": self.step_dir,
            "index": self.index,
        }
        out.update(self.metrics)
        return out


def slug_to_step_id(slug: str) -> str:
    """``OpenROAD-GlobalPlacement`` -> ``OpenROAD.GlobalPlacement``.

    LibreLane builds step directories as ``f"{ordinal}-{slugify(step.id)}"``,
    and slugify turns dots into hyphens. Recovering the dot form gives back the
    step id, which is what a human recognises and what the docs use.
    """
    return slug.replace("-", ".", 1) if "." not in slug else slug


def stage_name(step_id: str) -> str:
    """``OpenROAD.GlobalPlacement`` -> ``global_placement``.

    The tool-namespace prefix is dropped: the episode schema's ``stage`` field
    uses short flow-stage labels, and the namespace is redundant with
    ``step_id``, which is kept alongside it.
    """
    tail = step_id.rsplit(".", 1)[-1]
    snake = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", tail)
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", snake)
    return snake.lower()


def discover_step_dirs(run_dir: Path) -> list[tuple[int, str, Path]]:
    """Return ``(ordinal, slug, path)`` for every step directory, in flow order."""
    found: list[tuple[int, str, Path]] = []
    if not run_dir.is_dir():
        raise NotADirectoryError(run_dir)
    for child in run_dir.iterdir():
        if not child.is_dir() or child.name in _NON_STEP_DIRS:
            continue
        match = _STEP_DIR_RE.match(child.name)
        if match is None:
            continue
        found.append((int(match.group(1)), match.group(2), child))
    found.sort(key=lambda item: item[0])
    return found


# --------------------------------------------------------------------------
# Reading what a step produced
# --------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_state_metrics(step_dir: Path) -> dict[str, Any]:
    """The cumulative design metrics recorded in ``state_out.json``."""
    document = _read_json(step_dir / "state_out.json")
    if not isinstance(document, Mapping):
        return {}
    metrics = document.get("metrics")
    return dict(metrics) if isinstance(metrics, Mapping) else {}


def load_or_metrics(step_dir: Path) -> dict[str, Any]:
    """OpenROAD's own ``-metrics`` output for this step, when present."""
    document = _read_json(step_dir / "or_metrics_out.json")
    return dict(document) if isinstance(document, Mapping) else {}


def scrape_overflow(step_dir: Path) -> tuple[float | None, str | None]:
    """Best-effort routing overflow from the step log.

    Returns ``(value, pattern_name)``. ``(None, None)`` when nothing matched,
    which callers should turn into an absent key rather than a zero.
    """
    log_path = step_dir / f"{step_dir.name.split('-', 1)[-1]}.log"
    candidates = [log_path]
    # Some steps nest logs; check anything that looks like a log as a fallback.
    candidates.extend(sorted(p for p in step_dir.glob("*.log") if p != log_path))
    for path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, pattern in OVERFLOW_PATTERNS:
            match = pattern.search(text)
            if match is not None:
                try:
                    return float(match.group(1)), name
                except ValueError:
                    continue
    return None, None


def _as_number(value: Any) -> float | int | str | None:
    """Metrics are numbers or strings; anything else is not a measurement."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        # OpenROAD reports out-of-range values as the strings "Infinity" and
        # "-Infinity". They are real measurements, so they survive as strings
        # rather than being silently dropped or turned into a number.
        return value
    return None


def normalize_metrics(
    state_metrics: Mapping[str, Any],
    or_metrics: Mapping[str, Any],
    overflow: float | None = None,
    overflow_pattern: str | None = None,
) -> dict[str, Any]:
    """Project LibreLane's metric dictionary onto this repository's names.

    Absent stays absent. A key is added only when a source actually carried it.
    """
    merged: dict[str, Any] = {}
    merged.update(or_metrics)
    # The cumulative state wins over the per-step OpenROAD report: it is the
    # value LibreLane itself carried forward.
    merged.update(state_metrics)

    out: dict[str, Any] = {}
    for target, sources in METRIC_SOURCES.items():
        for source in sources:
            if source in merged:
                value = _as_number(merged[source])
                if value is not None:
                    out[target] = value
                break

    for source in DRC_SOURCES:
        if source in merged:
            value = _as_number(merged[source])
            if isinstance(value, (int, float)):
                out["drc_count"] = int(value) if float(value).is_integer() else value
                break

    if LVS_ERROR_KEY in merged:
        errors = _as_number(merged[LVS_ERROR_KEY])
        if isinstance(errors, (int, float)):
            out["lvs_status"] = "clean" if float(errors) == 0 else "failed"

    if overflow is not None:
        # The overflow figure comes from a log scrape whose meaning depends on
        # the matched pattern; the episode schema insists units live in the key
        # name. The total/grt patterns are EDGE counts, the congestion pattern
        # is a PERCENT -- two different quantities must not share one bare
        # `overflow` key (EDA-3), or a 1234-edge count is compared to an 87%
        # as commensurable.
        if overflow_pattern in ("total_overflow", "grt_overflow"):
            out["overflow_edge_count"] = overflow
        elif overflow_pattern == "congestion_pct":
            out["overflow_pct"] = overflow
        else:
            # Unknown pattern: record it under neither unit-bearing key, since
            # we cannot say what it measures. Honest absence beats a mislabelled
            # number.
            pass

    return out


# --------------------------------------------------------------------------
# Run-level extraction
# --------------------------------------------------------------------------


def metrics_from_run_dir(
    run_dir: Path,
    *,
    with_overflow: bool = True,
) -> list[StageRecord]:
    """Extract one :class:`StageRecord` per step directory in ``run_dir``."""
    records: list[StageRecord] = []
    used_stage_names: dict[str, int] = {}

    for ordinal, slug, path in discover_step_dirs(run_dir):
        step_id = slug_to_step_id(slug)
        base = stage_name(step_id)
        seen = used_stage_names.get(base, 0) + 1
        used_stage_names[base] = seen
        # Several steps share an id in the Classic flow (OpenROAD.STAMidPNR
        # runs four times). A stage label that collided would make "the state
        # at sta_mid_pnr" ambiguous, so repeats get an explicit suffix.
        stage = base if seen == 1 else f"{base}.{seen}"

        overflow: float | None = None
        overflow_pattern: str | None = None
        if with_overflow:
            overflow, overflow_pattern = scrape_overflow(path)

        records.append(
            StageRecord(
                step_id=step_id,
                stage=stage,
                step_dir=path.name,
                index=ordinal,
                metrics=normalize_metrics(
                    load_state_metrics(path),
                    load_or_metrics(path),
                    overflow,
                    overflow_pattern,
                ),
            )
        )
    return records


def extract_run(run_dir: Path, *, with_overflow: bool = True) -> list[dict[str, Any]]:
    """Same as :func:`metrics_from_run_dir`, as plain dicts ready to serialize."""
    return [r.to_record() for r in metrics_from_run_dir(run_dir, with_overflow=with_overflow)]


def write_jsonl(records: Iterable[Mapping[str, Any]], destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=False) + "\n")
            count += 1
    return count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="metrics_from_state",
        description="Extract per-stage metrics from a LibreLane run directory.",
    )
    parser.add_argument("run_dir", type=Path, help="LibreLane run directory")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write JSON Lines here (default: <run_dir>/metrics.jsonl)",
    )
    parser.add_argument(
        "--no-overflow",
        action="store_true",
        help="Skip the log scrape for routing overflow (faster, and avoids "
        "recording a number scraped from an unrecognised log format).",
    )
    parser.add_argument(
        "--jsonl-only",
        action="store_true",
        help="Write no summary to stdout (for piping).",
    )
    args = parser.parse_args(argv)

    if not args.run_dir.is_dir():
        print(f"error: not a directory: {args.run_dir}", file=sys.stderr)
        return 2

    records = extract_run(args.run_dir, with_overflow=not args.no_overflow)
    destination = args.output or (args.run_dir / "metrics.jsonl")
    count = write_jsonl(records, destination)

    if not args.jsonl_only:
        print(f"wrote {count} stage records to {destination}")
        for record in records:
            metric_count = len(record) - 4  # minus step_id/stage/step_dir/index
            print(f"  [{record['index']:>2}] {record['stage']:<28} {metric_count} metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
