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

"""Runs a sweep on this machine and reports it.

Every variant starts its command in a directory of its own, runs/<variant>/,
which is the output directory of its run, with the run's output in run.log.
The directories are kept between runs of the sweep, so a variant whose
inputs did not change is up to date and does not run again. `jobs` variants
execute at a time (flow option; 0: all of them), each for at most `timeout`
seconds (0: no limit).

report.md compares the variants, from the summary.json the flow of each run
writes in its work directory (runs/<variant>/<block>/<recipe>/); it is
rewritten whenever a variant finishes, so it also says how far the sweep
is. results.csv has one row per variant. sweep.pid holds the process to
stop the sweep with (SIGTERM or SIGINT stops every run). The exit code is
nonzero when a variant did not pass. A variant whose flow finished without
every output its step expects (a run stopped before the end of its flow on
purpose) is "partial": reported, but not a failure of the sweep.
"""

import concurrent.futures
import csv
import datetime
import json
import logging
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading
import time

GRACE_SECONDS = 30   # after a timeout or a stop, for a run to stop its flow
# What bake logs when the flow finished but the step lacks outputs it
# expects: a run stopped before the end of its flow on purpose, say.
MISSING_OUTPUTS = "did not produce all required files"

_lock = threading.Lock()
_procs: dict = {}    # running variant -> Popen
_stopping = threading.Event()


def summary_path(run):
    """Where the run's flow wrote summary.json: its work directory,
    <block>/<recipe>/, or the test's directory below it for a vrf recipe."""
    work = run["dir"] / run["block"] / run["recipe"]
    if (work / "summary.json").is_file():
        return work / "summary.json"
    found = sorted(work.glob("*/summary.json")) if work.is_dir() else []
    return found[0] if found else None


def summary_of(run):
    """The run's summary.json, or None when its flow wrote none (yet)."""
    path = summary_path(run)
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, ValueError):
        return None
    return summary if isinstance(summary, dict) else None


def execute(run, timeout, started_hook):
    """Run one variant; the result is its status and duration.
    started_hook() runs once the variant is running."""
    if _stopping.is_set():
        return {"status": "stopped", "seconds": 0.0}
    run["dir"].mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    with open(run["dir"] / "run.log", "w", encoding="utf-8") as log:
        log.write(shlex.join(run["command"]) + "\n\n")
        log.flush()
        with subprocess.Popen(run["command"], cwd=run["dir"], stdout=log, stderr=subprocess.STDOUT) as proc:
            with _lock:
                _procs[run["name"]] = proc
            run["status"] = "running"
            started_hook()
            try:
                code = proc.wait(timeout=timeout)
                status = "stopped" if _stopping.is_set() else ("passed" if code == 0 else "failed")
                if status == "failed" and MISSING_OUTPUTS in (run["dir"] / "run.log").read_text(
                        encoding="utf-8", errors="replace"):
                    status = "partial"
            except subprocess.TimeoutExpired:
                stop(proc)
                status = "timeout"
            with _lock:
                _procs.pop(run["name"], None)
    return {"status": status, "seconds": time.monotonic() - start}


