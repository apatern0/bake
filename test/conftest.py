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

"""Fixtures: an isolated copy of the test projects, and an in-process bake runner."""

import os
import shutil
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = REPO_DIR / "test" / "projects"


@pytest.fixture(autouse=True)
def tmp_run_dir(monkeypatch, tmp_path):
    """Run each test in an isolated temporary directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAKE_NO_CACHE", "1")
    return tmp_path


@pytest.fixture
def project(tmp_run_dir, monkeypatch):
    """Copy test/projects (and example/, which some projects refer to) into the
    temporary directory, keeping the repository layout so relative paths hold,
    and change into the named project. Returns its path."""
    dest = tmp_run_dir / "test" / "projects"
    shutil.copytree(PROJECTS_DIR, dest)
    shutil.copytree(REPO_DIR / "example", tmp_run_dir / "example",
                    ignore=shutil.ignore_patterns("work", "flow"))

    def enter(name):
        path = dest / name
        assert path.is_dir(), f"no test project named {name!r}"
        monkeypatch.chdir(path)
        return path

    return enter


class Bake:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch

    def run(self, arg_list=None):
        """Execute bake main; assert it calls sys.exit() and return the exit code."""
        arg_list = arg_list or []
        self._monkeypatch.setattr("sys.argv", ["bake"] + arg_list)

        from bake.cli import main as bake_main
        with pytest.raises(SystemExit) as retval:
            bake_main()
        return retval.value.code


@pytest.fixture
def bake(monkeypatch):
    return Bake(monkeypatch)


def stderr(capfd):
    """Everything bake logged so far (drains the capture buffer)."""
    return str(capfd.readouterr())
