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

# Yosys synthesis: RTL to a flat gate-level netlist mapped onto the TT-corner
# Liberty library of the block's libraries.

# Hard macros (implemented sub-blocks) are black boxes described by their
# Liberty; run.py writes the read_liberty calls into macros.ys.
script scripts/macros.ys

read_verilog -sv $BAKE_INCLUDE_FLAGS $BAKE_DESIGN_VERILOG_FILES
hierarchy -check -top $BAKE_TOP

# Generic synthesis down to the internal gate library, flattened so that
# place-and-route sees one module.
synth -top $BAKE_TOP -flatten

# Technology mapping: flip-flops, then combinational logic.
dfflibmap -liberty $BAKE_LIB_LIBERTY_FILES_TT
abc -liberty $BAKE_LIB_LIBERTY_FILES_TT

# Constant drivers: tie cells when the PDK names them (flow option tie_cells;
# run.py writes the hilomap call into tie_cells.ys), plain assignments otherwise.
setundef -zero
script scripts/tie_cells.ys
opt_clean -purge

write_verilog -noattr -noexpr output/${BAKE_TOP}_synth.v
write_json output/$BAKE_TOP.json
stat -liberty $BAKE_LIB_LIBERTY_FILES_TT
