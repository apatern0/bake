#!/usr/bin/env python3
"""A regression flow of the project's own: the runs one after the other, each
in a directory of its own (the example of docs/custom_flows.md)."""

import json
import os
from pathlib import Path
import subprocess
import sys

with open(os.environ["BAKE_VARS"], encoding="utf-8") as f:
    V = json.load(f)

failed = 0
for run in V["BAKE_REGRESSION_RUNS"]:
    run_dir = Path("runs") / run["name"]
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "run.log", "w", encoding="utf-8") as log:
        code = subprocess.run(run["command"], cwd=run_dir, stdout=log, stderr=subprocess.STDOUT,
                              check=False).returncode
    print(f"{run['name']}: {'passed' if code == 0 else 'failed'}", flush=True)
    failed += code != 0
sys.exit(1 if failed else 0)
