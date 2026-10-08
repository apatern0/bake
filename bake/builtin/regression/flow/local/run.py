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

"""Runs a regression on this machine.

Every run is the bake invocation of its test with its seed, in a directory of
its own, runs/<block>/<test>/<n>/: the test's work directory (vrf.run_dir),
with the run's output in run.log. `jobs` runs execute at a time (flow option;
0: one per CPU), each for at most `timeout` seconds (0: no limit). The
results go to results.csv, one row per run; the exit code is nonzero when a
run did not pass.
"""

import concurrent.futures
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
import time

SEED = re.compile(r"Simulation seed: (\d+)")
GRACE_SECONDS = 30   # after a timeout, for the run to stop its simulation


def runs_of(V):
    """One entry per run, numbered from 1 within its test."""
    runs = []
    for entry in V["BAKE_REGRESSION_RUNS"]:
        for n, seed in enumerate(entry["seeds"], start=1):
            run_dir = Path("runs") / entry["block"] / entry["test"] / str(n)
            runs.append({**entry, "order": len(runs), "n": n, "seed": seed, "dir": run_dir.absolute()})
    return runs


def command(run):
    """The run's seed, then the regression's and the command line's options,
    which may override it, then its directory."""
    options = ([f"vrf.seed={run['seed']}"] if run["seed"] is not None else []) + run["options"]
    options.append(f"vrf.run_dir={run['dir']}")
    cmd = list(run["command"])
    for option in options:
        cmd += ["-o", option]
    return cmd


def execute(run, timeout):
    """Run one bake invocation; the result is the run with its status,
    duration and seed (the one bake drew, for a random one)."""
    run["dir"].mkdir(parents=True)
    log_path = run["dir"] / "run.log"
    cmd = command(run)
    start = time.monotonic()
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(shlex.join(cmd) + "\n\n")
        log.flush()
        # In this process group, so that an interrupt of the regression
        # reaches every run; bake passes a termination on to its flow.
        with subprocess.Popen(cmd, cwd=run["dir"], stdout=log, stderr=subprocess.STDOUT) as proc:
            try:
                status = "passed" if proc.wait(timeout=timeout) == 0 else "failed"
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    proc.kill()
                status = "timeout"
    seed = run["seed"]
    if seed is None:
        found = SEED.search(log_path.read_text(encoding="utf-8", errors="replace"))
        seed = int(found.group(1)) if found else None
    return {**run, "status": status, "seconds": time.monotonic() - start, "seed": seed}


def describe(run):
    seed = "random seed" if run["seed"] is None else f"seed {run['seed']}"
    return f"{run['block']} {run['test']} #{run['n']}, {seed}"


def main():
    with open(os.environ.get("BAKE_VARS", "bake_vars.json"), encoding="utf-8") as f:
        V = json.load(f)
    jobs = int(V["BAKE_FLOW_OPT_JOBS"]) or os.cpu_count() or 1
    timeout = float(V["BAKE_FLOW_OPT_TIMEOUT"]) or None

    if os.path.isdir("runs"):
        shutil.rmtree("runs")
    runs = runs_of(V)
    logging.info("Regression %s: %d runs, %d at a time", V["BAKE_BLOCK"], len(runs), min(jobs, len(runs)))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(execute, run, timeout) for run in runs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            logging.info("[%d/%d] %-7s %s (%.0f s)", len(results), len(runs), result["status"],
                         describe(result), result["seconds"])

    results.sort(key=lambda r: r["order"])
    with open("results.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["block", "test", "run", "seed", "status", "seconds", "dir"])
        for r in results:
            writer.writerow([r["block"], r["test"], r["n"], "" if r["seed"] is None else r["seed"],
                             r["status"], f"{r['seconds']:.1f}", r["dir"]])

    failed = [r for r in results if r["status"] != "passed"]
    logging.info("Regression %s: %d runs, %d passed, %d not (results.csv)",
                 V["BAKE_BLOCK"], len(results), len(results) - len(failed), len(failed))
    for r in failed:
        logging.error("%s %s: %s", r["status"], describe(r), r["dir"] / "run.log")
        if r["seed"] is not None:
            repeat = ["bake", r["block"], r["recipe"], "-t", r["test"]]
            for option in r["options"] + [f"vrf.seed={r['seed']}"]:
                repeat += ["-o", option]
            logging.error("   repeat: %s", shlex.join(repeat))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[regression] %(levelname)s\t %(message)s")
    main()
