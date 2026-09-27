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
import inspect
import logging
from abc import abstractmethod
import os
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import loader
from . import file_utils
from .context import context
from .exceptions import BakeManifestError
from .step import LibData, RtlData, StepData


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
    manifest_function: ClassVar[str] = "flow"

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


class AbstractsSpec(BaseModel):
    """The files an implemented design is used through: a netlist to simulate
    it, and the abstracts (Liberty and SI per corner, LEF) to implement a
    design around it. Declared the same way for a cell library, lib(), and
    for an implemented block, macro(); only the role differs."""
    model_config = ConfigDict(validate_default=True, extra="forbid")

    netlist_files: list[str] = Field(default_factory=list)
    netlist_incdirs: list[str] = Field(default_factory=list)
    liberty_files: dict[str, list[str]] = Field(default_factory=dict)   # {corner: [files]}
    si_files: dict[str, list[str]] = Field(default_factory=dict)        # {corner: [files]}
    layout_info: str = ""

    _abstract_lists = field_validator("netlist_files", "netlist_incdirs", mode="before")(_as_list)
    _corner_dicts = field_validator("liberty_files", "si_files", mode="before")(_as_corner_dict)

    def _resolve_abstracts(self, owner: str) -> None:
        """Make the paths absolute; the cwd is the manifest's directory."""
        file_utils.resolve_file_list(self.netlist_files)
        file_utils.resolve_dir_list(self.netlist_incdirs)
        if self.layout_info:
            self.layout_info = _resolve_layout_info(self.layout_info, owner)
        for corner_dict in (self.liberty_files, self.si_files):
            for corner_files in corner_dict.values():
                file_utils.resolve_file_list(corner_files)


class LibSpec(AbstractsSpec):
    """A cell library (standard cells, IO cells, a PDK's technology files):
    what blocks are mapped onto, named by libs=, vrf_libs= and
    config.bake.default_libs. Not a design: it has no top and is not a
    target; an implemented block of the project is a macro()."""
    manifest_function: ClassVar[str] = "lib"

    name: str = ""
    desc: str = ""

    def model_post_init(self, __context: Any) -> None:
        if self.name in context.libs:
            raise BakeManifestError(f"Redefinition of library {self.name} detected")

        self._resolve_abstracts(f"Library '{self.name}'")

        context.libs[self.name] = self
        logging.debug(
            "Registered library '%s' (%d netlist files, %d liberty corners, %d SI corners)",
            self.name,
            len(self.netlist_files),
            len(self.liberty_files),
            len(self.si_files),
        )


def _named_libs(names: list[str], owner: str) -> list:
    """The cell libraries called `names`, for `owner`'s libs=."""
    libs = []
    for n in names:
        if n in context.libs:
            libs.append(context.libs[n])
        elif isinstance(context.blocks.get(n), MacroSpec):
            raise BakeManifestError(
                f"{owner}: libs= names '{n}', which is a macro(), not a cell library. "
                f"Include it instead: includes=[\"{n}\"]."
            )
        else:
            raise BakeManifestError(f"Library {n} not defined")
    return libs


