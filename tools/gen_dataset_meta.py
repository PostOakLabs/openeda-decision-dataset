#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate ``croissant.json`` and ``DATASET_CARD.md`` from the episode corpus (W2.9).

    python tools/gen_dataset_meta.py              # regenerate both artifacts
    python tools/gen_dataset_meta.py --check      # CI gate: fail if they are stale

The exporter itself lives in edi-schema (``build_croissant``, added in v0.2.0).
This file is only the wiring: point the exporter at this repository's
``episodes/`` tree, write the two artifacts at the repo root, and prove in CI
that what is committed is what the corpus actually contains.

Croissant (MLCommons) is the ML-dataset metadata standard -- schema.org-based
JSON-LD, natively indexed by Hugging Face, Kaggle, OpenML and Google Dataset
Search. An episode corpus that ships ``croissant.json`` is discoverable by every
major dataset search surface for free. Sources for that claim, verified
2026-08-29: mlcommons.org/working-groups/data/croissant,
github.com/mlcommons/croissant,
huggingface.co/docs/dataset-viewer/croissant.

Three deliberate choices:

**Nothing is published.** W2.9 makes the repository publication-*ready*; it does
not publish it. No upload, no DOI, no dataset host. The artifacts sit in git and
wait for the day the repository goes public.

**The card carries no judgment.** Every number in ``DATASET_CARD.md`` is
recomputed from the corpus on each run. Anything that is a claim -- motivation,
intended use, curation rationale, licence -- is a ``TODO(expert)`` marker. A
generated file that looks authoritative is worse than no file, because a reader
cannot tell which sentences were computed and which were merely asserted.