def stop(proc):
    """Terminate a run, giving bake time to stop its flow."""
    proc.terminate()
    try:
        proc.wait(timeout=GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()


def on_signal(signum, _frame):
    logging.warning("Stopping the sweep (signal %d): terminating %d running variant(s)", signum, len(_procs))
    _stopping.set()
    with _lock:
        procs = list(_procs.values())
    for proc in procs:
        threading.Thread(target=stop, args=(proc,), daemon=True).start()


def git_state(project):
    """'<commit>' or '<commit> (with uncommitted changes)', '' outside git."""
    def git(*args):
        try:
            return subprocess.run(["git", "-C", project, *args], capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    commit = git("rev-parse", "--short", "HEAD")
    if not commit:
        return ""
    dirty = git("status", "--porcelain", "--untracked-files=no")
    return commit + (" (with uncommitted changes)" if dirty else "")


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def metric_text(metric):
    value = metric.get("value")
    if value is None or value == "":
        return "—"
    unit = metric.get("unit", "")
    return f"{value} {unit}".strip() if unit and unit != "%" else f"{value}{unit}"


def row(cells):
    """A Markdown table row of cells."""
    return "| " + " | ".join(cells) + " |"


def options_text(options):
    return ", ".join(f"`{o}`" for o in options) if options else "—"


def write_report(V, runs, started, commit):
    """report.md and results.csv as the sweep stands now."""
    summaries = {r["name"]: summary_of(r) for r in runs}
    columns, labels = [], {}
    for summary in summaries.values():
        for metric in (summary or {}).get("metrics", []):
            if isinstance(metric, dict) and metric.get("name") and metric["name"] not in labels:
                columns.append(metric["name"])
                labels[metric["name"]] = metric.get("label") or metric["name"]

    first = runs[0]
    done = sum(r["status"] not in ("pending", "running") for r in runs)
    lines = [f"# Sweep {V['BAKE_BLOCK']}", ""]
    if V.get("BAKE_SWEEP_DESC"):
        lines += [V["BAKE_SWEEP_DESC"], ""]
    lines += [
        f"- **Runs:** `{first['block']} {first['recipe']}`, {len(runs)} variants, {done} finished",
        f"- **Commit:** {commit or 'not a git checkout'}",
        f"- **Started:** {started:%Y-%m-%d %H:%M}",
        f"- **Options of every variant:** {options_text(V.get('BAKE_SWEEP_OPTIONS', []))}",
        "",
        "## Results",
        "",
        row(["Variant", "Options", "Status", "Stage", *(cell(labels[c]) for c in columns)]),
        "|" + "---|" * (4 + len(columns)),
    ]
    for r in runs:
        summary = summaries[r["name"]] or {}
        values = {m["name"]: metric_text(m) for m in summary.get("metrics", [])
                  if isinstance(m, dict) and m.get("name")}
        lines.append(row([cell(r["name"]), cell(options_text(r["variant_options"])), r["status"],
                          cell(summary.get("stage", "—")), *(cell(values.get(c, "—")) for c in columns)]))

    notes = []
    for r in runs:
        summary = summaries[r["name"]] or {}
        items = [str(n) for n in summary.get("notes", [])]
        if summary.get("error"):
            items.insert(0, f"Error: {summary['error']}")
        elif r["status"] in ("failed", "timeout") and not summary:
            items.insert(0, f"{r['status'].capitalize()} without a summary: see `{r['dir'] / 'run.log'}`")
        if r["status"] == "partial":
            items.insert(0, "Partial: the flow finished, but the step lacks outputs it expects "
                            "(a run stopped before the end of its flow, say)")
        if items:
            notes += [f"### {r['name']}", ""] + [f"- {cell(i)}" for i in items] + [""]
    if notes:
        lines += ["", "## Notes", ""] + notes
    else:
        lines += [""]

    lines += [
        "## Conclusion",
        "",
        "_What the runs answer, and the choice it leads to. Every run of the sweep rewrites this "
        "file: write the conclusion in a copy._",
        "",
        "## Inspect",
        "",
        f"From the sweep directory, `{Path.cwd()}`, with `P={V['BAKE_SWEEP_PROJECT']}`:",
        "",
    ]
    for r in runs:
        summary = summaries[r["name"]] or {}
        rel = Path("runs") / r["name"]
        found = summary_path(r)
        work = found.parent.relative_to(Path.cwd()) if found else rel / r["block"] / r["recipe"]
        rerun = ["bake", "-m", "$P", r["block"], r["recipe"]]
        for option in r["options"] + [f"bake.output_dir={rel}"]:
            rerun += ["-o", option]
        lines += [f"- **{r['name']}**: work directory `{work}`, log `{rel / 'run.log'}`",
                  f"  - rerun: `{' '.join(shlex.quote(a) if a != '$P' else a for a in rerun)}`"]
        for item in summary.get("inspect", []):
            if not isinstance(item, dict) or not item.get("command"):
                continue
            then = f", then `{item['then']}`" if item.get("then") else ""
            lines.append(f"  - {cell(item.get('what', 'inspect'))}: "
                         f"`cd {shlex.quote(str(work))} && {item['command']}`{then}")
    lines.append("")

    Path("report.md").write_text("\n".join(lines), encoding="utf-8")
    with open("results.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["variant", "status", "stage", "seconds", *columns, "dir"])
        for r in runs:
            summary = summaries[r["name"]] or {}
            values = {m["name"]: m.get("value", "") for m in summary.get("metrics", [])
                      if isinstance(m, dict) and m.get("name")}
            writer.writerow([r["name"], r["status"], summary.get("stage", ""),
                             f"{r['seconds']:.1f}" if r["seconds"] is not None else "",
                             *[values.get(c, "") for c in columns], r["dir"]])


def main():
    with open(os.environ.get("BAKE_VARS", "bake_vars.json"), encoding="utf-8") as f:
        V = json.load(f)
    timeout = float(V["BAKE_FLOW_OPT_TIMEOUT"]) or None
    runs = [{**run, "status": "pending", "seconds": None, "dir": (Path("runs") / run["name"]).absolute()}
            for run in V["BAKE_SWEEP_RUNS"]]
    jobs = int(V["BAKE_FLOW_OPT_JOBS"]) or len(runs)
    started = datetime.datetime.now()
    commit = git_state(V["BAKE_SWEEP_PROJECT"])

    Path("sweep.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    report = Path("report.md").absolute()
    logging.info("Sweep %s: %d variants of %s %s, %d at a time; report: %s",
                 V["BAKE_BLOCK"], len(runs), runs[0]["block"], runs[0]["recipe"], min(jobs, len(runs)), report)
    logging.info("Stop it with: kill %d", os.getpid())
    write_report(V, runs, started, commit)

    def report_now():
        with _lock:
            write_report(V, runs, started, commit)

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(execute, run, timeout, report_now): run for run in runs}
        finished = 0
        for future in concurrent.futures.as_completed(futures):
            run = futures[future]
            run.update(future.result())
            finished += 1
            report_now()
            logging.info("[%d/%d] %-7s %s (%.0f s)", finished, len(runs), run["status"], run["name"],
                         run["seconds"])

    failed = [r for r in runs if r["status"] not in ("passed", "partial")]
    partial = [r for r in runs if r["status"] == "partial"]
    logging.info("Sweep %s: %d variants, %d passed, %d partial, %d not; report: %s",
                 V["BAKE_BLOCK"], len(runs), len(runs) - len(failed) - len(partial), len(partial),
                 len(failed), report)
    for r in partial:
        logging.warning("partial %s: the step lacks outputs it expects (%s)", r["name"], r["dir"] / "run.log")
    for r in failed:
        logging.error("%s %s: %s", r["status"], r["name"], r["dir"] / "run.log")
    Path("sweep.pid").unlink(missing_ok=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[sweep] %(levelname)s\t %(message)s")
    main()
