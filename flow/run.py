#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""One command from a design to a recorded, reproducible run.

    python flow/run.py --design ibex [--sweep congestion-util-75] [--tag NAME]

It does five things, in this order:

  1. resolves the design's configuration, plus at most one sweep overlay;
  2. enables the pinned PDK revision (``pdk/sky130.pin``) under ``.ciel/``;
  3. snapshots a run manifest -- design commit, PDK commit, tool versions,
     sha256 of every input file, flake.lock hash, host -- and validates it
     against ``run-manifest.schema.json``;
  4. invokes LibreLane with a run tag, so the run directory is
     ``<design_dir>/runs/<tag>``;
  5. runs the extractor over the result, producing ``metrics.jsonl``.

The manifest is written *before* the flow runs. If the run dies, the manifest
still says exactly what was attempted, which is the case where you most need
to know.

Use ``--dry-run`` to stop after step 3. That is how the tests exercise this
without LibreLane installed, and how you check what a run would record before
spending an hour on it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGNS = REPO_ROOT / "designs"
SWEEPS = REPO_ROOT / "flow" / "sweeps"
PDK_PIN = REPO_ROOT / "pdk" / "sky130.pin"
DEFAULT_PDK_ROOT = REPO_ROOT / ".ciel"
PDK_NAME = "sky130"

__all__ = [
    "REPO_ROOT",
    "flake_lock_hash",
    "git_head",
    "host_info",
    "main",
    "sha256_concat",
    "sha256_file",
    "tool_version",
]


# --------------------------------------------------------------------------
# Hashing and provenance
# --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    """sha256 of a file's bytes, lowercase hex."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_concat(paths: Sequence[Path]) -> str:
    """sha256 over several files, in order.

    A sweep is a second configuration file layered on top of the baseline, so
    the effective configuration is the ordered pair. Hashing them together
    means the manifest's ``config_hash`` identifies what the flow was actually
    given, not just the baseline's contribution to it.
    """
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def flake_lock_hash() -> str | None:
    """sha256 of ``flake.lock``, which pins the whole tool environment."""
    for candidate in (REPO_ROOT / "flake.lock", REPO_ROOT / "nix" / "flake.lock"):
        if candidate.is_file():
            return sha256_file(candidate)
    return None


def git_head(workdir: Path) -> str | None:
    """HEAD commit of a checkout, or None if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def tool_version(command: str, *args: str) -> str | None:
    """Ask a tool for its version. Returns None if it is not installed.

    Version strings are stored verbatim rather than parsed: they are
    identifiers, not numbers, and normalising them invites a comparison bug.
    """
    executable = shutil.which(command)
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    combined = (result.stdout or "") + (result.stderr or "")
    return _first_line(combined) or None


def host_info() -> dict[str, str]:
    os_name = platform.platform()
    cpu = platform.machine()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        try:
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.lower().startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
    return {"os": os_name, "cpu": cpu}


def read_pin(path: Path) -> str:
    """Read a ``*.pin`` file: a comment header, then the pinned value."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    raise ValueError(f"no pinned value found in {path}")


# --------------------------------------------------------------------------
# Configuration resolution
# --------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else {}


def resolve_design(design: str) -> tuple[Path, Path]:
    design_dir = DESIGNS / design
    config = design_dir / "config.yaml"
    if not config.is_file():
        raise FileNotFoundError(f"no config at {config}")
    return design_dir, config


def resolve_sweep(name: str | None) -> Path | None:
    if name is None:
        return None
    path = SWEEPS / f"{name}.yaml"
    if not path.is_file():
        known = sorted(p.stem for p in SWEEPS.glob("*.yaml"))
        raise FileNotFoundError(
            f"no sweep named {name!r}; available: {', '.join(known) or '(none)'}"
        )
    return path


def load_config_stack(config_files: Sequence[Path]) -> dict[str, Any]:
    """The effective configuration: files layered in order, later ones winning.

    This mirrors what LibreLane does when it is handed several configuration
    files, so that anything we read out of the configuration -- the constraints
    file, notably -- is read from the same values the flow will use.
    """
    effective: dict[str, Any] = {}
    for path in config_files:
        effective.update(_load_yaml(path))
    return effective


