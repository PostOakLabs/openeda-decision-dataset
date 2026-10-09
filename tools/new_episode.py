#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Scaffold one episode document.

    python tools/new_episode.py --design ibex --failure-class FAIL_TIMING
    python tools/new_episode.py --from-run designs/ibex/runs/RUN_... \
        --failure-class FAIL_CONGESTION --out episodes/EP-IBEX-001.json

Two modes, and the difference between them is the point of the tool.

**With ``--from-run``**, everything that can be read off a real run is read off
it: the design and its RTL commit, the PDK and its commit, the tool versions,
the run id, and the metrics at whichever two stages you name. None of that is
supplied by the author, so none of it can be misremembered. Provenance is
``reproduced``, which then obliges the author to keep the environment block --
the schema enforces that, not this tool.

**Without it**, the episode is a blank form: ids and defaults are filled in,
and every field that needs an expert is marked ``TODO(expert)``. Provenance is
``retrospective`` -- a decision recalled from a prior tapeout, with no run
artifact behind it. That is a real and respectable kind of episode; it is not
a lesser one, and it must not be dressed up as a reproduced one.

What this tool will not do is invent a number, a metric, or a rationale. The
schema's enum fields cannot hold a TODO string, so those get a documented
default instead -- which is why a scaffolded episode always carries markers
elsewhere, and why ``check_episodes.py`` treats any marker at all as making
the whole document a draft.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Runs as `python tools/new_episode.py` as well as `python -m tools.new_episode`.
# A direct script run puts <repo>/tools on sys.path, not the repo root, so the
# `tools` package and the repo's other packages would not be importable.
if __package__ in (None, ""):  # pragma: no cover - exercised by running the script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import (  # noqa: E402
    OWNERS,
    find_todo_markers,
    todo_marker,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EPISODES = REPO_ROOT / "episodes"
SCHEMA_ID = "https://postoaklabs.github.io/engineering-decision-schema/episode.schema.json"

#: Enum fields cannot hold a TODO marker, so they are scaffolded to a value
#: that is at least defensible: the least committal member of each enum.
#: Documented here, because a default is easy to mistake for a decision that
#: was actually made.
DEFAULT_PROVENANCE = "retrospective"
DEFAULT_SEVERITY = "degrading"
DEFAULT_ASSESSMENT = "inconclusive"
DEFAULT_FAILURE_CLASS = "FAIL_FLOW"

#: A scaffolded confidence of 0.0 means "not assessed yet". Any other number
#: would be a fabricated judgment, and there is no null in the schema.
DEFAULT_CONFIDENCE = 0.0

FAILURE_CLASSES = (
    "FAIL_CONGESTION",
    "FAIL_TIMING",
    "FAIL_IR_DROP",
    "FAIL_ANTENNA",
    "FAIL_DRC",
    "FAIL_LVS",
    "FAIL_ROUTER",
    "FAIL_CTS",
    "FAIL_MEMORY",
    "FAIL_FLOW",
    "SDC_BUDGET",
)

_IDENTITY_KEYS = ("stage", "step_id", "step_dir", "index")
_EPISODE_ID_RE = re.compile(r"^EP-(?P<domain>[A-Za-z0-9]+)-(?P<number>\d+)$")

__all__ = ["build_episode", "main", "next_episode_id"]


# --------------------------------------------------------------------------
# Ids
# --------------------------------------------------------------------------


