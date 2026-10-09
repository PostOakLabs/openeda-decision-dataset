# Alignment Note: Three EDA AI Research Systems vs. an Expert-Episode Reference Policy

Status: SCAFFOLD ONLY. This note maps *where* an expert-episode reference policy
would plug into each of three EDA AI research systems. It does **not** contain any
episodes, because there are none: `episodes/` in this repo holds a template whose
every *judgment* field is a `TODO(expert)` marker, with only
the fixed identifiers and least-committal enum members filled in (the
`SCAFFOLD_STRINGS` allowlist in `tests/test_episode_assets.py`) -- see
`episodes/README.md`. Every section that would need actual episodes carries an
explicit `BLOCKED-ON-EPISODES` marker; no placeholder prose is used to stand in
for them.

Retrieved date for all sources: **2026-08-31**.

---

## 1. Three-system plug-point table

| System | Optimizes (objective) | Eval loop consumes (inputs / feedback) | Where an expert-episode reference policy would plug in |
|---|---|---|---|
| **ORFS-agent** (arXiv 2506.08332) | Natural-language-weightable flow parameters. §3.1: "The objective function in this work is formulated as F=∑ᵢ αᵢfᵢ, where each fᵢ is a design metric (e.g., routed wirelength, worst negative slack) and each αᵢ is a nonnegative real weight." Abstract: improve the "geometric-mean normalized wirelength, effective clock period, and co-optimization objectives." | §3.1: "The inputs to ORFS-agent include process design kits (PDKs) for the target technology node, target circuits described in Verilog files, and user-defined prompts." Loop reads JSON run logs (READ) and collates them (COLLATE) per §3.2; §1: "Leveraging ORFS's METRICS2.1 logging, the agent skips bad configurations." | §4.5 **Decision Process Analysis** — the section reporting "checkpoint-aligned trajectories and reasoning summaries" (Abstract: "We also report checkpoint-aligned trajectories and reasoning summaries that document the agent's decision process"). A reference policy would pin *why* the iteratively-proposed parameter sets were chosen (INSPECT → OPTIMIZE → AGGLOM step), rather than only observing them post-hoc. `BLOCKED-ON-EPISODES`. |
| **AuDoPEDA** / OpenROAD QoR coding agents (arXiv 2601.06268) | Repository-level PPA: Abstract "routed wirelength reductions of up to 5.9%, effective clock period reductions of up to 10.0%, and power reductions of up to 19.4%." §3.4: "We evaluate candidate changes using a composite score derived from normalized metrics (wirelength (WL), via count, density, timing). Crucially, we employ hard gates…" | §3.4: "The agent iterates using self-measured signals (e.g., routed wirelength (rWL), worst negative slack (WNS), total negative slack (TNS), via count and power)." §3.2: "We maintain two corpora for retrieval: C_repo… and C_lit (EDA papers, tutorials, and documentation covering placement, routing, timing, etc.)." Failures are fed back: "Failures… are converted into counterexamples and fed back into the granular plan for repair." | §3.2 **DSPy-programmed Retrieve-Synthesize-Validate planner**: "Retrieve. Given an objective… the planner retrieves relevant information from both C_repo and C_lit." An expert-episode reference policy would seed/weight this retrieve step (and the S1/S2 counterexample feedback loop) with recorded expert repair decisions instead of docs alone. `BLOCKED-ON-EPISODES`. |
| **FluxBench** (arXiv 2607.17528) | Task-specific EDA "return": §4.2 "we use the normalized task-specific score S_k∈[0,1] as the EDA return." Scoring per Table 1 (e.g., R_final = λ_P·S_P(P) + λ_aware·S_aware(I_PAECO) + …; Appendix A: "S = 0.2 S_stage + 0.8 S_result"). | §3.1: "the agent can access only the task description, public inputs, and editable files, without visibility into hidden tests, reference solutions, or internal scoring data." §4.2 trajectory: "let the agent trajectory be τ_k=(p_k,{(y_t,o_t)}ₜ₌₁^T)"; Token ROI = "the EDA return per unit token investment and per unit execution time." | §4.2 / §4.3 **process-level evaluation** — trajectories τ_k are recorded and compared, and §3.3 notes "reference results and final evaluation logic are used by the evaluator only after the task is completed." An expert-episode reference policy would be the *reference trajectory baseline* the agents' trajectories are scored against, not merely the hidden final answers. `BLOCKED-ON-EPISODES`. |

