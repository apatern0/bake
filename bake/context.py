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

import functools
import re
import logging
from typing import TYPE_CHECKING
from .exceptions import (
    BakeConfigAttributeError,
    BakeConfigError,
    BakeManifestError,
)

if TYPE_CHECKING:
    from .manifest import TestSpec


class FixedSchemaAttributes:
    """Base class for config sections whose attributes are fixed: __init__
    defines them, and once it returns, assigning a name that does not exist
    is an error — so a typo like `config.vrf.simulater = ...` stops bake
    instead of being ignored."""

    _bake_frozen = False
    _bake_section = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        init = cls.__init__

        @functools.wraps(init)
        def init_then_freeze(self, *args, **kw):
            init(self, *args, **kw)
            if type(self) is cls:  # the most derived class' __init__ has finished
                object.__setattr__(self, "_bake_frozen", True)

        cls.__init__ = init_then_freeze

    def __setattr__(self, key, value):
        if self._bake_frozen and key not in dir(self):
            section = self._bake_section or self.__class__.__name__
            raise BakeConfigAttributeError(
                f"config.{section} has no attribute '{key}'. "
                f"Known attributes: {', '.join(self._bake_attributes())}."
            )
        super().__setattr__(key, value)

    def _bake_attributes(self) -> list:
        return [a for a in dir(self) if not a.startswith("_") and not callable(getattr(self, a))]


class TemplateDictionary(dict):
    def __setitem__(self, key, value):
        if not key.startswith("BAKE_"):
            raise BakeConfigError(f"Template variable '{key}' doesn't begin with 'BAKE_'")

        if re.search(r"[^A-Z0-9_]", key) is not None:
            raise BakeConfigError(
                f"Template variable '{key}' can only contain upper case letters, numbers, and underscores"
            )

        if key in self:
            raise BakeConfigError(f"Cannot overwrite template variable '{key}'")

        super().__setitem__(key, value)


class BakeConfig(FixedSchemaAttributes):
    """Global bake settings: what manifests set (tpl_dict, file_copy_method,
    output_dir) and what the command line sets (the rest)."""

    _bake_section = "bake"

    # The mutable ones are given fresh values per instance in __init__.
    tpl_dict = None
    file_copy_method = "copy"
    options = None
    output_dir = None
    verbosity = 0
    interactive = False
    test = None
    force = False
    populate = False
    clean = False
    restart = False
    dry_run = False

    def __init__(self):
        self.tpl_dict = TemplateDictionary()
        self.options = []


class UserConfig:
    pass


class Config:
    """Groups all user-facing configuration sections.

    bake and user are always present. Step-specific sections (impl, vrf, tmr, ...)
    are registered dynamically when step modules are discovered via build_registry().
    """

    bake = BakeConfig()   # replaced by a fresh instance on every reset_sections()
    user = UserConfig()
    # Exposed for use in manifest exec scope
    TemplateDictionary = TemplateDictionary
    FixedSchemaAttributes = FixedSchemaAttributes

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)

    def register(self, name: str, section) -> None:
        """Register a config section by name. Idempotent."""
        if name not in vars(self):
            if isinstance(section, FixedSchemaAttributes):
                object.__setattr__(section, "_bake_section", name)
            object.__setattr__(self, name, section)
            logging.debug("Registered config section '%s' (%s)", name, type(section).__name__)

    def reset_sections(self) -> None:
        """Drop every dynamically registered section (impl, vrf, tmr, ...) and
        start `bake` from its defaults.

        The step manifests register their sections again on the next load, so
        each run starts clean; the CLI sets its options on the fresh `bake`
        afterwards. `user` is untouched: it holds free-form user attributes.
        """
        for name in list(vars(self)):
            delattr(self, name)
            logging.debug("Dropped config section '%s'", name)
        Config.bake = BakeConfig()

    def __getattr__(self, key):
        raise BakeConfigAttributeError(
            f"Tried to access non-existent section `{key}` from config. "
            f"Legal sections are: {', '.join(self._section_names())}"
        )

    def _section_names(self):
        names = []
        for name in dir(self):
            if name.startswith("_"):
                continue
            try:
                attr = getattr(self, name)
            except AttributeError:
                continue
            if callable(attr):
                continue
            names.append(name)
        return names

    def get_options_str_list(self):
        """Retrieve a string list of all defined config options."""
        result = []
        for section_name in self._section_names():
            section_obj = getattr(self, section_name)
            for attr in dir(section_obj):
                if not attr.startswith("_"):
                    result.append(f"{section_name}.{attr}")
        return result


