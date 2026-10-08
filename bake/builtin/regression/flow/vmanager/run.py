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

"""Runs a regression as a Cadence vManager session.

Writes the session file, <regression>.vsif (a group per block, a vManager
test per test of the regression), and runs.json, the regression's runs, one
of which bake_run.py starts in each vManager run. Then launches the
session on the server (flow option `server`, host:port), waits for it, and
exports its runs to report/runs.csv and report/runs.html. The exit code is
nonzero when a run did not pass.

vManager has no local mode (since 23.09): a server is needed. The runs
inherit this environment, so the simulators found here are the ones they
use.
"""

import csv
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


def ident(name):
    """`name` as a vManager session, group or test name."""
    return re.sub(r"\W", "_", name)


def test_lines(name, taken, script, attributes):
    """A vManager test of a group whose test names are `taken`: a test listed
    twice (by two included regressions, say) is two tests."""
    unique, k = name, 1
    while unique in taken:
        k += 1
        unique = f"{name}_{k}"
    taken.add(unique)
    return (["", f"    test {unique} {{", f"        run_script: \"{script}\";"]
            + [f"        {attribute};" for attribute in attributes] + ["    };"])


def vsif(V, runs_file, top_dir):
    """The session file: the random runs of a test as one vManager test of
    `count` runs (they all start the same command), each given seed as a
    test of its own."""
    here = Path.cwd()
    lines = [f"session {ident(V['BAKE_BLOCK'])} {{",
             f"    top_dir: {top_dir};",
             f"    drm: {V['BAKE_FLOW_OPT_DRM']};"]
    if int(V["BAKE_FLOW_OPT_MAX_RUNS_IN_PARALLEL"]):
        lines.append(f"    max_runs_in_parallel: {int(V['BAKE_FLOW_OPT_MAX_RUNS_IN_PARALLEL'])};")
    lines.append("};")

    filters = [str(here / "bake.flt")] + [str(f) for f in V["BAKE_FLOW_OPT_SCAN_FILTERS"]]
    groups = {}
    for index, run in enumerate(V["BAKE_REGRESSION_RUNS"]):
        groups.setdefault(run["block"], []).append((index, run))
    for block, runs in groups.items():
        lines += ["", f"group {ident(block)} {{",
                  f"    scan_script: \"vm_scan.pl shell.flt {' '.join(filters)}\";",
                  "    sv_seed: random;"]
        if int(V["BAKE_FLOW_OPT_TIMEOUT"]):
            lines.append(f"    timeout: {int(V['BAKE_FLOW_OPT_TIMEOUT'])};")
        counts = {}   # random runs: [the first run of their command, how many]
        for index, run in runs:
            if run["seed"] is None:
                counts.setdefault(tuple(run["command"]), [index, 0])[1] += 1
        taken = set()
        for index, run in runs:
            script = shlex.join([sys.executable, str(here / "bake_run.py"), str(runs_file), str(index)])
            if run["seed"] is not None:
                lines += test_lines(f"{ident(run['test'])}_seed{run['seed']}", taken, script,
                                    [f"sv_seed: {run['seed']}", "count: 1"])
            elif counts[tuple(run["command"])][0] == index:
                lines += test_lines(ident(run["test"]), taken, script,
                                    [f"count: {counts[tuple(run['command'])][1]}"])
        lines.append("};")
    return "\n".join(lines) + "\n"


def xcelium_filters():
    """Xcelium registers its own scan filters (cdns_sim.flt, ...) with every
    run it simulates, and vManager looks for them on VMANAGER_PATH: their
    directory in the Xcelium installation on PATH, if there is one."""
    if not (shutil.which("cds_root") and shutil.which("xrun")):
        return None
    root = subprocess.run(["cds_root", "xrun"], capture_output=True, text=True, check=False).stdout.strip()
    filters = Path(root) / "tools.lnx86" / "bin"
    return filters if (filters / "cdns_sim.flt").is_file() else None


def summary(runs_csv):
    """Log the runs per test and status; True when every run passed."""
    with open(runs_csv, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    counts = {}
    for row in rows:
        key = (row.get("Name", ""), row.get("Status", ""))
        counts[key] = counts.get(key, 0) + 1
    for (name, status), n in sorted(counts.items()):
        logging.info("%5d  %-8s %s", n, status, name)
    failed = sum(1 for row in rows if row.get("Status") != "passed")
    logging.info("%d runs, %d passed, %d not", len(rows), len(rows) - failed, failed)
    return bool(rows) and not failed


def main():
    with open(os.environ.get("BAKE_VARS", "bake_vars.json"), encoding="utf-8") as f:
        V = json.load(f)
    server = V["BAKE_FLOW_OPT_SERVER"]
    if not server:
        logging.error("No vManager server: set config.regression.flow_options[\"server\"] = \"<host>:<port>\".")
        sys.exit(2)
    if not shutil.which("vmanager"):
        logging.error("vmanager is not on PATH.")
        sys.exit(2)

    here = Path.cwd()
    runs_file = here / "runs.json"
    runs_file.write_text(json.dumps(V["BAKE_REGRESSION_RUNS"], indent=2) + "\n", encoding="utf-8")
    top_dir = Path(V["BAKE_FLOW_OPT_TOP_DIR"] or here / "sessions").absolute()
    top_dir.mkdir(parents=True, exist_ok=True)
    session_file = here / f"{V['BAKE_BLOCK']}.vsif"
    session_file.write_text(vsif(V, runs_file, top_dir), encoding="utf-8")

    report = here / "report"
    if report.is_dir():
        shutil.rmtree(report)
    report.mkdir()
    runs_csv = report / "runs.csv"

    env = dict(os.environ)
    filters = xcelium_filters()
    if filters:
        env["VMANAGER_PATH"] = os.pathsep.join(p for p in (str(filters), env.get("VMANAGER_PATH")) if p)

    logging.info("Launching %s on the vManager server %s", session_file.name, server)
    tcl = (f"launch -wait -load {{{session_file}}}; "
           f"csv_export -runs -out {{{runs_csv}}} -overwrite; "
           f"report_runs -errors -out {{{report / 'runs.html'}}} -overwrite")
    # vmanager's exit code does not tell a failed launch: the exported runs do
    subprocess.run(["vmanager", "-server", server, "-nocopyright", "-execcmd", tcl], env=env, check=False)

    if not runs_csv.is_file():
        logging.error("The session did not run: vmanager exported no runs (%s).", runs_csv)
        sys.exit(2)
    passed = summary(runs_csv)
    logging.info("Runs: %s; sessions in %s", runs_csv, top_dir)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[regression] %(levelname)s\t %(message)s")
    main()