---

## 2. Field-status anchor and taxonomy position

The field-status anchor is the ISPD'26 invited paper **"Invited: Agentic AI for
Physical Design R&D: Status and Prospects"** (Procs. ISPD '26, pp. 133–141, DOI
10.1145/3764386.3779612, published 27 March 2026). Its abstract frames the whole
frame of reference for this corpus: "agentic AI systems can comprehend user
specifications, modify code, run EDA tools, analyze results, perform multi-step
reasoning, and iteratively refine design heuristics." It surveys the landscape as
"(i) tool-integrated agents for algorithm evolution, debugging, and workflow
automation, (ii) autonomous exploration of heuristic spaces in placement, routing,
and partitioning, and (iii) interfaces between agents and traditional EDA
frameworks," and closes on the not-yet-realized prospect of "closed-loop learning
from large design corpora." This note's three systems sit squarely inside that
frame: ORFS-agent and AuDoPEDA are tool-integrated agents for tuning/coding the
flow, and FluxBench is the benchmark-evaluation axis.

For **taxonomy position**, the anchor is the agentic-EDA survey **"The Dawn of
Agentic EDA: A Survey of Autonomous Digital Chip Design"** (arXiv 2512.23189, v2,
7 Feb 2026). It frames agentic EDA "not merely as 'Chat with Tools,' but as a
Constrained Neuro-Symbolic Optimization problem," and "propose[s] a novel taxonomy
rooted in a Cognitive Stack—Perception (aligning multimodal semantics), Cognition
(planning under strict constraints), and Action (deterministic tool execution)."
Its autonomy levels (L0–L1 tool-assisted, L2 copilots, L3 agentic orchestration,
L4 self-driving) place our systems at L3: "AI drives tasks, Human monitors." The
survey's Table 1 classifies **ORFS-Agent** as Backend / MAS (Multi-Agent
Orchestration), role "Agent", output "optimized soln.", eval "QoR / runtime" —
precisely the row this corpus would target — while AuDoPEDA-type repository-grounded
code evolution and FluxBench-style end-to-end benchmarking belong to the survey's
backend "Agent-Centric orchestrators" and its §3.3 / §5.3 benchmarking critiques
("System-Level Benchmarking… that evaluate end-to-end PPA outcomes").
`BLOCKED-ON-EPISODES`: this note asserts placement in the taxonomy only; it asserts
nothing about any effect of this corpus on any of these systems.

---

## 3. Sources

All retrieved 2026-08-31.

| # | Title | Venue / arXiv id | URL |
|---|---|---|---|
| 1 | ORFS-agent: Tool-Using Agents for Chip Design Optimization (Ghose, Kahng, Kundu, Wang) | arXiv 2506.08332 (v3); Proc. MLCAD 2025 pp.1–13 | https://arxiv.org/abs/2506.08332 |
| 2 | Automated QoR improvement in OpenROAD with coding agents (Ghose, Jang, Kahng, Lee) — AuDoPEDA | arXiv 2601.06268 (v2) | https://arxiv.org/abs/2601.06268 |
| 3 | Can AI Agents Really Complete RTL-to-GDS? Lessons from Benchmarking Tool-Interactive EDA Workflows (Deng et al.) — FluxBench | arXiv 2607.17528 (v1) | https://arxiv.org/abs/2607.17528 |
| 4 | Invited: Agentic AI for Physical Design R&D: Status and Prospects (Ghose, Kahng, Kundu, Pramanik) | ISPD '26 proc., pp.133–141, DOI 10.1145/3764386.3779612 | https://dl.acm.org/doi/10.1145/3764386.3779612 |
| 5 | The Dawn of Agentic EDA: A Survey of Autonomous Digital Chip Design (Zang et al.) | arXiv 2512.23189 (v2) | https://arxiv.org/abs/2512.23189 |
