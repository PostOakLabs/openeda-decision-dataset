# SDC / Constraint-Derivation Pattern Scaffolding

Status: SCAFFOLD ONLY. Annotation scaffolding for reviewers and agent
plumbing, not expert data. Nothing in this file enters the episode corpus:
per the non-graduation rule below, any use downstream carries
`provenance: synthetic-fixture` until the domain expert rewrites it.

Provenance block (lifted from `digest/sdc-patterns.md`, 2026-09-04 read):
- Origin: free-model harvest, run marker `free-model-harvest/G/2026-08-31`
  (11 G-files → 88 pattern drafts from 10 models + one prose refusal).
- Merge + arithmetic recomputation: `digest/sdc-patterns.md` (2026-08-31);
  every worked example recomputed there: `✅ closes` = internally
  consistent, `⚠ partial` = closes with a misplaced/double-counted term,
  `❌ does not close` = wrong formula or example.
- Error-rate finding, verbatim: "Arithmetic error rate: 4 hard errors (❌)
  and 3 partials (⚠) across the ~25 drafts that carry worked numbers, i.e.
  roughly one in four numeric derivations does not survive recomputation…
  None of these was caught by the models' own confidence fields — the
  erroneous drafts self-rated 0.85–0.98, the same band as the correct ones.
  Confidence in this corpus predicts fluency, not correctness."
- Non-graduation rule, verbatim in substance: enters any downstream use as
  `provenance: synthetic-fixture`; graduates only through the domain expert's rewriting
  or a reproduced flow run.
- Convergence warning, verbatim in substance: 88 drafts collapse to 13
  canonical patterns with 5 claimed by all 10 models in near-identical
  structure — "that distribution looks like shared textbook provenance
  rather than independent knowledge."
- Defective derivations are NOT in the patterns below. Each lives in the
  appendix ("Known-defective, excluded") with its defect one-liner, so the
  exclusion is auditable, not silent.

`TODO(expert): review — priority order is pattern 7 (period-squeeze vs
uncertainty), pattern 4 (max_delay on CDC), pattern 1 (the -min omission),
then the rest.`

---

## Pattern 1 — Block-boundary input/output delay budget

`models: all 10` · 14 of 88 drafts · the universal pattern.

**Situation.** A block is implemented before its neighbour exists, but its
interface timing must represent the eventual top-level contract.

**Derivation (merged, corrected).** From the interface period T account for:
upstream clock-to-Q, upstream logic, interconnect, downstream logic, capture
setup, clock uncertainty, named margin. `set_input_delay` = everything
outside the block before data arrives (upstream Tcq + upstream logic +
interconnect). `set_output_delay` = everything outside after data leaves
(interconnect + downstream logic + downstream setup). Internal budget =
`T − boundary_delay − uncertainty`.

**Best worked example (qwen, ✅ closes).** T = 1000 ps, wire 100 ps, setup
50 ps → logic budget 850 ps split 50/50 → 425 ps each. `set_output_delay(A)
= 525 ps`, A internal `1000 − 525 − 50 = 425 ps`; symmetric input_delay(B)
= 525 ps. Stated closure: `425 + 100 + 425 + 50 = 1000 = T`. ⚠ caveat
carried: per-block lines subtract setup on both sides while closure counts
it once — fix the A-side line before reuse.

**Second-best (grok, ✅ closes).** T = 2.0 ns; ext. uncertainty 0.15 + ext.
logic 0.6 + package 0.1 → `input_delay max = 0.85 ns`, internal 1.15 ns.

**wrong_way (chatgpt).** "Assigning a convenient value such as 50% of the
period to input_delay and 50% to output_delay without accounting for
clock-to-Q, interconnect, setup, skew, uncertainty, or asymmetry silently
transfers an impossible burden to one block."

**signoff_risk.** Too tight → over-optimization (buffering, area, power,
congestion). Too loose → clean local STA, integrated failure discovered
after freeze; ECO or frequency cut only (yuanbao).

**Kept note.** Pair `-max` with `-min` (yuanbao — only draft to state it);
skipping `-min` leaves hold unconstrained on boundary paths.

## Pattern 2 — Asymmetric split between two unimplemented blocks

`models: chatgpt, gemini, grok, meta, minimax 2.7, minimax 3, mistral, qwen,
yuanbao` (9).

