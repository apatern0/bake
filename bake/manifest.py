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
Errors raise a BakeManifestError together with a meaningful error description.

All specs forbid unknown fields, so a misspelled argument in a manifest is
reported instead of being silently ignored.
"""

import functools
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import loader
from . import file_utils
from .context import context
from .exceptions import BakeManifestError


def load(path):
    loader.load(path)


# Argument normalisation shared by the specs. Manifest authors write a
# single file where a list is expected, and Path objects where strings are;
# both are accepted before validation.
def _as_list(value):
    if isinstance(value, (str, os.PathLike)):
        value = [value]
    if isinstance(value, (list, tuple)):
        return [str(v) if isinstance(v, os.PathLike) else v for v in value]
    return value


def _as_corner_dict(value):
    """{corner: [files]}, with a single file per corner accepted."""
    if isinstance(value, dict):
        return {corner: _as_list(files) for corner, files in value.items()}
    return value


def _resolve_layout_info(value: str, owner: str) -> str:
    """layout_info names one or more LEF files or OpenAccess directories,
    space-separated. Each is made absolute; one that does not exist is
    reported, since the implementation flow will not find it either."""
    resolved = []
    for token in os.path.expandvars(value).split():
        if Path(token).exists():
            resolved.append(file_utils.absolute_path(token))
        else:
            logging.warning("%s: layout_info '%s' does not exist", owner, token)
            resolved.append(token)
    return " ".join(resolved)


class FlowSpec(BaseModel):
    model_config = ConfigDict(validate_default=True, extra="forbid")

    name: str = ""
    desc: str = ""
    corners: list = Field(default_factory=list)
    simulators: list = Field(default_factory=list)
    simulation_frameworks: list = Field(default_factory=list)
    run_cmd: str = "run.py"
    dir: str = ""
    # Defaults for the $BAKE_FLOW_OPT_<NAME> template variables the flow's
    # scripts reference; config.<step>.flow_options overrides them per project.
    tpl_defaults: dict = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        # `dir` is relative to the manifest registering the flow (the cwd
        # while it loads) and defaults to flow/ next to it.
        self.dir = file_utils.absolute_path(self.dir or "flow")
        if self.name in context.flows:
            raise BakeManifestError(f"Redefinition of flow {self.name} detected")
        if not Path(self.dir).is_dir():
            raise BakeManifestError(f"Flow '{self.name}': directory {self.dir} does not exist")
        context.flows[self.name] = self
        logging.debug(
            "Registered flow '%s' (dir=%s, corners=%d, simulators=%s)",
            self.name, self.dir, len(self.corners), self.simulators or "any",
        )


class LibSpec(BaseModel):
    model_config = ConfigDict(validate_default=True, extra="forbid")

    name: str = ""
    desc: str = ""
    netlist_files: list[str] = Field(default_factory=list)
    netlist_incdirs: list[str] = Field(default_factory=list)
    liberty_files: dict[str, list[str]] = Field(default_factory=dict)   # {corner: [files]}
    layout_info: str = ""
    si_files: dict[str, list[str]] = Field(default_factory=dict)        # {corner: [files]}

    _lists = field_validator("netlist_files", "netlist_incdirs", mode="before")(_as_list)
    _corner_dicts = field_validator("liberty_files", "si_files", mode="before")(_as_corner_dict)

    def model_post_init(self, __context: Any) -> None:
        if self.name in context.libs:
            raise BakeManifestError(f"Redefinition of library {self.name} detected")

        file_utils.resolve_file_list(self.netlist_files)
        file_utils.resolve_dir_list(self.netlist_incdirs)

        if self.layout_info:
            self.layout_info = _resolve_layout_info(self.layout_info, f"Library '{self.name}'")

        for corner_dict in (self.liberty_files, self.si_files):
            for corner_files in corner_dict.values():
                file_utils.resolve_file_list(corner_files)

        context.libs[self.name] = self
        logging.debug(
            "Registered library '%s' (%d netlist files, %d liberty corners, %d SI corners)",
            self.name,
            len(self.netlist_files),
            len(self.liberty_files),
            len(self.si_files),
        )


class BlockSpec(BaseModel):
    model_config = ConfigDict(validate_default=True, extra="forbid")

    name: str = ""
    desc: str = ""
    includes: dict = Field(default_factory=dict)   # {block_name: recipe_str}
    dir: str = ""

    # RTL step
    top: str = ""
    rtl_files: list[str] = Field(default_factory=list)
    rtl_incdirs: list[str] = Field(default_factory=list)

    # Gate-level / implementation step (user-declared post-impl info)
    netlist_files: list[str] = Field(default_factory=list)
    netlist_incdirs: list[str] = Field(default_factory=list)
    liberty_files: dict[str, list[str]] = Field(default_factory=dict)   # {corner: [files]}
    si_files: dict[str, list[str]] = Field(default_factory=dict)        # {corner: [files]}
    layout_info: str = ""

    # Pipeline step files
    sdc_files: list[str] = Field(default_factory=list)                  # design constraints
    vcd_files: dict[str, list[str]] = Field(default_factory=dict)       # value change dump {corner: [files]}
    saif_files: dict[str, list[str]] = Field(default_factory=dict)      # switching activity {corner: [files]}

    # PDK cell library dependencies (LibSpec names)
    libs: list[str] = Field(default_factory=list)

    _lists = field_validator("rtl_files", "rtl_incdirs", "netlist_files", "netlist_incdirs",
                             "sdc_files", "libs", mode="before")(_as_list)
    _corner_dicts = field_validator("liberty_files", "si_files", mode="before")(_as_corner_dict)

    @model_validator(mode="before")
    @classmethod
    def reject_removed_fields(cls, values):
        if isinstance(values, dict) and "skip_on_include_errors" in values:
            raise BakeManifestError(
                "skip_on_include_errors has been removed: includes are resolved when a "
                "recipe runs and dependencies are built on demand. Remove the argument."
            )
        return values

    @field_validator("vcd_files", "saif_files", mode="before")
    @classmethod
    def coerce_activity_files(cls, v):
        # Convenience: a file or a list of files, with no corner, is the
        # "default" corner.
        if isinstance(v, (str, os.PathLike, list, tuple)):
            v = {"default": v}
        return _as_corner_dict(v)

    @field_validator("includes", mode="before")
    @classmethod
    def coerce_includes(cls, v):
        # Convenience: a plain list of block names is treated as {name: "rtl"}.
        # The dict form allows specifying a recipe (e.g. {name: "tmr-impl"}).
        if isinstance(v, list):
            return {item: "rtl" for item in v}
        if not isinstance(v, dict):
            raise BakeManifestError("Block includes must be a list or a dict.")
        for dep_name, recipe in v.items():
            if not isinstance(recipe, str) or not recipe:
                raise BakeManifestError(
                    f"Include '{dep_name}': the recipe must be a non-empty string, e.g. \"rtl\" or \"impl\"."
                )
        return v

    @functools.cached_property
    def available_tests(self):
        return [t.name for t in context.find_test_by_target(self.name)]

    @functools.cached_property
    def resolved_libs(self):
        libs = []
        for n in self.libs:
            if n not in context.libs:
                raise BakeManifestError(f"Library {n} not defined")
            libs.append(context.libs[n])
        return libs

    def model_post_init(self, __context: Any) -> None:
        if self.name in context.blocks:
            raise BakeManifestError(f"Redefinition of block {self.name} detected")
        self.dir = str(Path.cwd())
        file_utils.resolve_file_list(self.rtl_files)
        file_utils.resolve_dir_list(self.rtl_incdirs)
        file_utils.resolve_file_list(self.netlist_files)
        file_utils.resolve_dir_list(self.netlist_incdirs)
        file_utils.resolve_file_list(self.sdc_files)
        for corner_dict in (self.liberty_files, self.si_files, self.vcd_files, self.saif_files):
            for corner_files in corner_dict.values():
                file_utils.resolve_file_list(corner_files)
        if self.layout_info:
            self.layout_info = _resolve_layout_info(self.layout_info, f"Block '{self.name}'")
        # Includes are checked once every manifest has loaded (context.validate())
        # and resolved when a recipe is elaborated, so a block may include one
        # that is defined later, and whether an included recipe has been run is
        # decided at run time.
        context.blocks[self.name] = self
        logging.debug(
            "Registered block '%s' (top=%s, %d RTL files, %d includes)",
            self.name, self.top or "<none>", len(self.rtl_files), len(self.includes),
        )


class EnvSpec(BaseModel):
    model_config = ConfigDict(validate_default=True, extra="forbid")

    name: str = ""
    desc: str = ""
    includes: list[str] = Field(default_factory=list)
    target: str = ""
    vrf_top: str = ""
    vrf_files: list[str] = Field(default_factory=list)
    vrf_incdirs: list[str] = Field(default_factory=list)
    vrf_libs: list[str] = Field(default_factory=list)
    vrf_options: dict = Field(default_factory=dict)
    vrf_defines: list[str] = Field(default_factory=list)

    _lists = field_validator("includes", "vrf_files", "vrf_incdirs", "vrf_libs", "vrf_defines",
                             mode="before")(_as_list)
    vrf_framework: str = ""
    vrf_framework_top: str = ""
    default_sim: str = ""
    is_test: bool = False

    @functools.cached_property
    def resolved_libs(self):
        libs = []
        for n in self.vrf_libs:
            if n in context.libs:
                spec = context.libs[n]
            elif n in context.blocks:
                spec = context.blocks[n]
            else:
                raise BakeManifestError(f"Library {n} not defined")
            libs.append(spec)
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
            if context.test_exists(self.name, self.target):
                raise BakeManifestError(
                    f"Redefinition of test {self.name} for block {self.target} detected"
                )
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

