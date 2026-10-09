# SPDX-License-Identifier: Apache-2.0
"""Tests for the run manifest generator.

None of these run LibreLane. They check the parts that must be right even when
the flow is not installed: hashing, sweep resolution, the manifest's shape and
its validation against run-manifest.schema.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from edi_schema import validate_manifest

from flow.run import (
    REPO_ROOT,
    find_sdc,
    flake_lock_hash,
    host_info,
    load_config_stack,
    main,
    read_pin,
    resolve_design,
    resolve_sweep,
    run_librelane,
    sha256_concat,
    sha256_file,
)

# Sweeps whose perturbation is one *physical* variable expressed as more than
# one LibreLane config key.
#
# A power grid is two-dimensional: moving only PDN_VPITCH would leave the
# horizontal straps at PDK density, which is an anisotropic grid, not a sparse
# one. Strap density is one variable with two axes, so both pitches move
# together. The sweep file carries the same reasoning.
#
# This is an allowlist, not a "two is fine" rule: adding another multi-key
# sweep means deliberately adding an entry here.
COUPLED_SWEEPS: dict[str, frozenset[str]] = {
    "pdn-sparse": frozenset({"PDN_VPITCH", "PDN_HPITCH"}),
}

# Variables the baseline deliberately leaves at the PDK's default, so that a
# baseline run is a normal run. Overriding one of these is not a typo -- but it
# does mean the sweep's "Nx the default" framing is a claim about the PDK
# revision pinned in pdk/sky130.pin, and must be re-checked against the
# installed PDK when that pin moves.
PDK_DEFAULTED_VARIABLES: frozenset[str] = frozenset({"PDN_VPITCH", "PDN_HPITCH"})


def test_design_resolution() -> None:
    design_dir, config = resolve_design("ibex")
    assert design_dir.is_dir()
    assert config.is_file()
    assert config.name == "config.yaml"


def test_unknown_design_is_an_error() -> None:
    with pytest.raises(FileNotFoundError):
        resolve_design("does-not-exist")


def test_every_documented_sweep_resolves() -> None:
    sweeps_dir = REPO_ROOT / "flow" / "sweeps"
    names = sorted(p.stem for p in sweeps_dir.glob("*.yaml"))
    assert names, "no sweep files found"
    for name in names:
        assert resolve_sweep(name) is not None


def test_unknown_sweep_lists_the_known_ones() -> None:
    with pytest.raises(FileNotFoundError, match="available:"):
        resolve_sweep("nope")


def test_sha256_is_lowercase_hex_of_64_chars() -> None:
    digest = sha256_file(REPO_ROOT / "designs" / "ibex" / "config.yaml")
    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)


def test_config_hash_covers_baseline_and_sweep_together() -> None:
    """Two files with the same content in a different order must not collide."""
    baseline = REPO_ROOT / "designs" / "ibex" / "config.yaml"
    sweep = resolve_sweep("congestion-util-75")
    assert sweep is not None
    forward = sha256_concat([baseline, sweep])
    backward = sha256_concat([sweep, baseline])
    assert forward != backward
    assert forward != sha256_concat([baseline])


def test_flake_lock_hash_is_present_or_explicitly_none() -> None:
    digest = flake_lock_hash()
    assert digest is None or len(digest) == 64


def test_host_info_has_both_required_fields() -> None:
    info = host_info()
    assert info["os"]
    assert info["cpu"]


def test_pdk_pin_reads_the_value_not_the_comments() -> None:
    pinned = read_pin(REPO_ROOT / "pdk" / "sky130.pin")
    assert len(pinned) == 40
    int(pinned, 16)


def test_sdc_is_found_and_hashed() -> None:
    design_dir, _config = resolve_design("ibex")
    from flow.run import _load_yaml

    sdc = find_sdc(design_dir, _load_yaml(design_dir / "config.yaml"))
    assert sdc is not None and sdc.is_file()
    assert len(sha256_file(sdc)) == 64


def test_sweeps_change_exactly_one_variable() -> None:
    """A sweep that changes two things is not a single-variable experiment.

    Comments and blank lines are ignored; a sweep file may carry a long header
    explaining itself, which is the point of the file.

    The one exception is a sweep declared in COUPLED_SWEEPS, where several
    config keys express one physical variable. Those must match their declared
    key set exactly -- a coupled sweep that quietly grows or drops a key is
    still a mistake.
    """
    import yaml

    sweeps_dir = REPO_ROOT / "flow" / "sweeps"
    for path in sorted(sweeps_dir.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(document, dict), path.name
        assert document, f"{path.name} sets nothing"

        coupled = COUPLED_SWEEPS.get(path.stem)
        if coupled is not None:
            assert set(document) == coupled, (
                f"{path.name} is declared as the coupled group {sorted(coupled)} "
                f"but sets {sorted(document)}"
            )
            continue

        assert len(document) == 1, f"{path.name} changes {len(document)} variables"


def test_coupled_allowlist_only_names_real_sweeps() -> None:
    """An allowlist entry for a sweep that no longer exists is dead weight."""
    sweeps_dir = REPO_ROOT / "flow" / "sweeps"
    existing = {path.stem for path in sweeps_dir.glob("*.yaml")}
    for name in COUPLED_SWEEPS:
        assert name in existing, f"COUPLED_SWEEPS names {name!r}, but no such sweep exists"


def test_every_sweep_variable_exists_in_the_baseline_or_is_pdk_defaulted() -> None:
    """Overriding a variable the baseline never set is almost always a typo.

    The exception is a variable the baseline intentionally leaves to the PDK
    configuration; those are named in PDK_DEFAULTED_VARIABLES so that
    introducing one is a deliberate act, not a silent slip.
    """
    import yaml

    design_dir, config = resolve_design("ibex")
    baseline = yaml.safe_load(config.read_text(encoding="utf-8"))
    for path in sorted((REPO_ROOT / "flow" / "sweeps").glob("*.yaml")):
        sweep = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in sweep:
            assert key in baseline or key in PDK_DEFAULTED_VARIABLES, (
                f"{path.name} overrides {key!r}, which the baseline never sets and "
                f"which is not declared as PDK-defaulted"
            )


def test_librelane_is_given_an_explicit_design_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without --design-dir, LibreLane reparents the design to flow/sweeps/.

    LibreLane derives DESIGN_DIR from the *last* configuration file it is
    handed. For a sweep run that is the sweep's own directory, which would
    resolve every `dir::` path in the baseline under flow/sweeps/ -- finding no
    Verilog at all -- and put the run directory at flow/sweeps/runs/.
    """
    captured: list[list[str]] = []

    monkeypatch.setattr("flow.run.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        "flow.run.subprocess.run",
        lambda command, **kwargs: captured.append(list(command)) or SimpleNamespace(returncode=0),
    )

    design_dir, baseline = resolve_design("ibex")
    sweep = resolve_sweep("congestion-util-75")
    assert sweep is not None

    code = run_librelane(
        design_dir=design_dir,
        config_files=[baseline, sweep],
        run_id="RUN_TEST",
        pdk_root=Path("/pdk"),
    )
    assert code == 0
    assert len(captured) == 1
    command = captured[0]

    assert "--design-dir" in command
    assert command[command.index("--design-dir") + 1] == str(design_dir)
    # Baseline first, sweep last: LibreLane layers them in the order given.
    assert command[-2:] == [str(baseline), str(sweep)]


