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

import fcntl
import hashlib
import json
import logging
import os
import signal
import subprocess
import glob
import random
import re
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
        'seed_opt': '-svseed %d',
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
        'seed_opt': '-svseed %d',
        'delay_opts': {'typ': '-typdelays',
                       'min': '-mindelays',
                       'max': '-maxdelays'},
        # Build once per build configuration, run each test from the build
        # (see build_once_and_run): the options of each phase.
        'build_once': {'build': '-sv -cdslib cds.lib -elaborate -l elab.log',
                       'run': '-cdslib cds.lib -l sim.log -R',
                       'library': '-xmlibdirname %s -snapshot sim'},
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
        'seed_opt': '',
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
        'seed_opt': '+verilator+seed+%d',
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
        'seed_opt': '+ntb_random_seed=%d',
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
        'seed_opt': '-sv_seed %d',
        'delay_opts': {'typ': '+typdelays',
                       'min': '+mindelays',
                       'max': '+maxdelays'}
    }
}

# Everything the simulator prints is appended here (and still shown), so the
# pass/fail criteria can be checked against it after the run.
SIM_LOG = "bake_sim.log"


def run_command(cmd, capture=True, cwd=None):
    proc = None

    def handle_signal(signum, frame):
        if proc is not None:
            logging.info("Received %s, sending to simulator." % signal.Signals(signum).name)
            proc.send_signal(signum)

    if capture:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd)
    else:
        proc = subprocess.Popen(cmd, shell=True, cwd=cwd)
    backup_handler_sigterm = signal.getsignal(signal.SIGTERM)
    backup_handler_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if capture:
        with open(SIM_LOG, "ab") as log:
            for line in proc.stdout:
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
                log.write(line)
    proc.wait()  # wait for command to complete
    signal.signal(signal.SIGTERM, backup_handler_sigterm)
    signal.signal(signal.SIGINT, backup_handler_sigint)

    return proc.returncode


# The files whose size and time a build's stamp covers: those a Verilog
# `include can reach, by extension.
HDL_EXTENSIONS = (".v", ".sv", ".vh", ".svh", ".vp", ".svp", ".inc", ".h", ".sva", ".vams")


def build_inputs_digest(build_cmd, sources, incdirs, skip_dir):
    """What a build was made from, as far as the flow can tell without the
    simulator: the command, and the size and time of the sources and of the
    HDL files under the include directories (recursively) and next to the
    sources. Equal digests let a run reuse a build without asking the
    simulator, which would wait for every simulation using the build."""
    files = {os.path.abspath(f) for f in sources}
    skip_dir = os.path.realpath(skip_dir)
    for incdir in incdirs:
        for current, subdirs, names in os.walk(incdir):
            subdirs[:] = [d for d in subdirs if not d.startswith(".") and d not in ("xcelium.d", "INCA_libs")
                          and os.path.realpath(os.path.join(current, d)) != skip_dir]
            files.update(os.path.abspath(os.path.join(current, n)) for n in names if n.endswith(HDL_EXTENSIONS))
    for directory in {os.path.dirname(os.path.abspath(f)) for f in sources}:
        if os.path.isdir(directory):
            files.update(os.path.join(directory, n) for n in os.listdir(directory) if n.endswith(HDL_EXTENSIONS))
    digest = hashlib.sha256(build_cmd.encode("utf-8"))
    for path in sorted(files):
        try:
            st = os.stat(path)
        except OSError:
            continue
        digest.update(("%s\0%d\0%d\0" % (path, st.st_mtime_ns, st.st_size)).encode("utf-8"))
    return digest.hexdigest()


