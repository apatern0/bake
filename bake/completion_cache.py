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

"""Per-directory cache for tab-completion

The cache is keyed by absolute cwd so that different project directories each
get their own set of completions.  It is stored as JSON in
$XDG_CACHE_HOME/bake/completion_cache.json (~/.cache/bake/ by default) and
is updated after every successful manifest load.  Setting BAKE_NO_CACHE
suppresses all cache I/O.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from .context import context

cache: dict = {}


def cache_file() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "bake" / "completion_cache.json"


def load_from_file():
    """Populate the cache from the local user's home directory.

    Will fail silently if no completion cache file exists or no cache entry
    exists for the current working directory.
    """
    global cache
    cache = {}
    path = cache_file()

    if "BAKE_NO_CACHE" in os.environ:
        logging.debug("BAKE_NO_CACHE set — skipping completion cache load")
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        logging.debug("Loaded completion cache from %s (%d entries)", path, len(cache))
    except FileNotFoundError:
        logging.debug("Completion cache not found at %s, starting empty", path)
    except (OSError, json.JSONDecodeError) as e:
        logging.debug("Completion cache at %s cannot be read and will be ignored: %s", path, e)
        cache = {}
    if not isinstance(cache, dict):
        cache = {}


def store_to_file():
    """Update the cache storage in the local user's home directory.

    Will create a new cache file if none exists. Will fail silently if the
    cache directory or file cannot be created. Entries for directories
    that no longer exist are dropped; the file is replaced atomically so
    two bake runs cannot leave it half-written.
    """
    cwd = str(Path.cwd())
    path = cache_file()

    if "BAKE_NO_CACHE" in os.environ:
        logging.debug("BAKE_NO_CACHE set — skipping completion cache store")
        return

    cache[cwd] = {}
    cache[cwd]["targets_tests"] = {}
    for name, b in context.blocks.items():
        if b.rtl_files:
            cache[cwd]["targets_tests"][name] = b.available_tests

    cache[cwd]["config_keys"] = context.config.get_options_str_list()
    cache[cwd]["steps"] = list(context.steps.keys())

    for stale in [d for d in cache if not Path(d).is_dir()]:
        del cache[stale]
        logging.debug("Dropped completion cache entry for missing directory %s", stale)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
        logging.debug(
            "Stored completion cache for '%s' (%d targets)",
            cwd, len(cache[cwd]["targets_tests"]),
        )
    except OSError as e:
        logging.debug("Could not write completion cache to %s: %s", path, e)


def get_targets():
    cwd = str(Path.cwd())
    if cwd in cache:
        return cache[cwd]["targets_tests"].keys()
    return []


def get_tests(target):
    cwd = str(Path.cwd())
    if cwd in cache and target in cache[cwd]["targets_tests"]:
        return cache[cwd]["targets_tests"][target]
    return []


def get_config_keys():
    cwd = str(Path.cwd())
    if cwd in cache:
        return cache[cwd]["config_keys"]
    return []


def get_steps():
    cwd = str(Path.cwd())
    if cwd in cache:
        return cache[cwd].get("steps", [])
    return []