class Context:
    """Holds runtime state (registries) and configuration (config attribute)."""

    __instance = None

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super(Context, cls).__new__(cls)
        return cls.__instance

    def __init__(self):
        if not hasattr(self, 'config'):
            self.config = Config()
        self.reset()

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)

    # ------------------------------------------------------------------
    # Registry state
    # ------------------------------------------------------------------

    def reset(self):
        logging.debug("Resetting context registries")
        self.config.reset_sections()
        self.flows = {}
        self.libs = {}    # LibSpec objects (PDK/foundry cell libraries)
        self.blocks = {}  # BlockSpec objects (user design blocks)
        self.envs = {}
        self.tests = []
        self.steps = {}

    def validate(self):
        """Check the declarations once every manifest has loaded.

        Includes may reference blocks and environments defined later, so
        their existence, the step names in include recipes, and the absence
        of include cycles are verified here rather than at registration.
        Whether an included recipe has been *run* is not a manifest property;
        that is decided when a recipe is elaborated.
        """
        for name, b in self.blocks.items():
            for dep_name, recipe in b.includes.items():
                if dep_name not in self.blocks:
                    raise BakeManifestError(
                        f"Block '{name}' includes unknown block '{dep_name}'"
                    )
                if recipe == "rtl":
                    continue
                for part in recipe.split("-"):
                    if part not in self.steps:
                        raise BakeManifestError(
                            f"Block '{name}' includes '{dep_name}' with recipe '{recipe}': "
                            f"unknown step '{part}'"
                        )

        for e in list(self.envs.values()) + self.tests:
            for dep_name in e.includes:
                if dep_name not in self.envs:
                    kind = "Test" if e.is_test else "Environment"
                    raise BakeManifestError(
                        f"{kind} '{e.name}' includes unknown environment '{dep_name}'"
                    )

        self._check_cycles(self.blocks, lambda b: b.includes, "Block")
        self._check_cycles(self.envs, lambda e: e.includes, "Environment")

    @staticmethod
    def _check_cycles(registry, deps_of, kind):
        state = {}  # name -> "visiting" | "done"

        def visit(name, path):
            if state.get(name) == "done":
                return
            if state.get(name) == "visiting":
                cycle = path[path.index(name):] + [name]
                raise BakeManifestError(
                    f"{kind} include cycle: {' -> '.join(cycle)}"
                )
            state[name] = "visiting"
            for dep in deps_of(registry[name]):
                if dep in registry:
                    visit(dep, path + [name])
            state[name] = "done"

        for name in registry:
            visit(name, [])

    def libs_defined(self):
        return len(self.libs) > 0

    def blocks_defined(self):
        return len(self.blocks) > 0

    def flows_defined(self):
        return len(self.flows) > 0

    # ---------------------------------------------------------------------------
    # Helper functions for test discovery
    # ---------------------------------------------------------------------------

    def find_test(self, name: str, target: str) -> "TestSpec | None":
        result = next((t for t in self.tests if t.name == name and t.target == target), None)
        if result is None:
            logging.debug("Test '%s' not found for target '%s'", name, target)
        return result

    def find_test_by_target(self, target: str) -> "list[TestSpec]":
        return [t for t in self.tests if t.target == target]

    def test_exists(self, name: str, target: str) -> bool:
        return any(t.name == name and t.target == target for t in self.tests)

    # ------------------------------------------------------------------
    # Predicate helpers (usable from manifest code via `from bake import …`)
    # ------------------------------------------------------------------

    def is_flow(self, name: str) -> bool:
        return name in self.flows

    def is_block(self, name: str) -> bool:
        return name in self.blocks

    def is_target(self, name: str) -> bool:
        return name in self.blocks

    def is_env(self, name: str) -> bool:
        return name in self.envs

    def is_test(self, test_name: str, target_name: str) -> bool:
        return self.test_exists(test_name, target_name)


    # ---------------------------------------------------------------------------
    # Logging functions
    # ---------------------------------------------------------------------------

    def log_steps(self):
        logging.info("Available steps:")
        for name in self.steps:
            logging.info("- %s", name)

    def log_tests(self, target_name=None):
        if target_name:
            logging.info("Available tests for block %s:", target_name)
            for t in self.find_test_by_target(target_name):
                logging.info("- %s", t.name)
        else:
            logging.info("Available tests:")
            for t in context.tests:
                logging.info("- %s", t.name)


    def log_libs(self):
        logging.info("Available libraries (PDK):")
        for name in self.libs:
            logging.info("- %s", name)
        logging.info("Available blocks with timing libs:")
        for name, b in self.blocks.items():
            if b.liberty_files:
                logging.info("- %s", name)


    def log_targets(self):
        logging.info("Available blocks (with RTL):")
        for name, b in self.blocks.items():
            if b.rtl_files:
                logging.info("- %s", name)

context = Context()
