# Copyright 2025 CERN
# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
#
# This file is a modified version of a file from tmake
# (https://gitlab.cern.ch/tmake/tmake), developed at CERN and
# distributed under the Apache License, Version 2.0.
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

[global]
top_module = $BAKE_TOP

[tmrg]
# output directory
tmr_dir     = $BAKE_TMR_OUTPUT_DIR

#number of spaces to be insterted for indentation
spaces      = 2

overwrite_files   = True

# Defines whether common definitions (as majorirtyVoter, fanout) should be
# added to the output verilog file. If yes, the definitions are added to the
# file which contains top level cell. One has to define voter_definition and
# fanout_definition
add_common_definitions = True

# path to the file which contains majorityVoter module declaration
# (relative to tmrg.py script or absolut path)
voter_definition  = ../common/voter.v

# path to the file which contains fanout module declaration
# (relative to tmrg.py script or absolut path)
fanout_definition = ../common/fanout.v

# should SDC file for DC be generated? [true/false]
sdc_generate = false

# should headers of SDC file be added ? [true/false]
sdc_headers = true

# file name of sdc file (if empty, SDC file will have the same name as top module)
sdc_file_name = output/tmrg.sdc

# file list to be processed (space separated)
files = $BAKE_DESIGN_VERILOG_FILES

# libs list to be processed (space separated)
libs =
