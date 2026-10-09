# SPDX-License-Identifier: Apache-2.0
#
# Constraints for Ibex (top module `ibex_top`) on a single clock domain.
#
# Derivative work notice (Apache-2.0 section 4, LIC-4, 2026-09-02):
# This file is a DERIVATIVE of LibreLane's `scripts/base.sdc`
# (https://github.com/librelane/librelane, Apache-2.0, (c) the FOSSi
# Foundation). The Tcl constraint structure -- the input/output delay
# expression, the max-fanout / max-transition / max-capacitance blocks, the
# all_inputs_wo_clk idiom, the SYNTH_CLK_DRIVING_CELL fallback and both
# set_driving_cell blocks -- is reproduced from that file. The modifications
# relative to the upstream `base.sdc` are:
#   * the clock is fixed to a single named port (`clk_i`) and a single clock
#     domain (no multi-clock / __VIRTUAL_CLK__ handling, no dummy-clock
#     fallback, no port-count branching);
#   * `set_clock_uncertainty` / `set_clock_transition` are absolute numbers
#     (0.25 / 0.15) rather than scaled from the period, so the sweep variable
#     (the period) and the uncertainty do not move together;
#   * the set_input_delay / set_output_delay reference `[get_clocks
#     $clock_port]` directly instead of a cached `$clocks` variable;
#   * the `SYNTH_DRIVING_CELL`-only `set_driving_cell` for the non-clock
#     inputs is dropped (there is one cell for both clock and data here), and
#     the OUTPUT_CAP_LOAD / timing-derate / propagated-clock blocks are
#     omitted (not needed for the baseline run);
#   * the multi-clock / resetn handling and the `puts "[INFO] ..."` chatter
#     are removed.
#
# The upstream Librelane license (Apache-2.0) is reproduced in LICENSE; the
# only license grant that applies here is Apache-2.0.
#
# It mirrors the structure of LibreLane's `scripts/base.sdc` so that the
# variables the flow exports (CLOCK_PERIOD, IO_DELAY_CONSTRAINT,
# MAX_FANOUT_CONSTRAINT, SYNTH_DRIVING_CELL) are still honoured.

set clock_port clk_i

create_clock -name $clock_port -period $::env(CLOCK_PERIOD) [get_ports $clock_port]

# Clock uncertainty and transition are given as absolute numbers rather than a
# percentage of the period: the sweeps in flow/sweeps/ change the period by
# 4x-8x, and an uncertainty that scaled with it would move the goalposts at
# the same time as the variable under test.
set_clock_uncertainty 0.25 [get_clocks $clock_port]
set_clock_transition 0.15 [get_clocks $clock_port]

set input_delay_value [expr $::env(CLOCK_PERIOD) * $::env(IO_DELAY_CONSTRAINT) / 100]
set output_delay_value [expr $::env(CLOCK_PERIOD) * $::env(IO_DELAY_CONSTRAINT) / 100]

set_max_fanout $::env(MAX_FANOUT_CONSTRAINT) [current_design]

if { [info exists ::env(MAX_TRANSITION_CONSTRAINT)] } {
    set_max_transition $::env(MAX_TRANSITION_CONSTRAINT) [current_design]
}

if { [info exists ::env(MAX_CAPACITANCE_CONSTRAINT)] } {
    set_max_capacitance $::env(MAX_CAPACITANCE_CONSTRAINT) [current_design]
}

set clk_input [get_port $clock_port]
set clk_indx [lsearch [all_inputs] $clk_input]
set all_inputs_wo_clk [lreplace [all_inputs] $clk_indx $clk_indx ""]

set_input_delay $input_delay_value -clock [get_clocks $clock_port] $all_inputs_wo_clk
set_output_delay $output_delay_value -clock [get_clocks $clock_port] [all_outputs]

if { ![info exists ::env(SYNTH_CLK_DRIVING_CELL)] } {
    set ::env(SYNTH_CLK_DRIVING_CELL) $::env(SYNTH_DRIVING_CELL)
}

set_driving_cell \
    -lib_cell [lindex [split $::env(SYNTH_CLK_DRIVING_CELL) "/"] 0] \
    -pin [lindex [split $::env(SYNTH_CLK_DRIVING_CELL) "/"] 1] \
    $all_inputs_wo_clk

set_driving_cell \
    -lib_cell [lindex [split $::env(SYNTH_CLK_DRIVING_CELL) "/"] 0] \
    -pin [lindex [split $::env(SYNTH_CLK_DRIVING_CELL) "/"] 1] \
    $clk_input