**Derivation.** Split residual budget by estimated logic depth, not halves
(meta: 20 vs 10 FO4 stages → 66/33 ✅; `T_A = T_total × L_A / (L_A + L_B +
L_wire)` mistral/qwen; minimax 3: 60% blocks / 20% interconnect / 20%
skew+margin ✅; yuanbao: document the depth assumption explicitly).

**Best worked example (qwen, ✅ closes).** T = 1000 ps; 2 stages × 400 ps +
100 wire + 50 setup = 950, 50 slack. `output_delay(A) = 500`, documented
15% over-constraint → 575 ps; A closes in 375 ps. Separates budget from
margin explicitly — the only draft to do so.

**wrong_way (minimax 2.7).** "Splitting 50/50 because it is simple, without
considering that one block may be fundamentally more complex."

**signoff_risk (yuanbao).** "An interface never jointly validated against
real netlists is a classic source of last-minute frequency cuts."

**Consensus caveat (yuanbao).** "Output delay on A is the same physical
constraint as input delay on B — defining them inconsistently creates a
contradictory budget neither side can meet." (gemini's swapped-port
derivation, which violates exactly this, is excluded — see appendix.)

## Pattern 3 — False path vs multicycle path

`models: all 10` · highest-confidence pattern in the corpus.

**Derivation (consensus, correct).** False path iff the path can never be
launched/captured in adjacent cycles under any legal sequence (exclusive
modes, static config, scan-only). Else multicycle:
`set_multicycle_path N -setup` **paired with** `set_multicycle_path N-1
-hold`, N from the RTL/protocol event sequence, never from wanted slack.
**7-model agreement** (chatgpt, gemini, grok, meta, minimax 3, qwen,
yuanbao) with three independently phrased N−1 explanations — the single
most repeated substantive claim in the corpus. **Unresolved caveat
carried:** worth the domain expert's confirmation for the opposite-edge case, which
two drafts flag as an exception and none resolves.

**Why N−1 (qwen).** "The hold is set to N−1 because the default hold check
is at the same edge; with setup at edge N, hold must be checked at edge
N−1." Cost of omitting it (gemini, ✅ consistent): MCP 4 setup with no
hold exception at 1 ns forces 3.0 ns of redundant buffers — area bloat,
routability failure.

**wrong_way (minimax 3).** "Defaulting to `set_false_path` for anything
that 'looks slow' … cells never sized for delay, never hold-checked —
signoff hold failure or leakage from minimum-size cells."

**signoff_risk (yuanbao).** "Among the most dangerous SDC errors because
they pass STA cleanly yet fail in silicon."

**Extra check (qwen).** Re-verify the N-cycle guarantee across ALL modes
(normal, debug, scan, low-power).

## Pattern 4 — Asynchronous CDC constraint

`models: all 10`.

**Derivation (consensus).** Establish no phase relationship first. If async
with real synchronizers: `set_clock_groups -asynchronous -group {clkA}
-group {clkB}`; bound the synchronizer data path with `set_max_delay
-datapath_only` (majority: chatgpt, grok, meta, mistral, qwen, yuanbao,
deepseek — grok's quantity: fraction, often ½–⅔, of the receiving period;
qwen's case: gray FIFO pointers, e.g. 500 ps at 1 GHz).

**Carried dispute, digest-resolved (not re-resolved here).** Minority (minimax
2.7; minimax 3 for handshakes): no max_delay on async paths. Digest
resolution: majority right — `-datapath_only` bounds wire delay into the
first flop (no implied clock relationship); the objection holds only for a
boundary-spanning max_delay without it. yuanbao's extra `set_min_delay`
proposal flagged probably-wrong (second flop protected by its own clock).

**wrong_way (qwen).** "Blanket `-asynchronous` between all pairs without
auditing synchronizer existence — clean STA hiding unprotected paths."
meta adds: `-logically_exclusive` for async clocks corrupts crosstalk/CRPR.

**signoff_risk (yuanbao).** "CDC mistakes are a leading cause of chips that
'work on the bench but fail in the field'."

**MTBF note (minimax 3, symbolic, unverified).** The constraint carries no
arithmetic; the MTBF does — `MTBF = exp(t_res / C) / (fA · fB · fc)`.

## Pattern 5 — Virtual clock for external / off-chip I/O

`models: all 10`.

**Derivation (consensus, correct).** Virtual clock at the external reference
period. `set_input_delay -max` = ext. Tco(max) + trace(max); `-min` =
Tco(min) + trace(min). `set_output_delay -max` = downstream setup + trace;
`-min` = −(downstream hold − trace skew). The virtual clock is a reference,
not an internal-clock claim.

**Best worked example (gemini, ✅ closes).** T = 10.0 ns; Tco 4.5/1.0,
flight 1.2/0.8 → `-max = 5.7`, `-min = 1.8`. **Second (qwen, ✅ closes).**
PHY 10 ns, valid 2 ns after edge → 2 ns; internal `10 − 2 − setup ≈ 7.5 ns`.

**wrong_way (gemini).** "Constraining DATA_IN to internal CLK_CORE — P&R
folds 2.5 ns of tree latency into the I/O path, impossible setup closure."

**signoff_risk (yuanbao).** "May pass STA but fail on the board (optimistic
board models baked into the virtual clock)."

