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

"""Implementation runner: Yosys synthesis, then OpenROAD place-and-route.

PDK-agnostic: the Liberty and LEF files come from the libraries the manifest
registers; example/pdk/sky130/manifest shows how.
"""

import json
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

# The template variables, as bake wrote them to bake_vars.json (lists stay
# lists, so paths with spaces survive).
with open(os.environ.get("BAKE_VARS", "bake_vars.json"), encoding="utf-8") as f:
    V = json.load(f)


def as_list(value):
    """A flow option may be a list, a tuple or a plain string."""
    return shlex.split(value) if isinstance(value, str) else list(value)


TOP            = V["BAKE_TOP"]
LIB_LIBERTY_TT = V["BAKE_LIB_LIBERTY_FILES_TT"]
LIB_PHYSICAL   = V["BAKE_LIB_PHYSICAL"]
TIE_CELL_HI    = as_list(V["BAKE_FLOW_OPT_TIE_CELLS_HI"])   # [cell, pin] or []
TIE_CELL_LO    = as_list(V["BAKE_FLOW_OPT_TIE_CELLS_LO"])
MACRO_LIBERTY_TT = V["BAKE_MACRO_LIBERTY_FILES_TT"]

os.makedirs("output", exist_ok=True)

# Hard macros enter synthesis as black boxes from their Liberty files.
with open("scripts/macros.ys", "w") as macro_script:
    for lib_file in MACRO_LIBERTY_TT:
        macro_script.write(f"read_liberty -lib {lib_file}\n")

# Translate the tie_cells flow option into Yosys's hilomap call; the synthesis
# script sources the file, so no cells means no mapping.
with open("scripts/tie_cells.ys", "w") as tie_script:
    hilomap = []
    if TIE_CELL_HI:
        hilomap += ["-hicell"] + TIE_CELL_HI
    if TIE_CELL_LO:
        hilomap += ["-locell"] + TIE_CELL_LO
    if hilomap:
        tie_script.write("hilomap " + " ".join(hilomap) + "\n")


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
