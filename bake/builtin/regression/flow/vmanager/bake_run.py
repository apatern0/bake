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

"""One run of a regression in a vManager session: the command of a run of
runs.json, in the vManager run directory (the current directory), which is
the test's work directory.

Usage: bake_run.py <runs.json> <index>

A run with a random seed gets "random" as its sv_seed, which is how vManager
passes `sv_seed: random` on, and bake draws one, which bake.flt records as
the run's sv_seed. A rerun from vManager then gets that number, which it
passes on to bake to repeat the run.
"""

import json
import os
import shlex
import sys


def command(run, seed):
    """The run's command; a rerun of a run with a random seed repeats the
    seed it recorded, which is the one the run used."""
    if run["seed"] is None and seed.isdigit():
        return run["command"] + ["-o", f"vrf.seed={seed}"]
    return list(run["command"])


def main():
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <runs.json> <index>")
    with open(sys.argv[1], encoding="utf-8") as f:
        run = json.load(f)[int(sys.argv[2])]
    cmd = command(run, os.environ.get("BRUN_SV_SEED", "random"))
    print(shlex.join(cmd), flush=True)
    os.execv(cmd[0], cmd)


if __name__ == "__main__":
    main()
