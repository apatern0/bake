#!/usr/bin/env python3
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

"""SkyWater 130nm implementation runner — Yosys synthesis + OpenROAD P&R."""

import logging
import os
import shlex
import shutil
import subprocess
import sys

coloredlogs_available = False
try:
    import coloredlogs
    coloredlogs.install(level=logging.DEBUG)
    coloredlogs_available = True
except ImportError:
    logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)

TOP            = "$BAKE_TOP"
LIB_LIBERTY_TT = shlex.split("$BAKE_LIB_LIBERTY_FILES_TT")
LIB_PHYSICAL   = shlex.split("$BAKE_LIB_PHYSICAL")

os.makedirs("output", exist_ok=True)


# ---------------------------------------------------------------------------
# Step 1: Synthesis — Yosys
# ---------------------------------------------------------------------------

logger.info("=== Synthesis (Yosys) ===")

if not LIB_LIBERTY_TT:
    logger.error("No TT-corner liberty files available. Cannot synthesise.")
    sys.exit(1)

subprocess.run(["yosys", "-s", "scripts/synthesis.ys"], check=True)
logger.info("Synthesis complete: output/%s_synth.v", TOP)


# ---------------------------------------------------------------------------
# Step 2: Place-and-Route — OpenROAD (only when LEF files are available)
# ---------------------------------------------------------------------------

if not LIB_PHYSICAL:
    # Without LEF there is nothing to place. Still produce the outputs the impl
    # step promises: the synthesised netlist and an SDF with no delays.
    logger.warning("No physical (LEF) files provided — skipping P&R, "
                   "using the synthesis netlist as the final netlist.")
    shutil.copyfile(f"output/{TOP}_synth.v", f"output/{TOP}.v")
    with open(f"output/{TOP}.sdf", "w") as sdf:
        sdf.write(f'(DELAYFILE (SDFVERSION "3.0") (DESIGN "{TOP}") '
                  f'(CELL (CELLTYPE "{TOP}") (INSTANCE)))\n')
    sys.exit(0)

logger.info("=== Place-and-Route (OpenROAD) ===")

subprocess.run(["openroad", "-exit", "scripts/place_and_route.tcl"], check=True)
logger.info("P&R complete: output/%s.v, output/%s.sdf", TOP, TOP)
