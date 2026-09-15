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

# Read LEF (tech + cells)
foreach lef_file [list $BAKE_LIB_PHYSICAL] {
    read_lef $$lef_file
}

# Read timing libraries (all corners)
foreach lib_file [list $BAKE_LIB_LIBERTY_FILES_TT] {
    read_liberty $$lib_file
}
foreach lib_file [list $BAKE_LIB_LIBERTY_FILES_FF] {
    read_liberty -corner FF $$lib_file
}
foreach lib_file [list $BAKE_LIB_LIBERTY_FILES_SS] {
    read_liberty -corner SS $$lib_file
}

read_verilog output/${BAKE_TOP}_synth.v
link_design $BAKE_TOP

initialize_floorplan \
    -utilization 30 \
    -aspect_ratio 1 \
    -core_space 2

place_pins -random

global_placement -density 0.6
detailed_placement
check_placement -verbose

clock_tree_synthesis
repair_clock_inverters

global_route -guide_file output/$BAKE_TOP.guide
detailed_route -output_drc output/${BAKE_TOP}_drc.rpt \
               -output_maze output/${BAKE_TOP}_maze.log

# Final outputs: these two are what the impl step hands to the next step in
# the recipe (e.g. tmr-impl-vrf simulates them). Wire delays are not
# estimated here; add set_wire_rc/estimate_parasitics before write_sdf for
# back-annotated timing that includes interconnect.
write_def     output/$BAKE_TOP.def
write_verilog output/$BAKE_TOP.v
write_sdf     output/$BAKE_TOP.sdf
