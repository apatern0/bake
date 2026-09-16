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

"""Verification run script template"""

import logging
import os
import shlex
import signal
import subprocess
import glob
import sys
import shutil
import xml.etree.ElementTree as ET

def cadence_pre_run_function():
    # create an empty cds.lib file
    with open("cds.lib", "a") as _:
        pass

SIMULATOR_OPTIONS = {
    'ius': {
        'executable': 'irun',
        'default_opts': '-sv -cdslib cds.lib -l sim.log',
        'def_timescale': '-timescale 1ps/1ps',
        'incdir': '-incdir ',
        'libfile': '-v ',
        'define': '-define ',
        'gui': '-gui -access +rwc',
        'nogui': '',
        'pre_run_function': cadence_pre_run_function,
        'cap_frameworks': ['', 'uvm', 'cocotb'],
        'uvm_opts': '-uvm',
        'uvm_testname': '+UVM_TESTNAME=%s',
        'delay_opts': {'typ': '-typdelays',
                       'min': '-mindelays',
                       'max': '-maxdelays'}
    },
    'xcelium': {
        'executable': 'xrun',
        'default_opts': '-sv -cdslib cds.lib -l sim.log',
        'def_timescale': '-timescale 1ps/1ps',
        'incdir': '-incdir ',
        'libfile': '-v ',
        'define': '-define ',
        'gui': '-gui -access +rwc',
        'nogui': '',
        'pre_run_function': cadence_pre_run_function,
        'cap_frameworks': ['', 'uvm', 'cocotb'],
        'uvm_opts': '-uvm',
        'uvm_testname': '+UVM_TESTNAME=%s',
        'delay_opts': {'typ': '-typdelays',
                       'min': '-mindelays',
                       'max': '-maxdelays'}
    },
    'icarus': {
        'executable': 'iverilog',
        'default_opts': '',
        'def_timescale': '',
        'incdir': '-I',
        'libfile': '',
        'define': '-D',
        'gui': '-D VCD',
        'nogui': '',
        'pre_run_function': None,
        'cap_frameworks': ['', 'cocotb'],
        'uvm_opts': '',
        'uvm_testname': '',
        'delay_opts': {'typ': '-T typ',
                       'min': '-T min',
                       'max': '-T max'}
    },
    'verilator': {
        'executable': 'verilator',
        'default_opts': '',
        'def_timescale': '',
        'incdir': '-I',
        'libfile': '',
        'define': '-D',
        'gui': '',
        'nogui': '',
        'pre_run_function': None,
        'cap_frameworks': ['cocotb'],
        'uvm_opts': '',
        'uvm_testname': '',
        'delay_opts': {'typ': '',
                       'min': '',
                       'max': ''}
    },
    'vcs': {
        'executable': 'vcs',
        'default_opts': '-sverilog -full64 -l sim.log',
        'def_timescale': '-timescale=1ps/1ps',
        'incdir': '+incdir+',
        'libfile': '-v ',
        'define': '+define+',
        'gui': '-kdb -debug_access+all',
        'nogui': '-R',
        'pre_run_function': None,
        'cap_frameworks': ['', 'uvm', 'cocotb'],
        'uvm_opts': '-ntb_opts uvm',
        'uvm_testname': '+UVM_TESTNAME=%s',
        'delay_opts': {'typ': '+typdelays',
                       'min': '+mindelays',
                       'max': '+maxdelays'}
    },
    'questa': {
        'executable': 'qverilog',
        'default_opts': '-sv -64 -l sim.log',
        'def_timescale': '-timescale=1ps/1ps',
        'incdir': '+incdir+',
        'libfile': '-v ',
        'define': '+define+',
        'gui': '-gui',
        'nogui': '',
        'pre_run_function': None,
        'cap_frameworks': ['', 'uvm', 'cocotb'],
        'uvm_opts': '',
        'uvm_testname': '-R +UVM_TESTNAME=%s -',
        'delay_opts': {'typ': '+typdelays',
                       'min': '+mindelays',
                       'max': '+maxdelays'}
    }
}

