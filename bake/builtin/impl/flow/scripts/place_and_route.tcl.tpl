# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# OpenROAD place-and-route for the synthesised netlist.
#
# Everything technology-specific arrives through template variables: the
# libraries a manifest registered (BAKE_LIB_* variables) and the flow options
# (BAKE_FLOW_OPT_* variables) whose defaults the yosys-openroad FlowSpec declares
# and a PDK manifest or project overrides with config.impl.flow_options.

# ---------------------------------------------------------------------------
# Technology and libraries
# ---------------------------------------------------------------------------

foreach lef_file [list $BAKE_LIB_PHYSICAL] {
    read_lef $$lef_file
}

# Hard macros: implemented sub-blocks, integrated from their abstracts.
set macro_lefs [list $BAKE_MACRO_PHYSICAL]
foreach lef_file $$macro_lefs {
    read_lef $$lef_file
}

# One STA corner per corner that has Liberty files. define_corners has to
# come before any read_liberty -corner.
set corner_libs [dict create \
    TT [list $BAKE_LIB_LIBERTY_FILES_TT $BAKE_MACRO_LIBERTY_FILES_TT] \
    FF [list $BAKE_LIB_LIBERTY_FILES_FF $BAKE_MACRO_LIBERTY_FILES_FF] \
    SS [list $BAKE_LIB_LIBERTY_FILES_SS $BAKE_MACRO_LIBERTY_FILES_SS] \
]
set corners {}
dict for {corner libs} $$corner_libs {
    if {[llength $$libs] > 0} { lappend corners $$corner }
}
if {[llength $$corners] == 0} {
    puts "ERROR: no Liberty files for any corner"
    exit 1
}
define_corners {*}$$corners
foreach corner $$corners {
    foreach lib_file [dict get $$corner_libs $$corner] {
        read_liberty -corner $$corner $$lib_file
    }
}

# ---------------------------------------------------------------------------
# Design and constraints
# ---------------------------------------------------------------------------

read_verilog output/${BAKE_TOP}_synth.v
link_design $BAKE_TOP

foreach sdc_file [list $BAKE_SDC_FILES] {
    read_sdc $$sdc_file
}
if {[llength [all_clocks]] == 0} {
    puts "WARNING: no clock defined (no sdc_files on the block, or none with create_clock);"
    puts "         skipping clock tree synthesis and timing-driven repair."
}

# Wire RC estimates for the placement and CTS steps and for the final SDF.
if {"$BAKE_FLOW_OPT_SIGNAL_LAYER" ne ""} {
    set_wire_rc -signal -layer $BAKE_FLOW_OPT_SIGNAL_LAYER
}
if {"$BAKE_FLOW_OPT_CLOCK_LAYER" ne ""} {
    set_wire_rc -clock -layer $BAKE_FLOW_OPT_CLOCK_LAYER
}

# ---------------------------------------------------------------------------
# Floorplan, placement, clock tree, routing
# ---------------------------------------------------------------------------

initialize_floorplan \
    -utilization $BAKE_FLOW_OPT_CORE_UTILIZATION \
    -aspect_ratio $BAKE_FLOW_OPT_ASPECT_RATIO \
    -core_space $BAKE_FLOW_OPT_CORE_MARGIN \
    -site $BAKE_FLOW_OPT_SITE
make_tracks

place_pins -hor_layers $BAKE_FLOW_OPT_PIN_HOR_LAYERS -ver_layers $BAKE_FLOW_OPT_PIN_VER_LAYERS

global_placement -density $BAKE_FLOW_OPT_PLACE_DENSITY
if {[llength $$macro_lefs] > 0} {
    # Macros get their final positions from the macro placer, then the
    # standard cells are placed around them.
    macro_placement -halo {$BAKE_FLOW_OPT_MACRO_HALO} -channel {$BAKE_FLOW_OPT_MACRO_CHANNEL}
    global_placement -density $BAKE_FLOW_OPT_PLACE_DENSITY
}
detailed_placement
check_placement -verbose

if {[llength [all_clocks]] > 0} {
    repair_clock_inverters
    clock_tree_synthesis -buf_list {$BAKE_FLOW_OPT_CTS_BUFFERS}
    detailed_placement
}

global_route

# Wire parasitics from the global routes (a per-layer RC extraction would
# need a technology RC file; the estimate is what the SDF is based on).
if {"$BAKE_FLOW_OPT_SIGNAL_LAYER" ne ""} {
    estimate_parasitics -global_routing
}

detailed_route -output_drc output/${BAKE_TOP}_drc.rpt

# ---------------------------------------------------------------------------
# Outputs: the netlist and SDF are what the impl step hands to the next step
# in the recipe (e.g. impl-vrf simulates them); the DEF is for inspection.
# ---------------------------------------------------------------------------

write_def     output/$BAKE_TOP.def
write_verilog output/$BAKE_TOP.v
write_sdf -corner [lindex $$corners 0] output/$BAKE_TOP.sdf
foreach corner $$corners {
    write_sdf -corner $$corner output/${BAKE_TOP}_$${corner}.sdf
}

# Abstracts: what a block including this one after impl integrates it with.
write_abstract_lef output/$BAKE_TOP.lef
foreach corner $$corners {
    write_timing_model -corner $$corner -library_name ${BAKE_TOP}_$${corner} \
        output/${BAKE_TOP}_$${corner}.lib
}
report_checks -corner [lindex $$corners 0]
