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

import os
from pathlib import Path

from . import exceptions


def absolute_path(path):
    return str(Path(os.path.expanduser(os.path.expandvars(path))).resolve())


def check_file(path):
    if not Path(path).is_file():
        raise exceptions.BakeFileError(f"File {path} does not exist")


def check_files(files):
    for path in files:
        check_file(path)


def check_dir(path):
    if not Path(path).is_dir():
        raise exceptions.BakeFileError(f"Directory {path} does not exist")


def check_dir_or_file(path):
    p = Path(path)
    if not (p.is_dir() or p.is_file()):
        raise exceptions.BakeFileError(f"Directory or file {path} does not exist")


def files_from_folder(path):
    check_dir(path)
    return [str(f) for f in Path(path).rglob("*") if f.is_file()]


def resolve_file_list(paths: list) -> None:
    """Resolve each path in-place to an absolute path and verify it exists."""
    for i, p in enumerate(paths):
        paths[i] = absolute_path(p)
        check_file(paths[i])


def resolve_dir_list(paths: list) -> None:
    """Resolve each path in-place to an absolute path and verify it exists."""
    for i, p in enumerate(paths):
        paths[i] = absolute_path(p)
        check_dir(paths[i])
