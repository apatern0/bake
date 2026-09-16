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
~/.cache/bake/completion_cache.json and is updated after every successful
manifest load.  Setting BAKE_NO_CACHE suppresses all cache I/O.
"""

import json
import logging
import os
from pathlib import Path

from .context import context

cache = {}


def load_from_file():
    """Populate the cache from the local user's home directory.

    Will fail silently if no completion cache file exists or no cache entry
    exists for the current working directory.
    """
    global cache
    cache = {}
    cache_file = Path.home() / ".cache" / "bake" / "completion_cache.json"

    if "BAKE_NO_CACHE" in os.environ:
        logging.debug("BAKE_NO_CACHE set — skipping completion cache load")
        return

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
        logging.debug("Loaded completion cache from %s (%d entries)", cache_file, len(cache))
    except FileNotFoundError:
        logging.debug("Completion cache not found at %s, starting empty", cache_file)
    except (OSError, json.JSONDecodeError) as e:
        logging.debug("Completion cache at %s cannot be read and will be ignored: %s", cache_file, e)
        cache = {}


def store_to_file():
    """Update the cache storage in the local user's home directory.

    Will create a new cache file if none exists. Will fail silently if the
    cache directory or file cannot be created.
    """
    cwd = str(Path.cwd())
    cache_file = Path.home() / ".cache" / "bake" / "completion_cache.json"

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

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        logging.debug(
            "Stored completion cache for '%s' (%d targets)",
            cwd, len(cache[cwd]["targets_tests"]),
        )
    except (IOError, OSError) as e:
        logging.debug("Could not write completion cache to %s: %s", cache_file, e)


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