def next_episode_id(episodes_dir: Path, domain: str) -> str:
    """The next unused ``EP-<DOMAIN>-<nnn>`` under ``episodes_dir``.

    Numbering is per domain and zero-padded to three digits, so ids sort in
    the order they were created. Existing files are read for their
    ``episode_id`` field rather than parsed out of the filename, because the
    filename is a convenience and the field is the identity.
    """
    highest = 0
    for path in sorted(episodes_dir.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        match = _EPISODE_ID_RE.match(str(document.get("episode_id", "")))
        if match is None or match.group("domain").upper() != domain.upper():
            continue
        highest = max(highest, int(match.group("number")))
    return f"EP-{domain.upper()}-{highest + 1:03d}"


def _domain_for(design: str) -> str:
    """A filesystem- and id-safe domain label from a design name."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", design)
    return cleaned or "DESIGN"


# --------------------------------------------------------------------------
# Reading a real run
# --------------------------------------------------------------------------


def load_manifest(run_dir: Path) -> dict[str, Any]:
    """The run manifest from a run directory. Raises if there is not one."""
    path = run_dir / "manifest.json"
    if not path.is_file():
        msg = (
            f"no manifest.json in {run_dir}; an episode with provenance "
            "'reproduced' must be backed by a run that recorded one. Scaffold "
            "without --from-run if this is a retrospective episode."
        )
        raise FileNotFoundError(msg)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        msg = f"{path} is not a JSON object"
        raise ValueError(msg)
    return document


def records_from_run(run_dir: Path) -> list[dict[str, Any]]:
    """Per-stage metric records for a run, from the extractor."""
    sys.path.insert(0, str(REPO_ROOT))
    from extractors.metrics_from_state import extract_run  # noqa: PLC0415

    return extract_run(run_dir)


def pick_stage(
    records: list[dict[str, Any]],
    wanted: str | None,
    *,
    occurrence: str,
) -> dict[str, Any]:
    """One record by stage name, or by position when no name is given.

    ``occurrence`` decides which of several records for the same stage wins.
    LibreLane runs OpenROAD.STAMidPNR four times in the Classic flow, so a
    stage name is not unique: the first occurrence is where the state was
    before anything was done about it, the last is where it ended up.

    Repeated stages are disambiguated by the extractor with a numeric suffix
    (``sta_mid_pnr``, ``sta_mid_pnr.2``), so asking for ``sta_mid_pnr`` matches
    on the base name and ``occurrence`` picks which one you meant.
    """
    if not records:
        msg = "the run produced no stage records"
        raise ValueError(msg)
    if wanted is None:
        return records[0] if occurrence == "first" else records[-1]

    matches = [
        record
        for record in records
        if record.get("stage") == wanted or str(record.get("stage", "")).split(".", 1)[0] == wanted
    ]
    if not matches:
        available = ", ".join(sorted({str(r.get("stage")) for r in records}))
        msg = f"no stage named {wanted!r} in this run; available: {available}"
        raise KeyError(msg)
    return matches[0] if occurrence == "first" else matches[-1]


def state_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """A schema ``state`` object: a stage label plus the metrics measured there.

    Metrics that were not measured are absent, never zero. That rule comes
    from the schema and the extractor both; keeping it here means a scaffolded
    episode does not smuggle in a 0 that later reads as a measurement.
    """
    metrics = {
        key: value
        for key, value in record.items()
        if key not in _IDENTITY_KEYS and value is not None
    }
    return {"stage": record["stage"], "metrics": metrics}


# --------------------------------------------------------------------------
# Scaffolding
# --------------------------------------------------------------------------


def _todo(owner: str, what: str) -> str:
    return todo_marker(owner, what)


def build_episode(
    *,
    episode_id: str,
    owner: str,
    design_name: str,
    provenance: str,
    failure_class: str,
    pdk: str,
    prior_state: dict[str, Any] | None = None,
    post_state: dict[str, Any] | None = None,
    environment: dict[str, Any] | None = None,
    rtl_commit: str | None = None,
    pdk_commit: str | None = None,
    run_manifest_ref: str | None = None,
) -> dict[str, Any]:
    """One scaffolded episode. Mechanical fields filled, judgment marked."""
    design: dict[str, Any] = {"name": design_name, "pdk": pdk}
    if rtl_commit:
        design["rtl_commit"] = rtl_commit
    if pdk_commit:
        design["pdk_commit"] = pdk_commit

    blank_state = {
        "stage": _todo(owner, "which flow stage was this reading taken at?"),
        "metrics": {},
    }

    episode: dict[str, Any] = {
        "$schema": SCHEMA_ID,
        "episode_id": episode_id,
        "provenance": provenance,
        "design": design,
        "prior_state": prior_state or blank_state,
        "post_state": post_state or blank_state,
        "observation": {
            "metric": _todo(owner, "metric name with its unit, e.g. wns_ns"),
            "value": _todo(owner, "what was observed"),
            "target": _todo(owner, "what the design was aiming for"),
            "severity": DEFAULT_SEVERITY,
        },
        "hypothesis": _todo(owner, "your causal reading of the observation"),
        "candidates_considered": [
            {
                "intervention": _todo(owner, "the intervention you took"),
                "rejected_because": None,
            },
            {
                "intervention": _todo(owner, "an intervention you considered and rejected"),
                "rejected_because": _todo(owner, "why you rejected it"),
            },
        ],
        "chosen_intervention": {
            "parameter": _todo(owner, "the knob you turned, e.g. FP_CORE_UTIL"),
            "before": _todo(owner, "value before"),
            "after": _todo(owner, "value after"),
        },
        "expert_assessment": DEFAULT_ASSESSMENT,
        "rationale": _todo(owner, "why this intervention over the others"),
        "confidence": DEFAULT_CONFIDENCE,
        "failure_class": failure_class,
    }

    # Order matters only for readability; the schema does not care. Environment
    # and run_manifest_ref are placed next to provenance and design because
    # that is where a reader looks for them.
    if environment:
        episode["environment"] = environment
    if run_manifest_ref:
        episode["run_manifest_ref"] = run_manifest_ref
    return episode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="new_episode",
        description="Scaffold one episode document, prefilled where it can be.",
    )
    parser.add_argument("--design", default="ibex", help="design name")
    parser.add_argument("--pdk", default="sky130", help="PDK name")
    parser.add_argument(
        "--provenance",
        default=None,
        choices=["retrospective", "reproduced", "synthetic-fixture"],
        help=f"default: {DEFAULT_PROVENANCE}, or 'reproduced' with --from-run",
    )
    parser.add_argument(
        "--failure-class",
        default=DEFAULT_FAILURE_CLASS,
        choices=list(FAILURE_CLASSES),
        help=f"default: {DEFAULT_FAILURE_CLASS}",
    )
    parser.add_argument(
        "--from-run",
        type=Path,
        default=None,
        help="run directory containing a manifest.json written by flow/run.py",
    )
    parser.add_argument(
        "--prior-stage",
        default=None,
        help="stage name for prior_state (default: the run's first stage)",
    )
    parser.add_argument(
        "--post-stage",
        default=None,
        help="stage name for post_state (default: the run's last stage)",
    )
    parser.add_argument(
        "--id", default=None, help="episode id (default: next free EP-<DESIGN>-<nnn>)"
    )
    parser.add_argument(
        "--owner", default="expert", choices=list(OWNERS), help="who fills in the TODOs"
    )
    parser.add_argument("--out", type=Path, default=None, help="write here (default: stdout)")
    parser.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    args = parser.parse_args(argv)

    environment: dict[str, Any] | None = None
    prior_state: dict[str, Any] | None = None
    post_state: dict[str, Any] | None = None
    rtl_commit: str | None = None
    pdk_commit: str | None = None
    run_manifest_ref: str | None = None

    provenance = args.provenance
    if args.from_run is not None:
        try:
            manifest = load_manifest(args.from_run)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        manifest_design = manifest.get("design") or {}
        manifest_pdk = manifest.get("pdk") or {}
        design_name = str(manifest_design.get("name") or args.design)
        rtl_commit = manifest_design.get("rtl_commit")
        pdk_commit = manifest_pdk.get("commit")
        pdk = str(manifest_pdk.get("name") or args.pdk)
        run_manifest_ref = str(manifest.get("run_id") or args.from_run.name)
        environment = dict(manifest.get("environment") or {})
        # A run happened, so this episode is reproduced unless it is
        # deliberately labelled a fixture.
        provenance = provenance or "reproduced"

        try:
            records = records_from_run(args.from_run)
            prior_state = state_from_record(
                pick_stage(records, args.prior_stage, occurrence="first")
            )
            post_state = state_from_record(pick_stage(records, args.post_stage, occurrence="last"))
        except (KeyError, ValueError, NotADirectoryError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        design_name = args.design
        pdk = args.pdk
        provenance = provenance or DEFAULT_PROVENANCE

    episode_id = args.id or next_episode_id(EPISODES, _domain_for(design_name))
    episode = build_episode(
        episode_id=episode_id,
        owner=args.owner,
        design_name=design_name,
        provenance=provenance,
        failure_class=args.failure_class,
        pdk=pdk,
        prior_state=prior_state,
        post_state=post_state,
        environment=environment,
        rtl_commit=rtl_commit,
        pdk_commit=pdk_commit,
        run_manifest_ref=run_manifest_ref,
    )

    text = json.dumps(episode, indent=2) + "\n"
    if args.out is not None:
        if args.out.exists() and not args.force:
            print(f"error: {args.out} exists; pass --force to overwrite", file=sys.stderr)
            return 1
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)

    markers = find_todo_markers(episode)
    if markers:
        print(f"\n{len(markers)} field(s) need {args.owner}:", file=sys.stderr)
        for path, marker in markers:
            print(f"  {path}  {marker}", file=sys.stderr)
        print(
            "\nThis is a draft. check_episodes.py will reject it until the markers are gone.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
