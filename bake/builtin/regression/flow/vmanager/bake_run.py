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

"""One run of a regression in a vManager session: the bake invocation of a
test of runs.json, in the run directory (the current directory), which is
the test's work directory (vrf.run_dir).

Usage: bake_run.py <runs.json> <index>

The seed is the run's sv_seed. A number repeats a run; "random", which is
how vManager passes `sv_seed: random` on, lets bake draw one, which bake.flt
records as the run's sv_seed, so that a rerun from vManager repeats it.
"""

import json
import os
import shlex
import sys


def command(run, seed, run_dir):
    """The run's seed, then its options, which may override it, then its directory."""
    options = ([f"vrf.seed={seed}"] if seed.isdigit() else []) + run["options"]
    options.append(f"vrf.run_dir={run_dir}")
    cmd = list(run["command"])
    for option in options:
        cmd += ["-o", option]
    return cmd


def main():
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <runs.json> <index>")
    with open(sys.argv[1], encoding="utf-8") as f:
        run = json.load(f)[int(sys.argv[2])]
    cmd = command(run, os.environ.get("BRUN_SV_SEED", "random"), os.getcwd())
    print(shlex.join(cmd), flush=True)
    os.execv(cmd[0], cmd)


if __name__ == "__main__":
    main()
