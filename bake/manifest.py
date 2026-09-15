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

"""Manifest rule definitions

This module contains the design specification rules exposed to the manifest.
Type validation is performed automatically by Pydantic on instantiation.
Errors raise a ManifestError together with a meaningful error description.
"""

import functools
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import loader
from . import file_utils
from .context import context
from .exceptions import BakeManifestError


def load(path):
    loader.load(path)


class FlowSpec(BaseModel):
    model_config = ConfigDict(validate_default=True)

    name: str = ""
    desc: str = ""
    corners: list = Field(default_factory=list)
    simulators: list = Field(default_factory=list)
    simulation_frameworks: list = Field(default_factory=list)
    run_cmd: str = "run.py"
    dir: str = ""

    def model_post_init(self, __context: Any) -> None:
        self.dir = self.dir or str(Path.cwd() / "flow")
        if self.name in context.flows:
            raise BakeManifestError(f"Redefinition of flow {self.name} detected")
        context.flows[self.name] = self
        logging.debug(
            "Registered flow '%s' (dir=%s, corners=%d, simulators=%s)",
            self.name, self.dir, len(self.corners), self.simulators or "any",
        )


class LibSpec(BaseModel):
    model_config = ConfigDict(validate_default=True)

    name: str = ""
    desc: str = ""
    netlist_files: list = Field(default_factory=list)
    netlist_incdirs: list = Field(default_factory=list)
    liberty_files: dict = Field(default_factory=dict)
    layout_info: str = ""
    si_files: dict = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.name in context.libs:
            raise BakeManifestError(f"Redefinition of library {self.name} detected")

        file_utils.resolve_file_list(self.netlist_files)
        file_utils.resolve_dir_list(self.netlist_incdirs)

        if self.layout_info:
            self.layout_info = os.path.expandvars(self.layout_info)
            if Path(self.layout_info).is_dir() or Path(self.layout_info).is_file():
                self.layout_info = file_utils.absolute_path(self.layout_info)

        for attr in (self.liberty_files, self.si_files):
            for corner_name, corner_files in attr.items():
                if not isinstance(corner_files, list):
                    attr[corner_name] = [corner_files]
                file_utils.resolve_file_list(attr[corner_name])

        context.libs[self.name] = self
        logging.debug(
            "Registered library '%s' (%d netlist files, %d liberty corners, %d SI corners)",
            self.name,
            len(self.netlist_files),
            len(self.liberty_files),
            len(self.si_files),
        )


class BlockSpec(BaseModel):
    model_config = ConfigDict(validate_default=True)

    name: str = ""
    desc: str = ""
    includes: dict = Field(default_factory=dict)   # {block_name: recipe_str}
    skip_on_include_errors: bool = False
    dir: str = ""

    # RTL step
    top: str = ""
    rtl_files: list = Field(default_factory=list)
    rtl_incdirs: list = Field(default_factory=list)

    # Gate-level / implementation step (user-declared post-impl info)
    netlist_files: list = Field(default_factory=list)
    netlist_incdirs: list = Field(default_factory=list)
    liberty_files: dict = Field(default_factory=dict)   # {corner: [files]}
    si_files: dict = Field(default_factory=dict)    # {corner: [files]}
    layout_info: str = ""

    # Pipeline step files
    sdc_files: list = Field(default_factory=list)   # design constraints
    vcd_files: list = Field(default_factory=list)   # value change dump
    saif_files: dict = Field(default_factory=dict)  # switching activity {corner: [files]}

    # PDK cell library dependencies (LibSpec names)
    libs: list = Field(default_factory=list)

    @field_validator("includes", mode="before")
    @classmethod
    def coerce_includes(cls, v):
        # Convenience: a plain list of block names is treated as {name: "rtl"}.
        # The dict form allows specifying a recipe (e.g. {name: "tmr-impl"}).
        if isinstance(v, list):
            return {item: "rtl" for item in v}
        if not isinstance(v, dict):
            raise BakeManifestError("Target includes must be dict.")
        return v

    @functools.cached_property
    def available_tests(self):
        return [t.name for t in context.find_test_by_target(self.name)]

    @functools.cached_property
    def resolved_libs(self):
        # Cached so repeated accesses (e.g. from multiple steps) don't
        # re-validate corner consistency on every call.
        libs = []
        for n in self.libs:
            if n not in context.libs:
                raise BakeManifestError(f"Library {n} not defined")
            libs.append(context.libs[n])
            context.check_lib_corners(context.libs[n])
        return libs

    def _validate_include(self, dep_name: str, dep_recipe_str: str) -> None:
        """Validate that a non-rtl include recipe resolves to an existing outputdir."""
        logging.debug(
            "Validating include '%s' (recipe '%s') for block '%s'",
            dep_name, dep_recipe_str, self.name,
        )
        from . import step as step_module
        recipe_parts = dep_recipe_str.split("-")
        for part in recipe_parts:
            if part not in context.steps:
                raise BakeManifestError(
                    f"Unsupported step '{part}' in include recipe '{dep_recipe_str}'"
                )
        if dep_name not in context.blocks:
            raise BakeManifestError(
                f"Unable to create impl library: block '{dep_name}' not defined"
            )
        dep_block = context.blocks[dep_name]
        dep_data = step_module.StepData(target=dep_block)
        last_step_inst = None
        for part in recipe_parts:
            last_step_inst = context.steps[part](dep_data)
            dep_data = last_step_inst.output_data
        if not Path(last_step_inst.outputdir).is_dir():
            raise BakeManifestError(
                f"Unable to create impl library: output directory not found for "
                f"'{dep_name} {dep_recipe_str}'. Run it first."
            )

    def model_post_init(self, __context: Any) -> None:
        if self.name in context.blocks:
            raise BakeManifestError(f"Redefinition of block {self.name} detected")
        self.dir = str(Path.cwd())
        file_utils.resolve_file_list(self.rtl_files)
        file_utils.resolve_dir_list(self.rtl_incdirs)
        file_utils.resolve_file_list(self.netlist_files)
        file_utils.resolve_dir_list(self.netlist_incdirs)
        file_utils.resolve_file_list(self.sdc_files)
        file_utils.resolve_file_list(self.vcd_files)
        for attr_name in ("liberty_files", "si_files", "saif_files"):
            corner_dict = getattr(self, attr_name)
            for corner_name, corner_files in corner_dict.items():
                if not isinstance(corner_files, list):
                    corner_dict[corner_name] = [corner_files]
                file_utils.resolve_file_list(corner_dict[corner_name])
        if self.layout_info:
            self.layout_info = os.path.expandvars(self.layout_info)
            if Path(self.layout_info).is_dir() or Path(self.layout_info).is_file():
                self.layout_info = file_utils.absolute_path(self.layout_info)
        # Validate non-rtl includes at parse time (checks outputdir existence).
        try:
            for dep_name, dep_recipe_str in self.includes.items():
                if dep_recipe_str != "rtl":
                    self._validate_include(dep_name, dep_recipe_str)
        except BakeManifestError as e:
            if self.skip_on_include_errors:
                logging.warning(
                    "Skipping registration of block '%s': include validation failed (%s)",
                    self.name, e,
                )
                return
            raise
        context.blocks[self.name] = self
        logging.debug(
            "Registered block '%s' (top=%s, %d RTL files, %d includes)",
            self.name, self.top or "<none>", len(self.rtl_files), len(self.includes),
        )