**The output is deterministic.** This is what makes the freshness gate possible.
Values that would differ between a dev machine and the CI runner -- the current
date, the Python version, a generation timestamp -- are excluded rather than
frozen, because a committed file can only be diffed against a regeneration that
produces the same bytes everywhere. That is also why ``datePublished`` is
dropped: ``build_croissant`` stamps today's date, which would make the committed
artifact stale every morning, and nothing here is published yet anyway.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Runs as `python tools/gen_dataset_meta.py` as well as `python -m tools.gen_dataset_meta`.
# A direct script run puts <repo>/tools on sys.path, not the repo root, so the
# `tools` package would not be importable.
if __package__ in (None, ""):  # pragma: no cover - exercised by running the script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edi_schema import __version__ as EDI_SCHEMA_VERSION
from edi_schema.check_episodes import check_episodes
from edi_schema.croissant import (
    CROISSANT_SPEC_URL,
    CROISSANT_VERSION,
    ExportOptions,
    build_croissant,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EPISODES = REPO_ROOT / "episodes"
CROISSANT_PATH = REPO_ROOT / "croissant.json"
CARD_PATH = REPO_ROOT / "DATASET_CARD.md"

DATASET_URL = "https://github.com/PostOakLabs/openeda-decision-dataset"
DATASET_NAME = "openeda-decisions-episodes"

# The dataset (the episode corpus / fixture data) licence. Confirmed by the
# licensing decision of 2026-09-02: the DATA corpus is CC BY 4.0, distinct from
# the Apache-2.0 CODE licence. "The licence of the code" and "the licence of the
# data" are separate decisions; that one settled the data. The generated
# croissant.json `license` and the card's "Dataset licence (default)" row come
# from here.
DATASET_LICENSE = "CC-BY-4.0"

# The proposed "Related datasets" section (W2.11) is not rendered: its
# comparative wording was never reviewed, and an unreviewed claim about another
# project does not belong in a generated card. It stays in this repository's
# history for when someone reviews it.

__all__ = [
    "build_dataset",
    "corpus_stats",
    "main",
    "render_card",
    "render_croissant",
]


def build_dataset(episodes_dir: Path) -> dict[str, Any]:
    """Run the W1.2 exporter over ``episodes_dir`` and return the Croissant document.

    Drafts are excluded: ``include_drafts=False`` is the whole point of the
    strict default, since a discovery surface must never index a TODO skeleton
    as data.
    """
    options = ExportOptions(
        name=DATASET_NAME,
        description=(
            "Engineering-decision episodes recorded against LibreLane "
            "physical-design runs: the state before an intervention, the "
            "observation that triggered it, the candidates considered and "
            "rejected, the chosen intervention, and the expert's assessment."
        ),
        url=DATASET_URL,
        license=DATASET_LICENSE,
        include_drafts=False,
        # Deliberately not repeating "physical-design": the exporter's default
        # keyword list already carries it, and a duplicated keyword is noise in
        # a dataset search index.
        extra_keywords=("librelane", "ibex", "sky130"),
    )
    dataset, _summary = build_croissant(str(episodes_dir), options)

    # See the module docstring: a wall-clock date makes the artifact stale every
    # day and would be a fabricated publication date for an unpublished dataset.
    dataset.pop("datePublished", None)
    return dataset


def corpus_stats(episodes_dir: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    """Count what the export admits, and account for everything it leaves out.

    ``check_episodes`` is called a second time on purpose. The exported rows
    show what survived; only the check results explain *why* a file is absent,
    and a card that reported "3 files, 0 episodes" without saying "3 drafts"
    would read as a bug. ``strict=True`` matches
    ``build_croissant(include_drafts=False)``.
    """
    rows = dataset["recordSet"][0]["data"]["includes"]
    results, unreadable = check_episodes(str(episodes_dir), strict=True)

    def tally(column: str) -> list[tuple[str, int]]:
        counts: Counter[str] = Counter(
            str(row.get(column)) if row.get(column) is not None else "(absent)" for row in rows
        )
        return sorted(counts.items())

    return {
        "admitted": len(rows),
        "excluded_drafts": sum(1 for r in results if r.valid and not r.included),
        "schema_invalid": sum(1 for r in results if not r.valid),
        "unreadable": len(unreadable),
        "files_scanned": len(results) + len(unreadable),
        "by_provenance": tally("provenance"),
        "by_failure_class": tally("failure_class"),
    }


def render_croissant(dataset: dict[str, Any]) -> str:
    """Serialise the document the way it should be committed."""
    return json.dumps(dataset, indent=2, ensure_ascii=False) + "\n"


def _table(title: str, rows: list[tuple[str, int]]) -> str:
    """One facet of the corpus, or an explicit note that it is empty."""
    if not rows:
        return f"### {title}\n\n_None yet. The corpus admits no episodes._\n"
    lines = [f"### {title}", "", "| value | count |", "| --- | --- |"]
    lines.extend(f"| `{value}` | {count} |" for value, count in rows)
    lines.append("")
    return "\n".join(lines)


def render_card(stats: dict[str, Any], dataset: dict[str, Any]) -> str:
    """Render ``DATASET_CARD.md``: mechanical facts above, judgment below."""
    admitted = stats["admitted"]
    if admitted:
        corpus_line = f"{admitted} episode(s) admitted to the export."
    else:
        corpus_line = (
            "**No episodes are admitted yet.** Every file under `episodes/` is "
            "still a draft (TODO markers) or a template, and drafts are excluded "
            "by design: a discovery surface must never index a TODO skeleton as "
            "data. The card is still generated, and still honest, at zero."
        )

    enumeration_note = ""
    if not dataset["recordSet"][0]["enumeration"]:
        enumeration_note = (
            "\nThe export emits no Croissant enumerations yet, because those are "
            "derived from admitted rows rather than from the schema's vocabulary. "
            "They appear automatically once the first real episode lands.\n"
        )

    return "\n".join(
        [
            "# Dataset card - openeda-decisions episodes",
            "",
            "<!--",
            "GENERATED by tools/gen_dataset_meta.py - do not hand-edit.",
            "CI regenerates this file and fails if the committed copy is stale.",
            "Every number below is recomputed from episodes/ on each run; anything",
            "that is a claim rather than a count is a TODO(expert) marker.",
            "-->",
            "",
            "## At a glance",
            "",
            corpus_line,
            "",
            "| | |",
            "| --- | --- |",
            f"| Episodes admitted | {stats['admitted']} |",
            f"| Excluded as drafts | {stats['excluded_drafts']} |",
            f"| Excluded as schema-invalid | {stats['schema_invalid']} |",
            f"| Unreadable or invalid JSON | {stats['unreadable']} |",
            f"| Files scanned under `episodes/` | {stats['files_scanned']} |",
            "",
            "Drafts are excluded by default. `edi-croissant --include-drafts` will "
            "preview what the export *would* contain, but the committed artifact is "
            "always the strict one.",
            "",
            _table("By provenance", stats["by_provenance"]),
            _table("By failure_class", stats["by_failure_class"]),
            enumeration_note,
            "## Schema and tooling",
            "",
            "| | |",
            "| --- | --- |",
            f"| edi-schema version | {EDI_SCHEMA_VERSION} |",
            f"| Croissant version | {CROISSANT_VERSION} |",
            f"| Croissant spec | {CROISSANT_SPEC_URL} |",
            f"| Episode schema | `episode.schema.json` (edi-schema {EDI_SCHEMA_VERSION}) |",
            f"| Dataset licence (default) | {DATASET_LICENSE} |",
            "| Generator | `tools/gen_dataset_meta.py` |",
            "",
            "Timestamps and interpreter versions are deliberately absent: they "
            "would differ between a dev machine and the CI runner, and this file "
            "has to regenerate byte-identically everywhere for the freshness gate "
            "to mean anything.",
            "",
            "## TODO(expert): judgment, not counting",
            "",
            "These are the sections only the episode author can write. They are "
            "stubbed here rather than omitted so the shape of the finished card is "
            "visible.",
            "",
            "- **TODO(expert): motivation** - why this corpus exists and what a "
            "reader should be able to do with it.",
            "- **TODO(expert): intended use and out-of-scope uses** - in "
            "particular, whether these episodes are evidence about EDA flows, or "
            "about one expert's decisions, or both.",
            "- **TODO(expert): curation and provenance** - how episodes were "
            "chosen, who authored them, and what `retrospective` versus "
            "`reproduced` means in practice here.",
            f"- **Dataset licence (resolved 2026-09-02)** - the episode "
            f"corpus / fixture data is **CC BY 4.0** (`{DATASET_LICENSE}`), "
            "distinct from the Apache-2.0 code licence. Recorded in NOTICE.",
            "- **TODO(expert): publication** - this corpus is not published "
            "anywhere. Croissant makes it *publishable*; it does not publish it. "
            "Decide the venue, then set `datePublished` in the generator.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_dataset_meta",
        description="Generate croissant.json and DATASET_CARD.md from the episode corpus.",
    )
    parser.add_argument(
        "episodes",
        type=Path,
        nargs="?",
        default=DEFAULT_EPISODES,
        help=f"episode directory to export (default: {DEFAULT_EPISODES})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; fail if the committed artifacts differ from a regeneration",
    )
    args = parser.parse_args(argv)

    if not args.episodes.exists():
        print(f"error: {args.episodes} does not exist", file=sys.stderr)
        return 2

    dataset = build_dataset(args.episodes)
    stats = corpus_stats(args.episodes, dataset)
    croissant_text = render_croissant(dataset)
    card_text = render_card(stats, dataset)

    targets = ((CROISSANT_PATH, croissant_text), (CARD_PATH, card_text))

    if args.check:
        stale: list[str] = []
        for path, text in targets:
            name = path.relative_to(REPO_ROOT)
            if not path.exists():
                stale.append(f"{name} is missing")
            elif path.read_text(encoding="utf-8") != text:
                stale.append(f"{name} is stale")
        if stale:
            for problem in stale:
                print(f"error: {problem}", file=sys.stderr)
            print(
                "\nThe committed dataset metadata does not match episodes/.\n"
                "Regenerate it:  python tools/gen_dataset_meta.py",
                file=sys.stderr,
            )
            return 1
        print("croissant.json and DATASET_CARD.md are up to date")
        return 0

    for path, text in targets:
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")

    print(
        f"\n{stats['admitted']} admitted, {stats['excluded_drafts']} held back as drafts, "
        f"{stats['schema_invalid']} schema-invalid, {stats['unreadable']} unreadable "
        f"(of {stats['files_scanned']} files scanned)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
