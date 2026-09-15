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

import re
import logging
from . import file_utils
from .exceptions import (
    BakeConfigError,
    BakeInternalError,
    BakeManifestError,
)
from .file_utils import absolute_path


class WriteOnceProperty:
    """Descriptor that allows a config attribute to be set exactly once.

    Optionally enforces ordering constraints: before_libs/before_targets/
    before_flows ensure the attribute is set before any libs, blocks, or
    flows are registered, catching manifest ordering mistakes early.
    """

    def already_set(self, instance, value):
        raise BakeConfigError(f"Read-only property {self.name} has already been set.")

    def default_set(self, instance, value):
        if self.before_libs and context.libs_defined():
            raise BakeConfigError(f"Property {self.name} must be set before any library is created.")

        if self.before_targets and context.blocks_defined():
            raise BakeConfigError(f"Property {self.name} must be set before any target is created.")

        if self.before_flows and context.flows_defined():
            raise BakeConfigError(f"Property {self.name} must be set before any flow is created.")

        instance.__dict__[self.name] = value if not self.is_file else absolute_path(value)
        self.setter_func = self.already_set

    def __set_name__(self, owner, name):
        self.owner = owner
        self.name = name

    def __init__(self, before_targets=None, before_libs=None, before_flows=None, before_all=None, is_file=False):
        self.setter_func = self.default_set

        self.before_libs = before_libs or (before_all and before_libs is None)
        self.before_flows = before_flows or (before_all and before_flows is None)
        self.before_targets = before_targets or (before_all and before_targets is None)
        self.is_file = is_file

    def __get__(self, instance, objtype=None):
        if instance is None:
            return self
        return instance.__dict__.get(self.name)

    def __set__(self, instance, value):
        self.setter_func(instance, value)

    def __delete__(self, instance):
        raise BakeConfigError(f"Read-only property {self.name} cannot be deleted.")


class ReadOnlyAttributes:
    """Mixin that prevents all attribute writes, both new and existing."""
    def __setattr__(self, key, value):
        if key not in self.__dir__():
            raise BakeConfigError(f"Cannot add new attributes to class {self.__class__.__name__}")
        else:
            raise BakeConfigError(f"Cannot modify attribute '{key}' of class {self.__class__.__name__}")


class FixedSchemaAttributes:
    """Mixin that allows writes to declared attributes but prevents adding new ones."""
    def __setattr__(self, key, value):
        if key not in self.__dir__():
            raise BakeConfigError(f"Cannot add new attributes to class {self.__class__.__name__}")
        super().__setattr__(key, value)


class TemplateDictionary(dict):
    def __setitem__(self, key, value):
        if not key.startswith("BAKE_"):
            raise BakeConfigError(f"Template variable '{key}' doesn't begin with 'BAKE_'")

        if re.search(r"[^A-Z0-9_]", key) is not None:
            raise BakeConfigError(f"Template variable '{key}' can only contain upper case letters, numbers, and underscores")

        if key in self:
            raise BakeConfigError(f"Cannot overwrite template variable '{key}'")

        super().__setitem__(key, value)


class BakeConfig(FixedSchemaAttributes):
    tpl_dict = TemplateDictionary()
    vrf_simulator = "auto"
    file_copy_method = "copy"
    steps_dirs = None   # per-instance list; assigned in __init__
    options = []
    output_dir = None
    verbosity = 0
    interactive = False
    test = None
    force = False
    populate = False
    clean = False
    restart = False

    def __init__(self):
        self.steps_dirs = []


class UserConfig:
    pass


class Config:
    """Groups all user-facing configuration sections.

    bake and user are always present. Step-specific sections (impl, vrf, tmr, ...)
    are registered dynamically when step modules are discovered via build_registry().
    """

    bake = BakeConfig()
    user = UserConfig()
    TemplateDictionary = TemplateDictionary  # exposed for use in manifest exec scope

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)

    def register(self, name: str, section) -> None:
        """Register a config section by name. Idempotent."""
        if name not in vars(self):
            object.__setattr__(self, name, section)
            logging.debug("Registered config section '%s' (%s)", name, type(section).__name__)

    def __getattr__(self, key):
        raise BakeConfigError(
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
        self.flows = {}
        self.libs = {}    # LibSpec objects (PDK/foundry cell libraries)
        self.blocks = {}  # BlockSpec objects (user design blocks)
        self.envs = {}
        self.tests = []
        self.steps = {}

    def libs_defined(self):
        return len(self.libs) > 0

    def blocks_defined(self):
        return len(self.blocks) > 0

    def flows_defined(self):
        return len(self.flows) > 0

    # ------------------------------------------------------------------
    # Library corner helpers
    # ------------------------------------------------------------------

    def get_impl_corners(self):
        flow_name = self.config.impl.flow
        if not flow_name or flow_name not in self.flows:
            raise BakeInternalError("No implementation flow configured while checking library corners.")
        return self.flows[flow_name].corners

    def check_lib_corners(self, lib_spec):
        # TODO: complete corner validation — disabled until the impl flow selection
        # is reliable at lib-registration time (check_lib_corners is called from
        # resolved_libs which runs at manifest-parse time, before config.impl.flow
        # is necessarily set).
        return True
        if not lib_spec.liberty_files:
            logging.warning("No timing libraries have been defined for library %s", lib_spec.name)
            return

        corners = self.get_impl_corners()
        for corner_name, corner_desc in corners:
            if corner_name not in lib_spec.liberty_files:
                raise BakeManifestError(f"{corner_desc} corner missing for library {lib_spec.name}")

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


    def log_targets_and_tests(self):
        rtl_blocks = {n: b for n, b in self.blocks.items() if b.rtl_files}
        if not rtl_blocks:
            logging.info("No blocks with RTL files are registered.")
            return

        logging.info("Available blocks and associated tests:")
        for name, b in rtl_blocks.items():
            logging.info("- %s", name)
            for t in self.find_test_by_target(name):
                logging.info("    - %s", t.name)

context = Context()
