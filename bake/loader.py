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

import logging
import os
from pathlib import Path

from . import file_utils
from .context import context

loaded = []


def reset_context():
    global loaded
    loaded = []


def load(path):
    """Load a manifest file.

    Loads a file called "manifest" from the provided path. Relative paths will
    be treated as relative to the current manifest path, and will be converted
    into absolute paths.

    The cwd is temporarily changed to the manifest directory so that relative
    file paths declared inside the manifest resolve correctly at parse time.
    The original cwd is always restored in the finally block.

    Deduplication via the `loaded` list prevents the same manifest from being
    executed twice when multiple blocks include the same dependency.
    """
    global loaded

    manifest_path = str(Path(file_utils.absolute_path(path)) / "manifest")

    if manifest_path in loaded:
        logging.debug("Skipping already-loaded manifest: %s", manifest_path)
        return

    logging.debug("Loading manifest: %s", manifest_path)
    loaded.append(manifest_path)

    file_utils.check_file(manifest_path)

    _exec_in_dir(manifest_path)
    logging.debug("Manifest loaded successfully: %s", manifest_path)


def load_steps_dir(path):
    """Execute every ``*.py`` file in ``path`` as manifest code.

    This is what ``add_steps_dir()`` calls: each file is run with the same
    injected ``config`` object as a manifest, so a ``Step`` subclass defined
    in it registers itself via ``Step.__init_subclass__``. Files are loaded in
    sorted order and never twice.
    """
    global loaded

    steps_dir = Path(file_utils.absolute_path(path))
    for step_file in sorted(steps_dir.glob("*.py")):
        step_path = str(step_file)
        if step_path in loaded:
            logging.debug("Skipping already-loaded step file: %s", step_path)
            continue
        logging.debug("Loading step file: %s", step_path)
        loaded.append(step_path)
        _exec_in_dir(step_path)


def _exec_in_dir(script_path):
    """``exec`` a manifest-style script with its own directory as cwd."""
    oldpath = Path.cwd()
    os.chdir(Path(script_path).parent)
    try:
        with open(script_path) as f:
            source = f.read()

        # Manifests are trusted Python and run with full interpreter access.
        # Only __file__ and config are injected, but manifests can import
        # anything in the environment.  Do not load manifests from untrusted sources.
        symbols = {'__file__': script_path, 'config': context.config}
        exec(compile(source, script_path, "exec"), symbols)
    finally:
        os.chdir(oldpath)