class DesignSpec(BaseModel):
    """What a recipe runs on: a named design, registered in context.blocks.

    block() declares one in RTL and macro() an implemented block; a manifest
    may define other kinds of design by subclassing this (rdl2verilog's
    rdl() does).
    A subclass adds its own fields and says which StepData kind a recipe on
    it starts from (data_type) and how to build that data from its fields
    (to_data()). Includes, tests and the registration are common: every
    kind of design is a block to the command line and to includes.
    """
    model_config = ConfigDict(validate_default=True, extra="forbid")

    # The manifest function that declares this kind of design, for messages.
    manifest_function: ClassVar[str] = ""

    name: str = ""
    desc: str = ""
    includes: dict = Field(default_factory=dict)   # {block_name: recipe_str}
    dir: str = ""

    @field_validator("includes", mode="before")
    @classmethod
    def coerce_includes(cls, v):
        # Convenience: a plain list of block names is treated as {name: "rtl"}:
        # the included block's own data, whatever its kind. The dict form
        # allows specifying a recipe (e.g. {name: "tmr-impl"}).
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

    @property
    @abstractmethod
    def data_type(self) -> type[StepData]:
        """The kind of StepData a recipe on this design starts from."""

    @abstractmethod
    def to_data(self):
        """This design's own working state, of kind data_type (includes and
        test excluded; see StepData.create()), as copies: a step cannot
        alter the design."""

    @property
    def is_empty(self) -> bool:
        """Declares nothing to run a recipe on (such a block is not listed)."""
        return False

    def _resolve(self) -> None:
        """Check the kind's own fields and make its paths absolute; the cwd
        is the manifest's directory."""

    def _summary(self) -> str:
        """What the debug log says about the design once registered."""
        return f"{len(self.includes)} includes"

    def model_post_init(self, __context: Any) -> None:
        if self.name in context.blocks:
            raise BakeManifestError(f"Redefinition of block {self.name} detected")
        self.dir = str(Path.cwd())
        self._resolve()
        # Includes are checked once every manifest has loaded (context.validate())
        # and resolved when a recipe is elaborated, so a block may include one
        # that is defined later, and whether an included recipe has been run is
        # decided at run time.
        context.blocks[self.name] = self
        logging.debug("Registered %s block '%s' (%s)", self.data_type.kind, self.name, self._summary())