class EnvSpec(BaseModel):
    model_config = ConfigDict(validate_default=True, populate_by_name=True)

    name: str = ""
    desc: str = ""
    includes: list = Field(default_factory=list)
    target: str = ""
    vrf_top: str = ""
    vrf_files: list = Field(default_factory=list)
    vrf_incdirs: list = Field(default_factory=list)
    vrf_libs: list = Field(default_factory=list)
    vrf_options: dict = Field(default_factory=dict)
    vrf_defines: list = Field(default_factory=list)
    vrf_framework: str = ""
    vrf_framework_top: str = ""
    default_sim: str = ""
    is_test: bool = False

    @functools.cached_property
    def resolved_libs(self):
        # Cached so repeated accesses (e.g. from multiple steps) don't
        # re-validate corner consistency on every call.
        libs = []
        for n in self.vrf_libs:
            if n in context.libs:
                spec = context.libs[n]
            elif n in context.blocks:
                spec = context.blocks[n]
            else:
                raise BakeManifestError(f"Library {n} not defined")
            libs.append(spec)
            context.check_lib_corners(spec)
        return libs

    def _inherit_target(self) -> None:
        """Fill in `target` from the first included environment that has one.

        Environments are registered before the tests that include them, so a
        depth-first walk over `includes` sees every ancestor."""
        if self.target:
            return
        for dep_name in self.includes:
            dep = context.envs.get(dep_name)
            if dep is not None and dep.target:
                self.target = dep.target
                logging.debug(
                    "'%s' inherits target '%s' from environment '%s'",
                    self.name, dep.target, dep_name,
                )
                return

    def model_post_init(self, __context: Any) -> None:
        file_utils.resolve_file_list(self.vrf_files)
        file_utils.resolve_dir_list(self.vrf_incdirs)
        self._inherit_target()

        if self.is_test:
            context.tests.append(self)
            logging.debug(
                "Registered test '%s' for target '%s' (%d vrf files, framework=%s)",
                self.name, self.target, len(self.vrf_files), self.vrf_framework or "none",
            )
        else:
            if self.name in context.envs:
                raise BakeManifestError(f"Redefinition of environment {self.name} detected")
            context.envs[self.name] = self
            logging.debug(
                "Registered environment '%s' (%d vrf files, %d includes)",
                self.name, len(self.vrf_files), len(self.includes),
            )


class TestSpec(EnvSpec):
    is_test: bool = True


flow  = FlowSpec
lib   = LibSpec    # PDK cell libraries
block = BlockSpec  # user design blocks
env   = EnvSpec
test  = TestSpec



def add_steps_dir(path):
    """Register an external directory containing custom Step classes."""
    if not isinstance(path, str):
        raise BakeManifestError("Steps directory path must be str.")
    abs_path = file_utils.absolute_path(path)
    if not Path(abs_path).is_dir():
        raise BakeManifestError(f"Steps directory does not exist: {abs_path}")
    context.config.bake.steps_dirs.append(abs_path)
    logging.debug("Registered custom steps directory: %s", abs_path)
    loader.load_steps_dir(abs_path)