def find_sdc(design_dir: Path, config: Mapping[str, Any]) -> Path | None:
    """Locate the constraints file the configuration points at.

    LibreLane resolves ``dir::`` relative to the directory of the config file,
    i.e. the design directory. Mirror that rather than guessing.
    """
    for key in ("PNR_SDC_FILE", "SIGNOFF_SDC_FILE", "BASE_SDC_FILE"):
        raw = config.get(key)
        if not isinstance(raw, str):
            continue
        relative = raw.removeprefix("dir::")
        candidate = design_dir / relative
        if candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def build_manifest(
    *,
    design_name: str,
    design_dir: Path,
    config_files: Sequence[Path],
    sdc_file: Path | None,
    run_id: str,
    started_at: str,
    allow_unknown_tools: bool = False,
) -> dict[str, Any]:
    """Assemble a run-manifest document and validate it before returning.

    Validation happens here rather than at write time so that a malformed
    manifest is a build error, not a file someone discovers is unusable later.
    """
    from edi_schema import format_errors, validate_manifest

    environment: dict[str, Any] = {
        "librelane_version": tool_version("librelane", "--version"),
        "openroad_version": tool_version("openroad", "-version"),
        "yosys_version": tool_version("yosys", "-V"),
    }
    lock_hash = flake_lock_hash()
    if lock_hash is not None:
        environment["nix_flake_lock_hash"] = lock_hash

    missing = sorted(key for key, value in environment.items() if not value)
    if missing and not allow_unknown_tools:
        # Refuse to write a manifest that claims a tool version it could not
        # determine. An episode pinned to an unknown toolchain is not
        # reproducible, and saying so loudly beats discovering it in six months.
        raise RuntimeError(
            "could not determine tool versions for: "
            + ", ".join(missing)
            + ". Run this inside `nix develop`, or pass --allow-unknown-tools "
            "if you are deliberately recording an un-pinned environment."
        )
    if missing:
        print(
            "warning: recording a manifest with unknown tool versions "
            f"({', '.join(missing)}); episodes taken from this run will not be "
            "reproducible",
            file=sys.stderr,
        )
        for key in missing:
            environment[key] = "unknown"

    inputs: dict[str, Any] = {"config_hash": sha256_concat(config_files)}
    if sdc_file is not None:
        inputs["sdc_hash"] = sha256_file(sdc_file)

    rtl_commit = git_head(design_dir / "ibex")
    if rtl_commit is None:
        if not allow_unknown_tools:
            raise RuntimeError(
                f"could not read the RTL commit from {design_dir / 'ibex'}; "
                "run `git submodule update --init designs/ibex/ibex`"
            )
        print(
            "warning: RTL commit unknown; episodes will not be reproducible",
            file=sys.stderr,
        )
        rtl_commit = "unknown"

    manifest: dict[str, Any] = {
        "design": {"name": design_name, "rtl_commit": rtl_commit},
        "environment": environment,
        "pdk": {"name": PDK_NAME, "commit": read_pin(PDK_PIN)},
        "inputs": inputs,
        "run_id": run_id,
        "started_at": started_at,
        "host": host_info(),
    }

    errors = validate_manifest(manifest)
    if errors:
        raise RuntimeError("generated manifest is invalid:\n" + format_errors(errors))
    return manifest


# --------------------------------------------------------------------------
# PDK provisioning
# --------------------------------------------------------------------------


def ensure_pdk(pdk_root: Path) -> None:
    """Enable the pinned sky130 revision under ``pdk_root``, if ciel exists.

    Silently doing nothing when ciel is absent is wrong, but so is aborting a
    run on a machine where the PDK was provisioned by other means. So: warn,
    and let LibreLane decide whether the PDK it finds is acceptable.
    """
    pinned = read_pin(PDK_PIN)
    ciel = shutil.which("ciel")
    if ciel is None:
        print(
            f"warning: `ciel` not found; not enabling {PDK_NAME} {pinned}. "
            "LibreLane will use whatever is already in PDK_ROOT.",
            file=sys.stderr,
        )
        return
    subprocess.run(
        [
            ciel,
            "enable",
            "--pdk",
            PDK_NAME,
            "--pdk-root",
            str(pdk_root),
            pinned,
        ],
        check=False,
    )


# --------------------------------------------------------------------------
# Running the flow
# --------------------------------------------------------------------------


