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

"""Saves the block as a release with `bake-release pack --from-vars`, which
reads everything from bake_vars.json, and keeps the uncommitted changes of
a dirty working tree in the release's reports (git.diff). A project's own
publish flow does the same after its checks, adding --checks-json, --stream,
--lvs and --report."""

import json
import os
import subprocess
import sys


def main():
    vars_path = os.environ.get("BAKE_VARS", "bake_vars.json")
    with open(vars_path, encoding="utf-8") as f:
        V = json.load(f)
    os.makedirs("output", exist_ok=True)
    command = [V["BAKE_PUBLISH_PYTHON"], "-m", "bake.release_cli", "pack",
               "--from-vars", vars_path, "--published-json", "output/published.json"]
    git = V["BAKE_PUBLISH_GIT"]
    if git.get("dirty"):
        def run(*args):
            return subprocess.run(["git", "-C", git["repo"], *args],
                                  capture_output=True, text=True, check=False).stdout
        with open("git.diff", "w", encoding="utf-8") as f:
            f.write("# git status --porcelain\n" + run("status", "--porcelain") + "\n")
            f.write(run("diff", "HEAD"))
        command += ["--report", "git.diff"]
    return subprocess.call(command)


if __name__ == "__main__":
    sys.exit(main())
