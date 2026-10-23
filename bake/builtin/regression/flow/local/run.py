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

Every run starts its command in a directory of its own,
runs/<block>/<test>/<n>/, which is the test's work directory, with the run's
output in run.log. `jobs` runs execute at a time (flow option; 0: one per
CPU), each for at most `timeout` seconds (0: no limit). The results go to
results.csv, one row per run; the exit code is nonzero when a run did not
pass.

An interrupt (SIGINT, SIGTERM, SIGHUP; bake passes its own on to every
process of the step, the runs' included) stops the regression: no further run
starts, and those running stop with it.
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
import signal
import subprocess
import sys
import threading
import time

SEED = re.compile(r"Simulation seed: (\d+)")
GRACE_SECONDS = 30   # after a timeout, for the run to stop its simulation

stopping = threading.Event()    # set once the regression is interrupted
start_lock = threading.Lock()   # a run starts, or stopping is set, not both


def start(run):
    """Start one bake invocation, in a directory of its own; None once the
    regression is stopping."""
    with start_lock:
        if stopping.is_set():
            return None
        run["dir"].mkdir(parents=True)
        with open(run["dir"] / "run.log", "w", encoding="utf-8") as log:
            log.write(shlex.join(run["command"]) + "\n\n")
            log.flush()
            return subprocess.Popen(run["command"], cwd=run["dir"], stdout=log, stderr=subprocess.STDOUT)


def execute(run, timeout):
    """Run one bake invocation; the result is the run with its status,
    duration and seed (the one bake drew, for a random one)."""
    begin = time.monotonic()
    proc = start(run)
    if proc is None:
        return not_run(run)
    with proc:
        try:
            status = "passed" if proc.wait(timeout=timeout) == 0 else "failed"
        except subprocess.TimeoutExpired:
            # bake passes the first termination on to its flow, and kills
            # the flow's processes at the second
            proc.terminate()
            try:
                proc.wait(timeout=GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    proc.kill()
            status = "timeout"
    if status == "failed" and stopping.is_set():
        status = "stopped"
    seed = run["seed"]
    if seed is None:
        found = SEED.search((run["dir"] / "run.log").read_text(encoding="utf-8", errors="replace"))
        seed = int(found.group(1)) if found else None
    return {**run, "status": status, "seconds": time.monotonic() - begin, "seed": seed,
            "drawn": run["seed"] is None}


def not_run(run):
    return {**run, "status": "not run", "seconds": 0.0, "seed": run["seed"], "drawn": False}


def interrupted(_signum, _frame):
    raise KeyboardInterrupt


def describe(run):
    seed = "random seed" if run["seed"] is None else f"seed {run['seed']}"
    return f"{run['block']} {run['test']} #{run['run']}, {seed}"


def main():
    with open(os.environ.get("BAKE_VARS", "bake_vars.json"), encoding="utf-8") as f:
        V = json.load(f)
    jobs = int(V["BAKE_FLOW_OPT_JOBS"]) or os.cpu_count() or 1
    timeout = float(V["BAKE_FLOW_OPT_TIMEOUT"]) or None

    if os.path.isdir("runs"):
        shutil.rmtree("runs")
    runs = [{**run, "order": order, "dir": (Path("runs") / run["name"]).absolute()}
            for order, run in enumerate(V["BAKE_REGRESSION_RUNS"])]
    logging.info("Regression %s: %d runs, %d at a time", V["BAKE_BLOCK"], len(runs), min(jobs, len(runs)))

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    results = []

    def report(result):
        results.append(result)
        if result["status"] != "not run":
            logging.info("[%d/%d] %-7s %s (%.0f s)", len(results), len(runs), result["status"],
                         describe(result), result["seconds"])

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=jobs)
    futures = {pool.submit(execute, run, timeout): run for run in runs}
    try:
        for future in concurrent.futures.as_completed(futures):
            report(future.result())
    except KeyboardInterrupt:
        with start_lock:
            stopping.set()
        pool.shutdown(wait=False, cancel_futures=True)
        logging.warning("Regression %s interrupted: no further run starts; waiting for the running ones.",
                        V["BAKE_BLOCK"])
        reported = {r["order"] for r in results}
        for future, run in futures.items():
            if run["order"] not in reported:
                report(not_run(run) if future.cancelled() else future.result())
    pool.shutdown()

    results.sort(key=lambda r: r["order"])
    with open("results.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["block", "test", "run", "seed", "status", "seconds", "dir"])
        for r in results:
            writer.writerow([r["block"], r["test"], r["run"], "" if r["seed"] is None else r["seed"],
                             r["status"], f"{r['seconds']:.1f}", r["dir"]])

    failed = [r for r in results if r["status"] != "passed"]
    logging.info("Regression %s: %d runs, %d passed, %d not (results.csv)",
                 V["BAKE_BLOCK"], len(results), len(results) - len(failed), len(failed))
    if stopping.is_set():
        sys.exit(1)
    for r in failed:
        logging.error("%s %s: %s", r["status"], describe(r), r["dir"] / "run.log")
        if r["seed"] is not None:
            # the run's options have its seed, unless bake drew one
            repeat = ["bake", r["block"], r["recipe"], "-t", r["test"]]
            for option in r["options"] + ([f"vrf.seed={r['seed']}"] if r["drawn"] else []):
                repeat += ["-o", option]
            logging.error("   repeat: %s", shlex.join(repeat))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[regression] %(levelname)s\t %(message)s")
    main()