**Closure identities (yuanbao, grok).** Always pair `-max`/`-min`;
pad-to-pad: `input_delay + feedthrough + output_delay` = virtual period.

## Pattern 6 — Generated / divided clock derivation

`models: all 10`.

**Derivation (consensus, correct).** `create_generated_clock -source
<physical pin of the master> … -divide_by N` (or -multiply_by/-edges,
`-add` per mux source) **on the generating pin**, never a fresh
`create_clock`. yuanbao (most precise): source = master origin (divider CK
pin, PLL input); unmodeled mux sources leave paths untimed. Closure
identity (minimax 3, ✅): `f_src·M/N` ⇒ `T_src·N/M` for boundary budgets.

**wrong_way (unanimous).** Independent `create_clock` on the divider output:
edge misalignment, meaningless exceptions, misleading CTS, grok: "setup/hold
windows wrong by a factor of N."

**Caveats (chatgpt; minimax 3).** Divide-by-N need not be 50% duty cycle —
asymmetric edge sequences survive correct `-divide_by`. `-multiply_by M`
must match the silicon PLL configuration, or a perfect constraint is
externally false.

**signoff_risk (yuanbao).** "At advanced nodes, a wrong generated-clock
phase can create millions of false violations that obscure real ones."

## Pattern 7 — Early over-constraint with staged relaxation

`models: chatgpt, deepseek, grok, meta, minimax 2.7, mistral, qwen, yuanbao`
(8) · widest advice spread in the corpus.

**Schedules (all recomputed ✅ except as noted):** qwen 0.80–0.85T →
0.90 → 1.0 milestone-tied; minimax 2.7 1.2 GHz-for-1 GHz (16.7% headroom);
meta 0.9T + 100 ps@28nm / 60 ps@7nm + `max_delay 0.85T`; deepseek 0.85T
from prior-tapeout 15% degradation (only draft naming the number's
source); grok uncertainty-only (+30–50 ps); mistral 0.15T/0.10T + 0.7T
(⚠ no source, very large); yuanbao staged uncertainty 0.25 → 0.12 →
0.08+OCV, never to zero guardband.

**Open question carried (most useful in the corpus for an expert):**
squeeze the period (qwen/meta/minimax 2.7/deepseek) or add uncertainty
(grok/yuanbao)? Nobody argues it explicitly.

**wrong_way, both directions.** Never relaxing (meta, quantified:
20–30% extra buffers, 15% area @28nm; impossible @7nm). Relaxing
carelessly (chatgpt): healthy-looking implementation, silently reduced
signoff margin.

**Discipline (yuanbao, ✅ 250−80=170).** Initial = jitter + estimated skew
+ guardband; final = jitter only; carry guardband to signoff. Third
failure mode (yuanbao only): relaxing uncertainty while forgetting
ideal→propagated clocks or OCV enablement removes margin twice unseen.

## Pattern 8 — Clock uncertainty composition (jitter + skew)

`models: deepseek, gemini, grok, meta` (4).

**Worked example (gemini, ✅ closes — cleanest derivation in the corpus).**
T = 1.0 ns. Pre-CTS 50+30+40 = 120 ps; post-CTS measured skew 42 →
30+40 = 70; post-route SI-extracted → 30 ps jitter only. Each stage drops
exactly the term gone real.

**Principle (grok).** Setup: full sum. Hold: smaller subset (local OCV +
small margin) **because global jitter is common-mode** — resolves
deepseek's muddled negative-hold-uncertainty passage (excluded, appendix).

**wrong_way (grok).** "Flat 100 ps for every clock regardless of period or
PLL quality; forgetting hold reduction."

## Pattern 9 — Mode-dependent / multi-mode constraint derivation

`models: chatgpt, mistral` (2).