class BlockSpec(DesignSpec):
    """A design in RTL."""
    manifest_function: ClassVar[str] = "block"

    # RTL step
    top: str = ""
    rtl_files: list[str] = Field(default_factory=list)
    rtl_incdirs: list[str] = Field(default_factory=list)

    # Pipeline step files
    sdc_files: list[str] = Field(default_factory=list)                  # design constraints
    vcd_files: dict[str, list[str]] = Field(default_factory=dict)       # value change dump {corner: [files]}
    saif_files: dict[str, list[str]] = Field(default_factory=dict)      # switching activity {corner: [files]}

    # PDK cell library dependencies (LibSpec names)
    libs: list[str] = Field(default_factory=list)

    _lists = field_validator("rtl_files", "rtl_incdirs", "sdc_files", "libs", mode="before")(_as_list)

    # What an implemented block declares; block() takes RTL only.
    _MACRO_FIELDS: ClassVar[tuple] = tuple(AbstractsSpec.model_fields)

    @model_validator(mode="before")
    @classmethod
    def reject_removed_fields(cls, values):
        if not isinstance(values, dict):
            return values
        if "skip_on_include_errors" in values:
            raise BakeManifestError(
                "skip_on_include_errors has been removed: includes are resolved when a "
                "recipe runs and dependencies are built on demand. Remove the argument."
            )
        macro_fields = [f for f in cls._MACRO_FIELDS if f in values]
        if macro_fields:
            raise BakeManifestError(
                f"Block '{values.get('name', '')}': {', '.join(macro_fields)} "
                f"{'is' if len(macro_fields) == 1 else 'are'} not a block() argument: block() "
                f"declares RTL. Declare an implemented block with macro() and include it."
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

    @functools.cached_property
    def resolved_libs(self):
        return _named_libs(self.libs, f"Block '{self.name}'")

    @property
    def is_empty(self) -> bool:
        return not (self.rtl_files or self.includes)

    @property
    def data_type(self) -> type[StepData]:
        return RtlData

    def to_data(self):
        return RtlData(
            block=self.name, block_dir=self.dir, top=self.top,
            rtl_files=list(self.rtl_files),
            rtl_incdirs=list(self.rtl_incdirs),
            libs=StepData._block_libs(self),
            sdc_files=list(self.sdc_files),
            vcd_files={k: list(v) for k, v in self.vcd_files.items()},
            saif_files={k: list(v) for k, v in self.saif_files.items()},
        )

    def _resolve(self) -> None:
        file_utils.resolve_file_list(self.rtl_files)
        file_utils.resolve_dir_list(self.rtl_incdirs)
        file_utils.resolve_file_list(self.sdc_files)
        for corner_dict in (self.vcd_files, self.saif_files):
            for corner_files in corner_dict.values():
                file_utils.resolve_file_list(corner_files)

    def _summary(self) -> str:
        return f"top={self.top or '<none>'}, {len(self.rtl_files)} RTL files, {len(self.includes)} includes"


class MacroSpec(DesignSpec, AbstractsSpec):
    """An implemented block (a hard macro): declared by its netlist and
    abstracts, like a lib(), but a design. A recipe on it starts from lib
    data, so vrf simulates its netlist; an RTL block including it gets it as
    a macro, which impl places from its abstracts."""
    manifest_function: ClassVar[str] = "macro"

    top: str = ""
    # The cell libraries its netlist is mapped to (LibSpec names)
    libs: list[str] = Field(default_factory=list)

    _lists = field_validator("libs", mode="before")(_as_list)

    @functools.cached_property
    def resolved_libs(self):
        return _named_libs(self.libs, f"Macro '{self.name}'")

    @property
    def is_empty(self) -> bool:
        return not (self.netlist_files or self.layout_info or self.liberty_files or self.includes)

    @property
    def data_type(self) -> type[StepData]:
        return LibData

    def to_data(self):
        return LibData(
            block=self.name, block_dir=self.dir, top=self.top,
            netlist_files=list(self.netlist_files),
            netlist_incdirs=list(self.netlist_incdirs),
            liberty_files={k: list(v) for k, v in self.liberty_files.items()},
            si_files={k: list(v) for k, v in self.si_files.items()},
            layout_info=self.layout_info,
            libs=StepData._block_libs(self),
        )

    def _resolve(self) -> None:
        self._resolve_abstracts(f"Macro '{self.name}'")

    def _summary(self) -> str:
        return (f"top={self.top or '<none>'}, {len(self.netlist_files)} netlist files, "
                f"{len(self.liberty_files)} liberty corners")


class EnvSpec(BaseModel):
    model_config = ConfigDict(validate_default=True, extra="forbid")
    manifest_function: ClassVar[str] = "env"

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
    # Pass/fail criteria on the simulation log, besides the exit code: a
    # line matching vrf_fail_regex fails the test; with vrf_pass_regex set,
    # so does a log with no line matching it.
    vrf_pass_regex: str = ""
    vrf_fail_regex: str = ""
    is_test: bool = False

    @functools.cached_property
    def resolved_libs(self):
        libs = []
        for n in self.vrf_libs:
            if n in context.libs:
                spec = context.libs[n]
            elif n in context.blocks:
                spec = context.blocks[n]
                if not isinstance(spec, MacroSpec):
                    raise BakeManifestError(
                        f"vrf_libs: '{n}' is a block of kind {spec.data_type.kind}, not a library. "
                        f"Name a lib() or a macro()."
                    )
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
    manifest_function: ClassVar[str] = "test"
    is_test: bool = True


def spec_class(name: str):
    """The spec class called `name` (a pydantic error's title), specs that
    manifests define (DesignSpec subclasses) included; None if there is none."""
    todo: list = [FlowSpec, LibSpec, DesignSpec, EnvSpec]
    while todo:
        cls = todo.pop()
        if cls.__name__ == name:
            return cls
        todo.extend(cls.__subclasses__())
    return None


flow  = FlowSpec
lib   = LibSpec    # PDK cell libraries
block = BlockSpec  # user design blocks, in RTL
macro = MacroSpec  # implemented blocks (hard macros)


def target(**kwargs):
    """Deprecated alias of block(), from tmake; to be removed in 2.0.0."""
    caller = inspect.stack()[1]
    where = f"{loader.display_path(caller.filename)}:{caller.lineno}"
    logging.warning("%s: target() is deprecated and will be removed in bake 2.0.0; use block()", where)
    return BlockSpec(**kwargs)
env   = EnvSpec
test  = TestSpec