def run_librelane(
    *,
    design_dir: Path,
    config_files: Sequence[Path],
    run_id: str,
    pdk_root: Path,
    extra_args: Sequence[str] = (),
) -> int:
    """Invoke LibreLane, returning its exit code.

    ``--design-dir`` is passed explicitly and is not optional in practice.
    LibreLane derives DESIGN_DIR from *the last configuration file it is
    given* when the flag is absent, so handing it a sweep file from
    ``flow/sweeps/`` would silently reparent the design: every ``dir::`` path
    in the baseline would resolve under ``flow/sweeps/`` (no Verilog found)
    and the run directory would move to ``flow/sweeps/runs/``.
    """
    librelane = shutil.which("librelane")
    if librelane is None:
        print(
            "error: `librelane` not found on PATH. Run this inside `nix develop`, "
            "or use the Docker fallback in docs/windows-setup.md.",
            file=sys.stderr,
        )
        return 127
    command = [
        librelane,
        "--run-tag",
        run_id,
        "--design-dir",
        str(design_dir),
        "--pdk-root",
        str(pdk_root),
        *extra_args,
        *[str(path) for path in config_files],
    ]
    print("$ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=design_dir, check=False)
    return completed.returncode


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default_run_id(sweep: str | None) -> str:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    return f"RUN_{stamp}" + (f"_{sweep}" if sweep else "")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run",
        description="Provision, run, extract and record one LibreLane run.",
    )
    parser.add_argument("--design", default="ibex", help="design directory under designs/")
    parser.add_argument("--config", type=Path, default=None, help="override config path")
    parser.add_argument(
        "--sweep", default=None, help="name of a sweep under flow/sweeps/ (no extension)"
    )
    parser.add_argument("--tag", default=None, help="run id / run directory name")
    parser.add_argument(
        "--pdk-root",
        type=Path,
        default=DEFAULT_PDK_ROOT,
        help=f"PDK root for ciel (default: {DEFAULT_PDK_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write the manifest and the command, then stop without running the flow",
    )
    parser.add_argument(
        "--allow-unknown-tools",
        action="store_true",
        help="write the manifest even if a tool version could not be determined",
    )
    parser.add_argument(
        "--librelane-arg",
        action="append",
        default=[],
        metavar="ARG",
        help=(
            "extra argument passed through to librelane (repeatable). "
            "Use the = form for anything starting with a dash, e.g. "
            "--librelane-arg=--overwrite"
        ),
    )
    args = parser.parse_args(argv)

    try:
        design_dir, baseline = resolve_design(args.design)
        sweep_file = resolve_sweep(args.sweep)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    config_files = [args.config or baseline]
    if sweep_file is not None:
        config_files.append(sweep_file)

    run_id = args.tag or _default_run_id(args.sweep)
    started_at = _now_iso()

    # LibreLane deletes a run directory it is told to overwrite, which would
    # take the manifest with it. Refuse rather than silently losing the record:
    # the manifest existing before the flow starts is the whole point of
    # writing it first.
    if "--overwrite" in args.librelane_arg:
        print(
            "error: --overwrite would delete the run directory, including "
            "manifest.json. Use a fresh --tag instead.",
            file=sys.stderr,
        )
        return 2

    sdc_file = find_sdc(design_dir, load_config_stack(config_files))
    if sdc_file is None:
        print("warning: no constraints file found in the configuration", file=sys.stderr)

    try:
        manifest = build_manifest(
            design_name=args.design,
            design_dir=design_dir,
            config_files=config_files,
            sdc_file=sdc_file,
            run_id=run_id,
            started_at=started_at,
            allow_unknown_tools=args.allow_unknown_tools,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Created before the flow runs so a crashed run still records what was
    # attempted. LibreLane tolerates the manifest being there: it resumes a
    # non-empty run directory, but it only treats `<ordinal>-<slug>/` entries
    # as prior steps, so a lone manifest.json leaves it starting from scratch.
    # Expect it to log "Using existing run" on the first run; that log line
    # refers to the directory, not to any work having been done in it.
    run_dir = design_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"manifest: {manifest_path}")
    print(json.dumps(manifest, indent=2))

    if args.dry_run:
        print(f"\n[dry run] would run in {design_dir} with tag {run_id}")
        return 0

    ensure_pdk(args.pdk_root)
    returncode = run_librelane(
        design_dir=design_dir,
        config_files=config_files,
        run_id=run_id,
        pdk_root=args.pdk_root,
        extra_args=args.librelane_arg,
    )
    if returncode != 0:
        print(
            f"flow exited {returncode}; the run directory and manifest are still at {run_dir}",
            file=sys.stderr,
        )
        return returncode

    from extractors.metrics_from_state import extract_run, write_jsonl

    records = extract_run(run_dir)
    metrics_path = run_dir / "metrics.jsonl"
    write_jsonl(records, metrics_path)
    print(f"metrics: {metrics_path} ({len(records)} stages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