**Derivation (chatgpt, best-reasoned draft in the corpus).** Enumerate
legal modes; derive clocks, cases, IO, exceptions per configuration.
"Exclude a path only when the mode configuration makes it impossible…
The final MMMC set is the UNION of mode-specific legal relationships,
not the intersection of every possible clock relationship."

**wrong_way (chatgpt).** "One broad false path covering all modes because
two clocks are async in one configuration — disables real checks in
another." (mistral's `-case` syntax excluded — appendix; its idea is
carried by chatgpt's union rule.)

## Pattern 10 — Point-to-point max/min delay, non-clocked interfaces

`models: grok` (1) · singleton worth keeping — the only pattern for
interfaces with no usable clock reference. `budget = required external
window − external setup/hold − board delay`; max_delay keeps the path
short, min_delay stops external-hold violation. wrong_way: lone
false_path or mismatched clocked IO delay. signoff_risk enumerates all
four directions (most complete in the corpus).

## Pattern 11 — Source-synchronous / forwarded-clock budgeting

`models: gemini` (1, yuanbao DDR detail support).

Distinct from pattern 5: forwarded-clock receiver cancels tree latency,
so internal-clock constraining forces P&R to remove nonexistent skew
(gemini's wrong_way — the only draft where over-constraining is wrong
for a STRUCTURAL reason). yuanbao details: `-max = Tco_max +
board_trace_max − board_clock_trace_min` (mirrored `-min`); DDR both
edges (`-clock_fall -add_delay`); forgotten `-add_delay` silently
overrides one edge — appears nowhere else.

## Pattern 12 — Clock-network latency inclusion/exclusion

`models: mistral` (1) · **recorded, not recommended.** Names the real
question (when clock latency enters the check; ideal vs propagated;
what CRPR credits) with suspect commands/reasoning (excluded —
appendix). Kept because no other draft addresses the question.

## Pattern 13 — Reset and static-configuration false paths

`models: yuanbao` (1) · singleton, high practical value. Scope false
paths minimally (select-pin only on scan muxes); "false path removes the
check; `set_case_analysis` removes a logic state — use both." wrong_way:
wildcard `-from [get_cells *]`; false-pathed synchronous-in-some-modes
resets; scan paths forgotten in DFT SDC; stale false paths after ECO
("a notorious source of escaped bugs").

---

## Appendix — known-defective, excluded (auditable, not silent)

Derivations the merge marks ❌/⚠/flagged — excluded from the patterns
above; listed here so no exclusion is silent:

- P1 deepseek inverted I/O delays (❌): input/output formulas backwards on
  both sides; resolution: do not reuse (conf. 0.95 — fluency≠correctness).
- P2 gemini swapped port assignment (❌): `output_delay 1.10` on A /
  `input_delay 0.90` on B; keep its wrong_way (50/50 leaves 680 ps slack),
  discard the derivation (conf. 0.95).
- P3 minimax 2.7 off-by-one multicycle (❌): `-setup 1` relaxes nothing;
  paired hold 0 wrong; majority N/N−1 stands (conf. 0.91).
- P5 meta formula-vs-example (❌): stated `T_ext − Tsu − board + margin`
  vs worked `Tco + board = 2.5 ns`; keep the example, discard the formula.
- P5 mistral internal-setup formula (❌): external budget built from
  internal setup + unexplained half-period; self-contradicted by its own
  wrong_way.
- P5 gemini DDR sign (⚠): `min` computed +0.30 then written `-0.30`;
  unresolvable without the sign convention — do not reuse either line.
- P1 qwen A-side double-count (⚠): closure holds; fix the A-side setup
  subtraction before reuse.
- P2 mistral uncertainty size (⚠): 0.15T with no source; very large.
- P8 deepseek hold-half muddle (⚠): three incompatible hold statements;
  grok's common-mode principle above resolves the confusion.
- P9 mistral `-case` syntax (❌): no such option; idea carried by P9's
  union rule.
- P12 mistral commands + half-true latency claim (flagged): `…-max
  -include` do not exist; latency cancels only over the common path
  (CRPR's credit). Question kept, commands excluded.
- P4 yuanbao `set_min_delay` on CDC (flagged probably-wrong): second flop
  protected by its own clock; needs the domain expert's ruling before propagation.

`BLOCKED-ON-EPISODES`: nothing here is an episode and nothing here claims
an effect on any flow or system. Publish-gating unchanged: repo-internal
annotation scaffolding; no external publishing implied.
