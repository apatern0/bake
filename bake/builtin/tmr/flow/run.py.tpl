#!/usr/bin/env python3
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

"""tmrg run script template"""
# pylint: disable=invalid-name,broad-except

import logging
import os
import shlex
import subprocess
import signal
import sys
import functools
import hashlib
import re

import coloredlogs


def generate_cell_lib(fname_in, fname_out, ff_patterns, skip_patterns, seu_reset_pin, seu_set_pin):
    """Reduce a standard-cell Verilog library to port declarations.

    Only module/input/output/endmodule lines are kept, so tmrg sees the cell
    interfaces without the behavioural models. Modules matching one of the
    `ff_patterns` regexes are annotated with the async set/reset pin names for
    tmrg's SEU injection; modules matching `skip_patterns` are dropped.
    """
    ff_re   = [re.compile(p) for p in ff_patterns]
    skip_re = [re.compile(p) for p in skip_patterns]
    ignore_module = False
    with open(fname_in) as fin, open(fname_out, "w") as fout:
        for line in fin:
            stripped = line.lstrip()
            if stripped.startswith("module"):
                parts = stripped.split()
                name = parts[1].split("(")[0] if len(parts) > 1 else ""
                ignore_module = any(r.search(name) for r in skip_re)
                if not ignore_module:
                    fout.write(line)
                    if any(r.search(name) for r in ff_re):
                        if seu_reset_pin:
                            fout.write("    // tmrg seu_reset %s\n" % seu_reset_pin)
                        if seu_set_pin:
                            fout.write("    // tmrg seu_set   %s\n" % seu_set_pin)
            elif stripped.startswith(("input", "output", "endmodule")):
                if not ignore_module:
                    fout.write(line)
            elif stripped.startswith("primitive "):
                break

def generate_implementation_lib(fname_in, fname_out):
    """This function loads a post-implementation netlist and
    generates a simplified version retaining only port information
    of the top module.
    """
    module_name = os.path.splitext(os.path.basename(fname_in))[0]
    in_module = False
    in_module_header = False
    with open(fname_in) as fin, open(fname_out, "w") as fout:
        for line in fin.readlines():
            line_stripped = line.strip()
            if line_stripped.startswith("module %s" % module_name):
                in_module_header = True
                in_module = True
            if in_module_header:
                fout.write(line)
                if line_stripped.endswith(");"):
                    in_module_header = False
            if in_module and (
                line_stripped.startswith("input ")
                or line_stripped.startswith("inout ")
                or line_stripped.startswith("output ")
            ):
                fout.write(line)
            if in_module and line_stripped.startswith("endmodule"):
                fout.write(line)
                in_module = False


def simplify_lib(library, simplify_method):
    """Creates simplified library copies digestible by tmrg"""
    basename = os.path.basename(library)
    file_name, file_extension = os.path.splitext(basename)
    file_digest = hashlib.md5(library.encode()).hexdigest()[:8]
    basename_simplified = file_name + "_" + file_digest + file_extension
    lib_simplified = os.path.join("libs", basename_simplified)
    if os.path.isfile(lib_simplified):
        logging.info("Simplified version already exitsts (%s)", lib_simplified)
    else:
        logging.info("Generating simplified version (%s)", lib_simplified)
        if not os.path.exists("libs"):
            os.makedirs("libs")
        simplify_method(library, lib_simplified)
    return lib_simplified

def run_command(cmd):
    proc = None

    def handle_signal(signum, frame):
        if proc is not None:
            logging.info("Received %s, sending to tmrg." % signal.Signals(signum).name)
            proc.send_signal(signum)

    proc = subprocess.Popen(cmd, shell=True)
    backup_handler_sigterm = signal.getsignal(signal.SIGTERM)
    backup_handler_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    proc.wait()  # wait for command to complete
    signal.signal(signal.SIGTERM, backup_handler_sigterm)
    signal.signal(signal.SIGINT, backup_handler_sigint)

    return proc.returncode

def main():
    """tmrg flow implementation for bake"""
    BAKE_VERBOSITY = $BAKE_VERBOSITY
    BAKE_INCLUDE_DIRS = shlex.split("$BAKE_INCLUDE_DIRS")
    BAKE_LIB_VERILOG_FILES = shlex.split("$BAKE_LIB_VERILOG_FILES")
    BAKE_TOP = "$BAKE_TOP"
    BAKE_TMR_OUTPUT_DIR = "$BAKE_TMR_OUTPUT_DIR"
    BAKE_RUN_OPTIONS = "$BAKE_RUN_OPTIONS"
    BAKE_TMR_CELL_LIB_DIRS      = shlex.split("$BAKE_TMR_CELL_LIB_DIRS")
    BAKE_TMR_FF_CELL_PATTERNS   = shlex.split("$BAKE_TMR_FF_CELL_PATTERNS")
    BAKE_TMR_SKIP_CELL_PATTERNS = shlex.split("$BAKE_TMR_SKIP_CELL_PATTERNS")
    BAKE_TMR_SEU_RESET_PIN      = "$BAKE_TMR_SEU_RESET_PIN"
    BAKE_TMR_SEU_SET_PIN        = "$BAKE_TMR_SEU_SET_PIN"

    tmrg_options = "--include "
    tmrg_options += "--common-cells-postfix=_%s " % BAKE_TOP
    tmrg_options += BAKE_RUN_OPTIONS + " "

    for inc_dir in BAKE_INCLUDE_DIRS:
        tmrg_options += "--inc-dir " + inc_dir + " "

    for library in BAKE_LIB_VERILOG_FILES:
        simplify_method = None

        # Standard-cell libraries (configured via config.tmr.cell_lib_dirs)
        if any(library.startswith(d) for d in BAKE_TMR_CELL_LIB_DIRS):
            logging.info("Cell library detected (%s)", library)
            simplify_method = functools.partial(
                generate_cell_lib,
                ff_patterns=BAKE_TMR_FF_CELL_PATTERNS,
                skip_patterns=BAKE_TMR_SKIP_CELL_PATTERNS,
                seu_reset_pin=BAKE_TMR_SEU_RESET_PIN,
                seu_set_pin=BAKE_TMR_SEU_SET_PIN,
            )

        # Check for post-implementation netlists
        with open(library, "r") as fd:
            header = "".join([fd.readline() for _ in range(3)])
        if any(tool in header for tool in ("Yosys", "Genus", "Innovus", "Design Compiler")):
            logging.info("Post-implementation library detected (%s)", library)
            simplify_method = generate_implementation_lib

        # Perform simplification if required
        if simplify_method is not None:
            library = simplify_lib(library, simplify_method)

        if os.path.getsize(library):
            tmrg_options += "--lib=%s " % library
        else:
            logging.info("Library '%s' is empty. Not passing it to tmrg", library)

    if BAKE_VERBOSITY > 0:
        tmrg_options += "-" + "v" * BAKE_VERBOSITY + " "

    if not os.path.exists(BAKE_TMR_OUTPUT_DIR):
        os.makedirs(BAKE_TMR_OUTPUT_DIR)

    logging.info("Running tmrg")
    retval = run_command("tmrg -c config/tmrg.cnf %s" % tmrg_options)
    sys.exit(retval)


if __name__ == "__main__":
    coloredlogs.install(fmt="[tmrg ] %(levelname)s\t %(message)s")
    try:
        main()
        sys.exit(0)
    except Exception as exc:
        logging.error(str(exc))
        sys.exit(1)
