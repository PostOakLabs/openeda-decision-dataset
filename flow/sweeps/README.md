# Failure-provocation sweeps

Each file here is **one** configuration file layered on top of
`designs/ibex/config.yaml`, changing **exactly one variable**. It is not a
grid, not a campaign, and not a parameter study — the project spec excludes
those deliberately. There are six files, so there are six runs.

One file, `pdn-sparse`, sets two LibreLane keys (`PDN_VPITCH` and
`PDN_HPITCH`) because strap density is a single two-axis variable; moving one
axis alone makes an anisotropic grid, which is a different experiment. Both
moves are the same factor. The exception is allowlisted in
`tests/test_runner.py`, not left open-ended.

## How they are used

```bash
python flow/run.py --design ibex --sweep congestion-util-75
```

`run.py` passes the baseline and then the sweep to LibreLane as two
configuration files, so the sweep's values win. The manifest records the
sha256 of both, in order, as `inputs.config_hash` — so a run is identified by
the pair, not by the sweep name alone.

## The six

| Sweep | Variable | Baseline → Sweep | Aims to provoke |
|---|---|---|---|
| `congestion-util-75` | `FP_CORE_UTIL` | 40 → 75 | `FAIL_CONGESTION` (partial) |
| `congestion-util-85` | `FP_CORE_UTIL` | 40 → 85 | `FAIL_CONGESTION` (hard) |
| `timing-clk-40mhz` | `CLOCK_PERIOD` | 100 ns → 25 ns | `FAIL_TIMING` |
| `timing-clk-80mhz` | `CLOCK_PERIOD` | 100 ns → 12.5 ns | `FAIL_TIMING` (hard) |
| `aspect-extreme` | `FP_ASPECT_RATIO` | 1 → 4.0 | `FAIL_CONGESTION` (directional) |
| `pdn-sparse` | `PDN_VPITCH` / `PDN_HPITCH` | 153.6 / 153.18 µm → 400 µm | `FAIL_IR_DROP` |

Each file carries its own header comment with the same information plus the
expected shape of the failure. Read the file, not just this table.

The `pdn-sparse` baseline column is the sky130 PDK's own default, which the
baseline inherits rather than restating. It is quoted here with its source;
confirm it against the installed PDK before treating the ratio as measured.

## Why pairs

The four congestion/timing sweeps come in mild/severe pairs on purpose. An
episode is a decision under a specific set of pressures, and "what would you
do about congestion at 75%" is a different question from "what would you do at
85%". Two runs of the same variable at different severities make the
difference between an intervention that scaled and one that did not — which is
the part of expert judgment that is hardest to extract any other way.

## What is recorded, and what is not

**Do not commit run results.** The spec is explicit: run each sweep once to
confirm it either completes or fails *in the intended way*, and record only
the pass/fail shape here — not the metrics. The diagnostic runs, and the
episodes written about them, are the domain expert's.

`runs/` is in `.gitignore`, so a run directory is never committed by accident.

| Sweep | Confirmed? | Shape observed |
|---|---|---|
| `congestion-util-75` | not run | — |
| `congestion-util-85` | not run | — |
| `timing-clk-40mhz` | not run | — |
| `timing-clk-80mhz` | not run | — |
| `aspect-extreme` | not run | — |
| `pdn-sparse` | not run | — |

The table above is empty because no Linux execution environment was reachable
from the machine this repository was built on. Filling it in is the first
thing to do once one is: it is a one-line-per-run record of whether each sweep
provoked the failure it was designed to provoke, and it is the acceptance test
for this whole directory.