def run_command(cmd):
    proc = None

    def handle_signal(signum, frame):
        if proc is not None:
            logging.info("Received %s, sending to simulator." % signal.Signals(signum).name)
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
    # All values below are replaced by bake during template evaluation
    BAKE_TOP = "$BAKE_TOP"
    BAKE_INCLUDE_DIRS = shlex.split("$BAKE_INCLUDE_DIRS")
    BAKE_DESIGN_VERILOG_FILES = shlex.split("$BAKE_DESIGN_VERILOG_FILES")
    BAKE_INTERACTIVE = "$BAKE_INTERACTIVE"
    BAKE_SIM_TOP = "$BAKE_SIM_TOP"
    BAKE_SIM_FILES = shlex.split("$BAKE_SIM_FILES")
    BAKE_LIB_VERILOG_FILES = shlex.split("$BAKE_LIB_VERILOG_FILES")
    BAKE_SIM_SIMULATOR = "$BAKE_SIM_SIMULATOR"
    BAKE_SIM_OPTIONS = "$BAKE_SIM_OPTIONS"
    BAKE_RUN_OPTIONS = "$BAKE_RUN_OPTIONS"
    BAKE_SIM_DEFINES = "$BAKE_SIM_DEFINES".split()
    BAKE_SIM_DELAY_CORNER = "$BAKE_SIM_DELAY_CORNER"
    BAKE_SIM_SDF_FILES = shlex.split("$BAKE_SIM_SDF_FILES")
    BAKE_SIM_FRAMEWORK = "$BAKE_SIM_FRAMEWORK"
    BAKE_SIM_FRAMEWORK_TOP = "$BAKE_SIM_FRAMEWORK_TOP"

    # basic data validation
    if not BAKE_DESIGN_VERILOG_FILES:
        raise ValueError("BAKE_DESIGN_VERILOG_FILES is empty")

    if not BAKE_SIM_FILES:
        raise ValueError("BAKE_SIM_FILES is empty")

    if BAKE_INTERACTIVE not in ("0", "1"):
        raise ValueError("Unsupported GUI option (BAKE_INTERACTIVE=%s)" % BAKE_INTERACTIVE)
    gui = int(BAKE_INTERACTIVE)

    if BAKE_SIM_SIMULATOR not in SIMULATOR_OPTIONS:
        raise ValueError("Unsupported simulator (BAKE_SIM_SIMULATOR=%s)" % BAKE_SIM_SIMULATOR)
    simulator = SIMULATOR_OPTIONS[BAKE_SIM_SIMULATOR]

    if BAKE_SIM_DELAY_CORNER not in simulator['delay_opts']:
        raise ValueError("Unsupported delay corner '%s' for simulator '%s' (config.vrf.delays); choose one of: %s"
                         % (BAKE_SIM_DELAY_CORNER, BAKE_SIM_SIMULATOR, ", ".join(simulator['delay_opts'])))

    if BAKE_SIM_FRAMEWORK not in ("", "cocotb", "uvm"):
        if BAKE_SIM_FRAMEWORK == "":
            BAKE_SIM_FRAMEWORK = "no verification framework"
        raise ValueError("Unsupported simulation framework (BAKE_SIM_FRAMEWORK=%s)" % BAKE_SIM_FRAMEWORK)

    if BAKE_SIM_FRAMEWORK in ("cocotb", "uvm") and not BAKE_SIM_FRAMEWORK_TOP:
        raise ValueError("BAKE_SIM_FRAMEWORK_TOP must be specified when using '%s' framework." % BAKE_SIM_FRAMEWORK)

    if BAKE_SIM_FRAMEWORK == "cocotb" and not BAKE_SIM_TOP:
        raise ValueError("BAKE_SIM_TOP must not be empty for cocotb tests.")

    if BAKE_SIM_FRAMEWORK not in simulator['cap_frameworks']:
        if BAKE_SIM_FRAMEWORK == "":
            BAKE_SIM_FRAMEWORK = "no verification framework"
        raise ValueError("Simulator '%s' does not support requested verification framework ('%s')." % (BAKE_SIM_SIMULATOR, BAKE_SIM_FRAMEWORK))

    executable = simulator['executable']
    if shutil.which(executable) is None:
        info = "\nDetected on the system:\n"
        for sim in SIMULATOR_OPTIONS:
            info += "  %s : %s\n" % (sim, shutil.which(SIMULATOR_OPTIONS[sim]["executable"]))
        raise ValueError("Executable for '%s' simulator (cmd: '%s') not found." % (BAKE_SIM_SIMULATOR, executable) + info)

    simulator_options = [BAKE_SIM_OPTIONS]
    simulator_options.append(simulator['default_opts'])
    if BAKE_SIM_FRAMEWORK != "cocotb":
        simulator_options.append(simulator['def_timescale'])

    simulator_options.append(BAKE_RUN_OPTIONS)
    simulator_options.append(simulator['delay_opts'][BAKE_SIM_DELAY_CORNER])
    simulator_options.extend([simulator["incdir"] + incdir for incdir in BAKE_INCLUDE_DIRS])
    simulator_options.extend([simulator["define"] + define for define in BAKE_SIM_DEFINES])
    simulator_options.extend([simulator["libfile"] + libfile for libfile in BAKE_LIB_VERILOG_FILES])

    if simulator['pre_run_function'] is not None:
        simulator['pre_run_function']()

    if gui:
        simulator_options.append(simulator["gui"])
    else:
        simulator_options.append(simulator["nogui"])

    def link_sdf(sdf_file):
        # SDF files are linked into the run directory under their own name so
        # that $$sdf_annotate calls in the testbench find them.
        target_name = os.path.basename(sdf_file)
        if os.path.lexists(target_name):
            os.unlink(target_name)
        os.symlink(sdf_file, target_name)

    for sdf_file in BAKE_SIM_SDF_FILES:
        link_sdf(sdf_file)
    if BAKE_SIM_SDF_FILES and BAKE_SIM_SIMULATOR == "icarus":
        # Icarus drops specify blocks (and with them $$sdf_annotate) unless asked.
        simulator_options.append("-gspecify")

    vrf_py_dirs = []
    vrf_netlist_files = []
    for vrf_file in BAKE_SIM_FILES:
        _, ext = os.path.splitext(vrf_file)
        if ext == ".sdf":
            link_sdf(vrf_file)
        elif ext == ".py":
            vrf_py_dirs.append(os.path.dirname(vrf_file))
        else:
            if vrf_file not in BAKE_DESIGN_VERILOG_FILES:
                vrf_netlist_files.append(vrf_file)

    retval = 0
    if BAKE_SIM_FRAMEWORK == "cocotb":
        with open("Makefile", "w") as makefile:
            makefile.write("# Auto generated Makefile.\n")
            makefile.write("# Do not edit it by hand.\n\n")
            makefile.write("PYTHONPATH:=$$(PYTHONPATH):%s\n" % ":".join(vrf_py_dirs))
            makefile.write("TOPLEVEL_LANG = verilog\n")
            makefile.write("SIM = %s\n" % BAKE_SIM_SIMULATOR)
            makefile.write("TOPLEVEL = %s\n" % BAKE_SIM_TOP)
            makefile.write("MODULE = %s\n" % BAKE_SIM_FRAMEWORK_TOP)
            makefile.write("COMPILE_ARGS = %s\n" % " ".join(simulator_options))
            makefile.write("RTL_SOURCES = %s\n" % " ".join(BAKE_DESIGN_VERILOG_FILES))
            makefile.write("RTL_INCLUDE_DIRS = %s\n" % " ".join(BAKE_INCLUDE_DIRS))
            makefile.write("VRF_SOURCES = %s\n" % " ".join(vrf_netlist_files))
            makefile.write("VERILOG_SOURCES = $$(RTL_SOURCES) $$(VRF_SOURCES)\n")
            makefile.write("COCOTB_HDL_TIMEUNIT = 1ns\n")
            makefile.write("COCOTB_HDL_TIMEPRECISION = 1fs\n")
            makefile.write("export RTL_SOURCES\n")
            makefile.write("export RTL_INCLUDE_DIRS\n")
            makefile.write("export PYTHONPATH\n")
            for define in BAKE_SIM_DEFINES:
                makefile.write("export %s\n" % define)
            makefile.write("include $$(shell cocotb-config --makefiles)/Makefile.sim\n")
        if os.path.isfile("results.xml"):
            os.remove("results.xml")
        logging.info(f"Running generated Makefile in {os.getcwd()}")
        retval = run_command("make")
        if os.path.isfile("results.xml"):
            results = ET.parse('results.xml')
            for testcase in results.getroot().iter('testcase'):
                for tag in testcase:
                    if tag.tag.lower()=='failure':
                        logging.error("Test '%s' failed!", testcase.attrib['classname'])
                        retval = 2
        else:
            logging.error("File `results.xml` does not exist.")
            retval = 1
    elif BAKE_SIM_FRAMEWORK == "uvm":
        simulator_options.extend(BAKE_DESIGN_VERILOG_FILES)
        simulator_options.extend(vrf_netlist_files)
        simulator_options.append(simulator['uvm_opts'])
        simulator_options.append(simulator['uvm_testname'] % BAKE_SIM_FRAMEWORK_TOP)
        cmd = simulator['executable'] + " " + (" ".join(simulator_options))
        retval = run_command(cmd)
        if not retval:
            if not os.path.isfile("sim.log"):
                logging.error("Test failed as the output log file (sim.log) does not exist!")
                retval = 1
            else:
                ERROR_LEVELS = ('UVM_FATAL : ',
                                'UVM_ERROR : ')
                with open("sim.log") as file:
                    for line in file.readlines():
                        if any(error_level in line for error_level in ERROR_LEVELS):
                            messages = int(line.split(":")[1])
                            if messages:
                                retval = 2
                                logging.error("Test failed because of '%s'!", line.strip())
    else:
        simulator_options.extend(BAKE_DESIGN_VERILOG_FILES)
        simulator_options.extend(vrf_netlist_files)
        cmd = simulator['executable'] + " " + (" ".join(simulator_options))
        retval = run_command(cmd)
        if BAKE_SIM_SIMULATOR == "icarus" and retval == 0:
            retval = run_command("./a.out")

    if gui and BAKE_SIM_SIMULATOR == "icarus" and retval == 0:
        vcd_files = list(glob.glob("**.vcd"))
        if vcd_files:
            run_command("gtkwave %s" % vcd_files[0])

    if gui and BAKE_SIM_SIMULATOR == "vcs" and retval == 0:
        run_command("./simv* -gui=sx")

    sys.exit(retval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='[runsim] %(levelname)s\t %(message)s')
    try:
        main()
        sys.exit(0)
    except Exception as e:
        for line in str(e).split("\n"):
            logging.error(line)
        sys.exit(1)