def test_overwrite_is_refused_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--overwrite makes LibreLane rmtree the run directory, manifest included.

    The manifest is written first so that a crashed run still records what was
    attempted. Losing it to an overwrite defeats that, so the flag is rejected
    rather than passed through.
    """
    monkeypatch.setattr(
        "flow.run.run_librelane",
        lambda **kwargs: pytest.fail("the flow must not be invoked"),
    )

    design_dir, _baseline = resolve_design("ibex")
    code = main(
        [
            "--design",
            "ibex",
            "--tag",
            "RUN_OVERWRITE_GUARD_TEST",
            "--allow-unknown-tools",
            "--librelane-arg=--overwrite",
        ]
    )
    assert code == 2
    assert not (design_dir / "runs" / "RUN_OVERWRITE_GUARD_TEST").exists()


def test_config_stack_layers_sweeps_over_the_baseline() -> None:
    """The SDC we hash must come from the effective config, not just the baseline."""
    design_dir, baseline = resolve_design("ibex")
    sweep = resolve_sweep("congestion-util-75")
    assert sweep is not None

    effective = load_config_stack([baseline, sweep])
    assert effective["FP_CORE_UTIL"] == 75
    assert effective["DESIGN_NAME"] == "ibex_top"
    assert find_sdc(design_dir, effective) is not None


def test_manifest_shape_is_schema_valid() -> None:
    """A hand-built manifest with the same shape run.py emits must validate."""
    from datetime import datetime

    manifest = {
        "design": {"name": "ibex", "rtl_commit": "0" * 40},
        "environment": {
            "librelane_version": "3.0.11",
            "openroad_version": "v2.0-12345",
            "yosys_version": "Yosys 0.40",
            "nix_flake_lock_hash": "a" * 64,
        },
        "pdk": {"name": "sky130", "commit": "b" * 40},
        "inputs": {"config_hash": "c" * 64, "sdc_hash": "d" * 64},
        "run_id": "RUN_2026-08-28_00-00-00",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": host_info(),
    }
    errors = validate_manifest(manifest)
    assert errors == [], [str(e) for e in errors]
    assert json.loads(json.dumps(manifest)) == manifest
