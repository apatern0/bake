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

"""The built-in blackbox flow: the views a macro lacks, from its LEF, with
bake.lef. It runs under bake's interpreter (its first line leaves the
interpreter to PATH, see Step.execute_flow_step), which has bake.

$BAKE_BLACKBOX_VERILOG and $BAKE_BLACKBOX_LIBERTY name the files to write
(empty: the macro has that view); $BAKE_BLACKBOX_PINS is the timing of the
block's pins. Signal pins it leaves untimed are listed as a warning."""

import json
import logging
import os
import sys

from bake import lef

logging.basicConfig(level=logging.INFO, format="[blackbox] %(levelname)s\t %(message)s", force=True)


def main() -> int:
    with open(os.environ["BAKE_VARS"], encoding="utf-8") as f:
        bake_vars = json.load(f)
    top = bake_vars["BAKE_TOP"]
    macros = lef.read(*bake_vars["BAKE_BLACKBOX_LEFS"])
    if top not in macros:
        logging.error("No MACRO %s in %s (it has: %s)", top, " ".join(bake_vars["BAKE_BLACKBOX_LEFS"]),
                      ", ".join(sorted(macros)) or "none")
        return 1
    macro = macros[top]
    pins = bake_vars["BAKE_BLACKBOX_PINS"]

    if bake_vars["BAKE_BLACKBOX_VERILOG"]:
        os.makedirs(os.path.dirname(bake_vars["BAKE_BLACKBOX_VERILOG"]), exist_ok=True)
        with open(bake_vars["BAKE_BLACKBOX_VERILOG"], "w", encoding="utf-8") as f:
            f.write(lef.verilog(macro, supplies=bake_vars["BAKE_BLACKBOX_SUPPLIES"]))
        logging.info("Wrote %s", bake_vars["BAKE_BLACKBOX_VERILOG"])
    if bake_vars["BAKE_BLACKBOX_LIBERTY"]:
        text = lef.liberty(macro, pins)
        os.makedirs(os.path.dirname(bake_vars["BAKE_BLACKBOX_LIBERTY"]), exist_ok=True)
        with open(bake_vars["BAKE_BLACKBOX_LIBERTY"], "w", encoding="utf-8") as f:
            f.write(text)
        logging.info("Wrote %s", bake_vars["BAKE_BLACKBOX_LIBERTY"])
        left = lef.untimed(macro, pins)
        if left:
            logging.warning("%d digital pin(s) of %s have no timing, and will not be timed: %s "
                            "(config.blackbox.pins[\"%s\"])", len(left), top, ", ".join(left),
                            bake_vars["BAKE_BLOCK"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except lef.LefError as e:
        logging.error("%s", e)
        sys.exit(1)