def build_once_and_run(simulator, build_opts, run_opts, sources, incdirs, build_root, capture):
    """Build (compile and elaborate) into a directory shared by every test
    with the same build configuration, then simulate from it in the test's
    directory.

    The directory is named after a digest of the simulator and the build
    command, so tests differing only in what they give the simulation (the
    UVM test, the seed, runtime options) share one build, and others get
    theirs. The simulator's incremental build brings a changed build up to
    date; a stamp of the build inputs skips asking it when nothing changed,
    since it would wait for every simulation running from the build. Builds
    take turns (a lock); simulations take none: the simulator locks the
    snapshot against a rebuild while they run."""
    settings = simulator['build_once']
    executable = simulator['executable']
    build_cmd = " ".join([executable] + build_opts)
    key = hashlib.sha256(json.dumps([os.path.realpath(shutil.which(executable)), build_cmd]).encode("utf-8"))
    build_dir = os.path.join(build_root, key.hexdigest()[:16])
    os.makedirs(build_dir, exist_ok=True)
    library = settings['library'] % os.path.join(build_dir, "xcelium.d")
    stamp_path = os.path.join(build_dir, "build_stamp")

    with open(os.path.join(build_dir, "build.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        inputs = build_inputs_digest(build_cmd, sources, incdirs, build_root)
        try:
            with open(stamp_path, encoding="utf-8") as f:
                up_to_date = f.read().strip() == inputs
        except OSError:
            up_to_date = False
        if up_to_date:
            logging.info("Reusing the build in %s", build_dir)
        else:
            logging.info("Building in %s (shared by the tests with this build configuration)", build_dir)
            if os.path.exists(stamp_path):
                os.remove(stamp_path)
            with open(os.path.join(build_dir, "build_cmd"), "w", encoding="utf-8") as f:
                f.write(build_cmd + "\n")
            open(os.path.join(build_dir, "cds.lib"), "a").close()
            retval = run_command("%s %s %s" % (build_cmd, settings['build'], library), capture, cwd=build_dir)
            if retval:
                return retval
            with open(stamp_path, "w", encoding="utf-8") as f:
                f.write(inputs + "\n")

    return run_command(" ".join([executable] + run_opts + [settings['run'], library]), capture)


def check_log_criteria(pass_regex, fail_regex):
    """Return 0 when the captured simulator output meets the criteria, 2
    otherwise: no line may match fail_regex, and one must match pass_regex
    when it is set."""
    if not (pass_regex or fail_regex):
        return 0
    if not os.path.isfile(SIM_LOG):
        logging.error("Cannot check the pass/fail criteria: %s was not written.", SIM_LOG)
        return 2
    with open(SIM_LOG, encoding="utf-8", errors="replace") as log:
        lines = log.read().splitlines()
    if fail_regex:
        failing = [line for line in lines if re.search(fail_regex, line)]
        if failing:
            logging.error("Test failed: %d line(s) match vrf_fail_regex %r, first: %s",
                          len(failing), fail_regex, failing[0].strip())
            return 2
    if pass_regex and not any(re.search(pass_regex, line) for line in lines):
        logging.error("Test failed: no line matches vrf_pass_regex %r", pass_regex)
        return 2
    return 0


# A severity count of the UVM report summary. UVM prints it as "%s :%5d",
# so from 10000 up no space is left between the colon and the count.
UVM_SEVERITY_COUNT = re.compile(r"^\s*(UVM_ERROR|UVM_FATAL)\s*:\s*(\d+)\s*$")


def check_uvm_summary(log_file):
    """Return 0 when the UVM report summary in log_file counts no UVM_ERROR
    and no UVM_FATAL, 2 otherwise. A log without the summary means the test
    never got to the end, which is a failure too."""
    summary_found = False
    retval = 0
    with open(log_file, encoding="utf-8", errors="replace") as log:
        for line in log:
            if "UVM Report Summary" in line:
                summary_found = True
                continue
            match = summary_found and UVM_SEVERITY_COUNT.match(line)
            if match and int(match.group(2)):
                logging.error("Test failed because of '%s'!", line.strip())
                retval = 2
    if not summary_found:
        logging.error("Test failed: no 'UVM Report Summary' in %s — the test did not run to completion.",
                      log_file)
        retval = 2
    return retval


def main():
    # The template variables, as bake wrote them to bake_vars.json (lists
    # stay lists, so paths with spaces survive).
    with open(os.environ.get("BAKE_VARS", "bake_vars.json"), encoding="utf-8") as f:
        V = json.load(f)
    BAKE_TOP = V["BAKE_TOP"]
    BAKE_INCLUDE_DIRS = V["BAKE_INCLUDE_DIRS"]
    BAKE_DESIGN_VERILOG_FILES = V["BAKE_DESIGN_VERILOG_FILES"]
    BAKE_INTERACTIVE = str(V["BAKE_INTERACTIVE"])
    BAKE_SIM_TOP = V["BAKE_SIM_TOP"]
    BAKE_SIM_FILES = V["BAKE_SIM_FILES"]
    BAKE_LIB_VERILOG_FILES = V["BAKE_LIB_VERILOG_FILES"]
    BAKE_SIM_SIMULATOR = V["BAKE_SIM_SIMULATOR"]
    BAKE_SIM_OPTIONS = " ".join(V["BAKE_SIM_OPTIONS"])
    BAKE_RUN_OPTIONS = " ".join(V["BAKE_RUN_OPTIONS"])
    BAKE_SIM_DEFINES = V["BAKE_SIM_DEFINES"]
    BAKE_SIM_DELAY_CORNER = V["BAKE_SIM_DELAY_CORNER"]
    BAKE_SIM_SDF_FILES = V["BAKE_SIM_SDF_FILES"]
    BAKE_SIM_FRAMEWORK = V["BAKE_SIM_FRAMEWORK"]
    BAKE_SIM_FRAMEWORK_TOP = V["BAKE_SIM_FRAMEWORK_TOP"]
    BAKE_SIM_PASS_REGEX = V.get("BAKE_SIM_PASS_REGEX", "")
    BAKE_SIM_FAIL_REGEX = V.get("BAKE_SIM_FAIL_REGEX", "")
    BAKE_SIM_SEED = V.get("BAKE_SIM_SEED", "")
    BAKE_SIM_RUNTIME_OPTIONS = " ".join(V.get("BAKE_SIM_RUNTIME_OPTIONS", []))
    BAKE_SIM_BUILD_DIR = V.get("BAKE_SIM_BUILD_DIR", "")

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

    # The seed: config.vrf.seed, or a fresh random one. Always reported so
    # that a failing run can be repeated with -o vrf.seed=<n>.
    seed = int(BAKE_SIM_SEED) if str(BAKE_SIM_SEED).strip() else random.randrange(1, 2**31)
    logging.info("Simulation seed: %d", seed)
    os.environ["RANDOM_SEED"] = str(seed)          # cocotb 1.x
    os.environ["COCOTB_RANDOM_SEED"] = str(seed)   # cocotb 2.x

    if os.path.isfile(SIM_LOG):
        os.remove(SIM_LOG)

    simulator_options = [BAKE_SIM_OPTIONS]
    simulator_options.append(simulator['default_opts'])
    if simulator['seed_opt']:
        simulator_options.append(simulator['seed_opt'] % seed)
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
            # cocotb 2.x renamed TOPLEVEL and MODULE; both spellings are
            # written so either version picks up its own.
            makefile.write("TOPLEVEL = %s\n" % BAKE_SIM_TOP)
            makefile.write("COCOTB_TOPLEVEL = %s\n" % BAKE_SIM_TOP)
            makefile.write("MODULE = %s\n" % BAKE_SIM_FRAMEWORK_TOP)
            makefile.write("COCOTB_TEST_MODULES = %s\n" % BAKE_SIM_FRAMEWORK_TOP)
            makefile.write("RANDOM_SEED = %d\n" % seed)
            makefile.write("COCOTB_RANDOM_SEED = %d\n" % seed)
            makefile.write("COMPILE_ARGS = %s\n" % " ".join(simulator_options))
            makefile.write("PLUSARGS = %s\n" % BAKE_SIM_RUNTIME_OPTIONS)
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
        retval = run_command("make", capture=not gui)
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
    else:
        uvm = BAKE_SIM_FRAMEWORK == "uvm"
        sources = BAKE_DESIGN_VERILOG_FILES + vrf_netlist_files
        framework_build = [simulator['uvm_opts']] if uvm else []
        framework_run = [simulator['uvm_testname'] % BAKE_SIM_FRAMEWORK_TOP] if uvm else []
        sdf = BAKE_SIM_SDF_FILES or any(f.endswith(".sdf") for f in BAKE_SIM_FILES)
        # An interactive run builds in the test's directory too: the GUI's
        # "Reinvoke" reruns its command, which then rebuilds what changed,
        # where a run from the shared build (-R) would only reload it.
        if simulator.get('build_once') and BAKE_SIM_BUILD_DIR and not sdf and not gui:
            build_opts = [BAKE_SIM_OPTIONS, simulator['def_timescale'], BAKE_RUN_OPTIONS,
                          simulator['delay_opts'][BAKE_SIM_DELAY_CORNER]]
            build_opts += [simulator["incdir"] + incdir for incdir in BAKE_INCLUDE_DIRS]
            build_opts += [simulator["define"] + define for define in BAKE_SIM_DEFINES]
            build_opts += [simulator["libfile"] + libfile for libfile in BAKE_LIB_VERILOG_FILES]
            build_opts += sources + framework_build
            run_opts = [BAKE_SIM_OPTIONS, BAKE_RUN_OPTIONS]
            run_opts += [simulator['seed_opt'] % seed] if simulator['seed_opt'] else []
            run_opts += [BAKE_SIM_RUNTIME_OPTIONS] + framework_run
            retval = build_once_and_run(simulator, build_opts, run_opts, sources + BAKE_LIB_VERILOG_FILES,
                                        BAKE_INCLUDE_DIRS, BAKE_SIM_BUILD_DIR, capture=True)
        else:
            if simulator.get('build_once') and sdf:
                logging.info("SDF back-annotation: building in the test's directory, not shared with other tests.")
            elif simulator.get('build_once') and gui:
                logging.info("Interactive run: building in the test's directory, so that the GUI's "
                             "Reinvoke picks up source changes.")
            simulator_options.extend(sources)
            simulator_options.extend(framework_build + framework_run)
            if BAKE_SIM_SIMULATOR != "icarus":
                simulator_options.append(BAKE_SIM_RUNTIME_OPTIONS)
            cmd = simulator['executable'] + " " + (" ".join(simulator_options))
            retval = run_command(cmd, capture=not gui)
            if BAKE_SIM_SIMULATOR == "icarus" and retval == 0:
                retval = run_command("./a.out " + BAKE_SIM_RUNTIME_OPTIONS, capture=not gui)
        if uvm and not retval:
            if not os.path.isfile("sim.log"):
                logging.error("Test failed as the output log file (sim.log) does not exist!")
                retval = 1
            else:
                retval = check_uvm_summary("sim.log")

    if retval == 0:
        retval = check_log_criteria(BAKE_SIM_PASS_REGEX, BAKE_SIM_FAIL_REGEX)

    if gui and BAKE_SIM_SIMULATOR == "icarus" and retval == 0:
        vcd_files = list(glob.glob("**.vcd"))
        if vcd_files:
            run_command("gtkwave %s" % vcd_files[0], capture=False)

    if gui and BAKE_SIM_SIMULATOR == "vcs" and retval == 0:
        run_command("./simv* -gui=sx", capture=False)

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
