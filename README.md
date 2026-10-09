# openeda-decision-dataset

Flow harness, metric extractors and episode tooling for reproducible
physical-design decisions.

Status: W2.1–W2.8 are in place. The environment, flow harness, extractor,
sweeps and episode tooling all run; no LibreLane flow has been executed yet,
because none could be from the machine this was built on. See
`docs/windows-setup.md` for the environment.

## What this repository is for

It runs [LibreLane](https://librelane.readthedocs.io) (never "OpenLane") on
Ibex against sky130A in a pinned environment, extracts per-stage metrics into
schema-shaped JSON, records a run manifest for reproducibility, and scaffolds
episode files whose mechanical fields are already filled in — so the only work
left is judgment.

It contains no episodes. `episodes/` holds a template, structure only -- every
*judgment* field in it is a `TODO(expert)` marker. The
only non-marker strings are the fixed identifiers (`$schema`, `episode_id`) and
the least-committal enum members (`provenance: retrospective`, `severity:
degrading`, `expert_assessment: inconclusive`, `failure_class: FAIL_FLOW` /
`FAIL_CONGESTION` / `FAIL_TIMING`) -- the scaffold allowlist set in
`tests/test_episode_assets.py::SCAFFOLD_STRINGS`. Filling the judgment fields in
is the domain expert's work and cannot be done by any tool here. See
[episodes/README.md](episodes/README.md).

## Layout

| Path | Purpose |
|---|---|
| `designs/ibex/` | LibreLane config and constraints for Ibex on sky130A |
| `flow/run.py` | One command: provision, run, extract, write manifest |
| `flow/sweeps/` | Named single-variable failure-provocation configs |
| `extractors/` | LibreLane run directory → per-stage metrics JSON |
| `tools/new_episode.py` | Scaffold an episode, prefilled from a run when one exists |
| `tools/check_episodes.py` | Drafts, duplicate ids, fixtures out of place |
| `episodes/` | Template, and eventually real episodes |
| `docs/windows-setup.md` | WSL 2 + Nix setup, and the Docker fallback |
| `.github/workflows/ci.yaml` | Lint + tests on every push; the flow on dispatch |
| `pdk/sky130.pin` | The pinned sky130 revision |
| `flake.nix` | Pinned LibreLane 3.0.11 environment |

Installed as console scripts too: `openeda-run`, `openeda-extract`,
`openeda-new-episode`, `openeda-check-episodes`.

## Quick start

```bash
pip install -e ".[dev]"        # installs engineering-decision-schema from GitHub

pytest -q                      # no LibreLane required
python tools/check_episodes.py --allow-draft

# Inside `nix develop` (see docs/windows-setup.md):
python flow/run.py --design ibex --sweep congestion-util-75
python tools/new_episode.py --from-run designs/ibex/runs/<tag> \
    --prior-stage global_placement --post-stage detailed_routing \
    --failure-class FAIL_CONGESTION --out episodes/EP-IBEX-001.json
```

Naming: the flow is **LibreLane**; the P&R engine inside it is **OpenROAD**.

## License

The code is Apache-2.0; see [LICENSE](LICENSE). The episode corpus / fixture
data that the tooling exports is **CC BY 4.0** (licensing decision of
2026-09-02), which is distinct from the code license. The split is recorded in
[NOTICE](NOTICE). `designs/ibex/constraints/ibex.sdc` carries a derivative-work
notice for LibreLane's `scripts/base.sdc`.
