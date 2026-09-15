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

read_verilog -sv $BAKE_INCLUDE_FLAGS $BAKE_DESIGN_VERILOG_FILES

# the high-level stuff
hierarchy

# Synthesis
synth -run coarse -top $BAKE_TOP

# Mapping ffs and logic
dfflibmap -liberty $BAKE_LIB_LIBERTY_FILES_TT
abc -liberty $BAKE_LIB_LIBERTY_FILES_TT

# cleanup
clean

write_verilog -noattr output/${BAKE_TOP}_synth.v
write_json output/$BAKE_TOP.json
stat -liberty $BAKE_LIB_LIBERTY_FILES_TT
