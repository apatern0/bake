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

"""Step base class, shared utilities, and recipe orchestration.

Any Step subclass with a `name` registers itself in context.steps when its
class body is executed, so a step is defined by manifest code: the built-in
ones live in `bake/builtin/<name>/manifest`, a project's own in any manifest
it load()s (or in the project manifest itself).

A recipe string such as "tmr-impl-vrf" is split on "-" into the ordered list
of step names ["tmr", "impl", "vrf"].  Recipe.elaborate() instantiates the
steps, threads a StepData through them, and records the dependency recipes
that the block's recipe-form includes require.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import os
from pathlib import Path
import shutil
import signal
import string
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from . import exceptions
from .context import context


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class RecipePath(list):
    def __str__(self):
        return "-".join(self)


# ---------------------------------------------------------------------------
# Step data
# ---------------------------------------------------------------------------

@dataclass
class StepData:
    """Pipeline state threaded through every step in a recipe.

    Three identity fields say which block, manifest directory and test the
    recipe runs for; they never change along the chain.  All other fields are
    the *current* working state: initialised from the manifest objects by
    create() and freely modifiable by steps.  No manifest object is kept
    here — a step cannot reach back into the BlockSpec/EnvSpec, so nothing a
    step does can corrupt the registered manifest.

    Attributes
    ----------
    block, block_dir, test
        Block name, directory of the manifest that defined it, and the name of
        the test the recipe runs with ("" when none is needed).

    top, rtl_files, rtl_incdirs, libs
        Block-derived working state.  TmrStep renames `top` and replaces
        `rtl_files`; ImplStep replaces the RTL with its netlist.

    vrf_top … default_sim
        Test-derived working state.  VrfStep consumes these; a user step
        may transform them before vrf runs.

    recipe_prefix, is_last
        Bookkeeping set by the Recipe orchestrator: the steps executed before
        this one, and whether this step is the last in the recipe.
    """

    # ── Identity ─────────────────────────────────────────────────────────────
    block:     str = ""
    block_dir: str = ""
    test:      str = ""

    # ── Mutable block-derived working state ──────────────────────────────────
    top:         str  = ""
    rtl_files:   list = field(default_factory=list)  # list[str] absolute paths
    rtl_incdirs: list = field(default_factory=list)
    libs:        list = field(default_factory=list)  # list[LibSpec], resolved

    # ── Mutable test-derived working state ───────────────────────────────────
    vrf_top:           str  = ""
    vrf_files:         list = field(default_factory=list)  # list[str]
    vrf_incdirs:       list = field(default_factory=list)
    vrf_libs:          list = field(default_factory=list)  # list[LibSpec], resolved
    vrf_defines:       list = field(default_factory=list)
    vrf_options:       dict = field(default_factory=dict)
    vrf_framework:     str  = ""
    vrf_framework_top: str  = ""
    default_sim:       str  = ""

    # ── Gate-level / lib fields (from BlockSpec or an impl step) ─────────────
    netlist_files:   list = field(default_factory=list)   # gate-level Verilog
    netlist_incdirs: list = field(default_factory=list)   # gate-level include dirs
    liberty_files:   dict = field(default_factory=dict)   # {corner: [files]}
    si_files:        dict = field(default_factory=dict)   # {corner: [files]}
    layout_info:     str  = ""

    # ── Constraint and activity files ────────────────────────────────────────
    sdf_files:    dict = field(default_factory=dict)   # annotated delays {corner: file}
    sdc_files:    list = field(default_factory=list)   # design constraints
    vcd_files:    dict = field(default_factory=dict)   # value change dump {corner: [files]}
    saif_files:   dict = field(default_factory=dict)   # switching activity {corner: [files]}

    # ── Bookkeeping ──────────────────────────────────────────────────────────
    recipe_prefix: RecipePath = field(default_factory=RecipePath)
    is_last:       bool       = False

    def copy(self) -> "StepData":
        """Return a copy whose lists and dicts are independent of this one.

        Containers are copied one level deep (lists inside the corner dicts
        included) so that a step appending to its output data cannot alter
        the data of the steps before it."""
        changes = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if isinstance(value, RecipePath):
                changes[f.name] = RecipePath(value)
            elif isinstance(value, list):
                changes[f.name] = list(value)
            elif isinstance(value, dict):
                changes[f.name] = {
                    k: list(v) if isinstance(v, list) else v for k, v in value.items()
                }
        return dataclasses.replace(self, **changes)

    def extend(self, data: StepData):
        """Merge `data` (an included env or block) into this working state."""

        def list_inherit(child, parent):
            """Merge child list into parent list, preserving order and suppressing duplicates.

            Parent elements appear first; child elements are appended only if not
            already present in the merged list.  This ordering means that files
            declared in an included env/block take lower precedence than those
            declared directly on the inheriting block.
            """
            merged_list = parent.copy()
            for child_elem in child:
                if child_elem not in merged_list:
                    merged_list.append(child_elem)
            return merged_list

        def dict_inherit(child, parent):
            """Merge dicts key by key: list values merge like lists, any other
            value keeps the child's when set and takes the parent's otherwise."""
            child = child.copy()
            for opt_k, opt_v in parent.items():
                if opt_k not in child:
                    child[opt_k] = list(opt_v) if isinstance(opt_v, list) else opt_v
                elif isinstance(opt_v, list) and isinstance(child[opt_k], list):
                    child[opt_k] = list_inherit(child[opt_k], opt_v)
                elif not child[opt_k]:
                    child[opt_k] = opt_v
            return child

        str_extend = [
            "vrf_top", "vrf_framework", "vrf_framework_top",
            "default_sim",
        ]

        list_extend = [
            "rtl_files", "rtl_incdirs", "libs", "vrf_files", "vrf_incdirs",
            "vrf_libs", "vrf_defines", "netlist_files", "netlist_incdirs",
            "sdc_files"]

        dict_extend = [
            "vrf_options", "liberty_files", "si_files",
            "sdf_files", "vcd_files", "saif_files"
        ]

        for attr in str_extend:
            setattr(self, attr, getattr(self, attr) or getattr(data, attr))

        for attr in list_extend:
            setattr(self, attr, list_inherit(getattr(self, attr), getattr(data, attr)))

        for attr in dict_extend:
            setattr(self, attr, dict_inherit(getattr(self, attr), getattr(data, attr)))

        # layout_info is a space-separated file list (LEF files); an included
        # block's abstracts add to the block's own.
        self.layout_info = " ".join(list_inherit(self.layout_info.split(), data.layout_info.split()))

    def _process_env_includes(self, env):
        for dep_name in env.includes:
            logging.debug(
                "Processing env include '%s' for test '%s'",
                dep_name, env.name,
            )
            if dep_name not in context.envs:
                raise exceptions.BakeIncludeError(
                    f"Include {dep_name}: env not found"
                )

            data = StepData.create(env=context.envs[dep_name])
            self.extend(data)

    def _process_block_includes(self, block, dependencies, visiting):
        for dep_name, dep_recipe_str in block.includes.items():
            logging.debug(
                "Processing block include '%s' (recipe='%s') for block '%s'",
                dep_name, dep_recipe_str, block.name,
            )
            if dep_name not in context.blocks:
                raise exceptions.BakeIncludeError(
                    f"Include {dep_name}: block not found"
                )
            if dep_name in visiting:
                cycle = " -> ".join(list(visiting) + [dep_name])
                raise exceptions.BakeManifestError(f"Include cycle detected: {cycle}")

            if dep_recipe_str == "rtl":
                # RTL include: pull in source files directly, no step outputs needed.
                data = StepData.create(
                    block=context.blocks[dep_name],
                    dependencies=dependencies,
                    _visiting=visiting,
                )
            else:
                # Recipe include: the dependency's outputs stand in for its
                # RTL.  Elaboration does not require them to exist; whether
                # they are missing or stale is decided when the recipe runs,
                # and the dependency is built first (see cli.run).
                dep_recipe = Recipe(dep_name, dep_recipe_str)
                dep_recipe.elaborate(_visiting=visiting)
                dependencies.append(dep_recipe)
                data = dep_recipe.last_step.output_data
                logging.debug(
                    "Include '%s/%s' resolved to outputdir: %s",
                    dep_name, dep_recipe_str, dep_recipe.last_step.outputdir,
                )

            self.extend(data)

    @staticmethod
    def create(block: Optional["BlockSpec"] = None, env: Optional["EnvSpec"] = None,
               dependencies: Optional[list] = None, _visiting: tuple = ()):
        """Build the initial working state from a block and/or test.

        Recipe-form includes are elaborated and appended to `dependencies`
        (a list of Recipe objects) so that the caller can build them first.
        """
        if dependencies is None:
            dependencies = []

        obj = StepData(
            block     = block.name if block else "",
            block_dir = block.dir if block else "",
            test      = env.name if env else "",

            # block-derived working state
            top         = block.top if block else "",
            rtl_files   = list(block.rtl_files) if block else [],
            rtl_incdirs = list(block.rtl_incdirs) if block else [],
            libs        = list(block.resolved_libs) if block else [],
            netlist_files   = list(block.netlist_files) if block else [],
            netlist_incdirs = list(block.netlist_incdirs) if block else [],
            liberty_files   = {k: list(v) for k, v in block.liberty_files.items()} if block else {},
            si_files    = {k: list(v) for k, v in block.si_files.items()} if block else {},
            layout_info = block.layout_info if block else "",
            sdc_files   = list(block.sdc_files) if block else [],
            vcd_files   = dict(block.vcd_files) if block else {},
            saif_files  = {k: list(v) for k, v in block.saif_files.items()} if block else {},

            # env-derived working state
            vrf_top           = env.vrf_top if env else "",
            vrf_files         = list(env.vrf_files) if env else [],
            vrf_incdirs       = list(env.vrf_incdirs) if env else [],
            vrf_libs          = list(env.resolved_libs) if env else [],
            vrf_defines       = list(env.vrf_defines) if env else [],
            vrf_options       = {k: list(v) if isinstance(v, list) else v
                                 for k, v in env.vrf_options.items()} if env else {},
            vrf_framework     = env.vrf_framework if env else "",
            vrf_framework_top = env.vrf_framework_top if env else "",
            default_sim       = env.default_sim if env else ""
        )

        if env:
            obj._process_env_includes(env)
        if block:
            obj._process_block_includes(block, dependencies, _visiting + (block.name,))

        return obj

    @staticmethod
    def create_from_env(env: "EnvSpec"):
        return StepData.create(env=env)

    @staticmethod
    def create_from_block(block: "BlockSpec"):
        return StepData.create(block=block)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class Step(ABC):
    """Abstract base class for all bake steps.

    Subclasses must declare:
        name  -- short identifier used in recipe names, e.g. "vrf"

    All block and test data is available via self.data (StepData).
    Step methods must not access context registries (context.libs,
    context.blocks, context.tests) — only self.data and self.config.
    """

    name: str
    default_flow = None
    require_test = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        step_name = getattr(cls, 'name', None)
        if step_name:
            if '-' in step_name:
                raise ValueError(
                    f"Step name '{step_name}' must not contain hyphens "
                    f"(hyphens are the recipe separator, e.g. 'tmr-impl-vrf')."
                )
            context.steps[step_name] = cls
            logging.debug("Registered step '%s' (%s)", step_name, cls.__name__)

    def __init__(self, data: StepData):
        self.data = data
        self.__flow = None

    @property
    def flow(self):
        if self.__flow:
            return self.__flow

        flow_name = getattr(self.config, 'flow', None)
        if flow_name and flow_name in context.flows:
            return context.flows[flow_name]

        flow_name = getattr(self, 'default_flow', None)
        if flow_name and flow_name in context.flows:
            return context.flows[flow_name]

        raise exceptions.BakeInternalError(
            f"No valid default_flow ('{flow_name}') provided for step '{self.name}'."
        )

    @flow.setter
    def flow(self, value):
        self.__flow = value

    @property
    def recipe_path(self):
        return str(self.data.recipe_prefix) + ("-" if self.data.recipe_prefix else "") + self.name

    def check_pre(self) -> None:
        """Verify that this step can consume self.data.

        Called during recipe elaboration, before anything runs.  Raise a
        BakeRuntimeError (or subclass) describing what is missing or
        unsupported; the message is shown to the user as the reason the
        block/recipe combination cannot run.
        """

    def check_post(self):
        """Verify that expected output files were produced."""
        missing = [f for f in self.output_files if not Path(f).is_file()]
        if missing:
            missing_str = "\n".join("   -" + f for f in missing)
            raise exceptions.BakeRuntimeError(
                f"Step {self.recipe_path} for block {self.data.block} "
                f"did not produce all required files:\n{missing_str}"
            )
        if self.output_files:
            logging.debug(
                "Step '%s' post-check passed (%d output files verified)",
                self.recipe_path, len(self.output_files),
            )

    def clean(self) -> None:
        """Remove the work directory for this step."""
        if self.workdir.is_dir():
            logging.info("Cleaning work directory: %s", self.workdir)
            shutil.rmtree(self.workdir)
        else:
            logging.debug("Work directory does not exist, nothing to clean: %s", self.workdir)

    @property
    @abstractmethod
    def source_files(self):
        """List of source files consumed by this step."""

    @property
    @abstractmethod
    def output_files(self):
        """List of output files produced by this step."""

    def is_available(self) -> bool:
        try:
            return self.flow is not None
        except exceptions.BakeRuntimeError:
            return False

    @property
    def config(self):
        return getattr(context.config, self.name)

    @property
    def flowdir(self) -> Path:
        return Path(self.data.block_dir) / "flow" / self.data.block / self.recipe_path

    @property
    def workdir(self) -> Path:
        if context.config.bake.output_dir:
            return Path(context.config.bake.output_dir) / self.data.block / self.recipe_path

        return Path(self.data.block_dir) / "work" / self.data.block / self.recipe_path

    @property
    def outputdir(self) -> Path:
        return self.workdir / "output"

    def run_required(self, log: bool = True) -> bool:
        """Return True if step execution is needed.

        Uses ctime (inode change time) rather than mtime so that link
        retargeting and permission changes also trigger a re-run.  With
        log=False nothing is reported (used by listings and dry runs).
        """

        def info(msg, *args):
            if log:
                logging.info(msg, *args)

        def log_first_five(files):
            for f in files[:5]:
                info("   - %s", f)
            if len(files) > 5:
                info("   - …")

        if not self.output_files:
            logging.debug("Step '%s' declares no output files; will always run.", self.name)
            return True  # step produces no trackable output; always execute

        output_missing = [f for f in self.output_files if not Path(f).is_file()]
        if output_missing:
            info("Expected output files missing for step '%s':", self.name)
            log_first_five(output_missing)
            return True

        in_files  = [f for f in self.source_files if not Path(f).is_symlink()]
        out_files = [f for f in self.output_files if not Path(f).is_symlink()]

        if self.source_files and not in_files:
            raise exceptions.BakeRuntimeError(
                "All input files are symlinks — cannot reliably check modification dates."
            )
        if not out_files:
            if log:
                logging.warning(
                    "All output files for step '%s' are symlinks — treating as up-to-date.",
                    self.name,
                )
            return False

        oldest_out  = min(out_files, key=lambda f: Path(f).stat().st_ctime)
        oldest_time = datetime.datetime.fromtimestamp(Path(oldest_out).stat().st_ctime)
        newer_files = [f for f in in_files if Path(f).stat().st_ctime > Path(oldest_out).stat().st_ctime]
        if newer_files:
            info(
                "Source files are newer than oldest output '%s' (modified %s) for step '%s':",
                Path(oldest_out).name, oldest_time.strftime("%Y-%m-%d %H:%M:%S"), self.name,
            )
            log_first_five(newer_files)
            return True

        logging.debug(
            "Step '%s' outputs are up-to-date (oldest output: %s, modified %s)",
            self.name, Path(oldest_out).name, oldest_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return False

    def run(self, force: Optional[bool] = None):
        """Execute the step unless its outputs are up to date.

        `force` defaults to the -f flag; cli.run passes False for dependency
        recipes so that -f only applies to the block the user asked for."""
        if force is None:
            force = context.config.bake.force
        if force:
            logging.info("Force flag set — running step '%s' unconditionally.", self.name)
        elif not self.run_required():
            logging.info("Output files are up-to-date, skipping step %s.", self.name)
            return
        self.copy_and_template()
        self.execute_flow_step()

    def build_tpl_dict(self) -> dict:
        """Template variables available to every flow.

        Combines config.bake.tpl_dict, the step's own config.<step>.tpl_dict,
        the block/recipe identity, and the flow options: the flow's
        tpl_defaults overlaid with config.<step>.flow_options, exposed as
        $BAKE_FLOW_OPT_<NAME> (name upper-cased, lists space-joined).  A dict
        option expands to one variable per key, $BAKE_FLOW_OPT_<NAME>_<KEY>,
        and an override merges into the flow's default dict key by key so
        that every key the flow declares stays defined.
        """
        tpl_dict = dict(context.config.bake.tpl_dict)
        tpl_dict.update(getattr(self.config, "tpl_dict", None) or {})

        tpl_dict["BAKE_INTERACTIVE"] = int(context.config.bake.interactive)
        tpl_dict["BAKE_VERBOSITY"]   = context.config.bake.verbosity
        tpl_dict["BAKE_TOP"]         = self.data.top
        tpl_dict["BAKE_BLOCK"]       = self.data.block
        tpl_dict["BAKE_RECIPE"]      = str(self.data.recipe_prefix)

        def as_string(value):
            if isinstance(value, (list, tuple)):
                return " ".join(str(v) for v in value)
            return value

        flow_options = dict(self.flow.tpl_defaults)
        for opt_name, opt_val in (getattr(self.config, "flow_options", None) or {}).items():
            if isinstance(opt_val, dict) and isinstance(flow_options.get(opt_name), dict):
                flow_options[opt_name] = {**flow_options[opt_name], **opt_val}
            else:
                flow_options[opt_name] = opt_val
        for opt_name, opt_val in flow_options.items():
            if isinstance(opt_val, dict):
                for key, val in opt_val.items():
                    tpl_dict[f"BAKE_FLOW_OPT_{opt_name.upper()}_{key.upper()}"] = as_string(val)
            else:
                tpl_dict[f"BAKE_FLOW_OPT_{opt_name.upper()}"] = as_string(opt_val)

        return tpl_dict

    # ---------------------------------------------------------------------------
    # File operations
    # ---------------------------------------------------------------------------

    def copy_and_template(self):
        """Copy the flow directory tree into workdir, expanding *.tpl files."""
        copy_method_map = {"copy": shutil.copyfile, "symlink": os.symlink}
        copy_method_key = context.config.bake.file_copy_method
        if copy_method_key not in copy_method_map:
            raise exceptions.BakeConfigError(
                "Invalid file copy method specified, check bake.file_copy_method"
            )
        copy_method = copy_method_map[copy_method_key]

        self.workdir.mkdir(parents=True, exist_ok=True)
        logging.debug(
            "Expanding flow directory '%s' → workdir '%s' (method=%s)",
            self.flowdir, self.workdir, copy_method_key,
        )

        tpl_dict = self.build_tpl_dict()

        for current_dir_src, subdirs, files in os.walk(self.flowdir):
            current_dir_src = Path(current_dir_src)
            current_dir_dest = self.workdir / current_dir_src.relative_to(self.flowdir)
            for subdir in subdirs:
                (current_dir_dest / subdir).mkdir(exist_ok=True)
            for subfile in files:
                subfile_src = current_dir_src / subfile
                if subfile_src.suffix == ".tpl":
                    subfile_dest = current_dir_dest / subfile_src.stem
                    logging.debug("Expanding template: %s → %s", subfile_src.name, subfile_dest.name)
                    with open(subfile_src, "r", encoding="utf-8") as f_in, \
                         open(subfile_dest, "w", encoding="utf-8") as f_out:
                        template = string.Template(f_in.read())
                        try:
                            f_out.write(template.substitute(tpl_dict))
                        except KeyError as err:
                            raise exceptions.BakeConfigError(
                                f"{subfile_src}: template variable {err} is undefined."
                            ) from err
                        except ValueError as err:
                            raise exceptions.BakeConfigError(f"{subfile_src}: {err}") from err
                    shutil.copymode(subfile_src, subfile_dest)
                else:
                    subfile_dest = current_dir_dest / subfile
                    if subfile_dest.exists() or subfile_dest.is_symlink():
                        subfile_dest.unlink()
                    copy_method(subfile_src, subfile_dest)

    def copy_flow_tree(self):
        """Copy flow step files into the flow directory for the current step."""
        if self.flowdir.exists():
            logging.debug(
                "Flow directory for step '%s' already exists: %s",
                self.recipe_path, self.flowdir,
            )
            return

        logging.info(
            "Populating flow directory for '%s' from '%s' → %s",
            self.recipe_path, self.flow.dir, self.flowdir,
        )
        shutil.copytree(self.flow.dir, self.flowdir)

    def execute_flow_step(self):
        """Execute the flow step entry point inside the correct directory."""
        proc = None
        start_time = time.monotonic()
        heartbeat_stop = threading.Event()

        def heartbeat():
            # Suppress periodic progress messages when running interactively;
            # the user is already watching the tool's own output.
            if context.config.bake.interactive:
                return
            while not heartbeat_stop.wait(60):
                elapsed = time.monotonic() - start_time
                logging.info("Step %s still running — %s elapsed", self.name, _fmt_elapsed(elapsed))

        def handle_signal(signum, _frame):
            if proc is not None:
                logging.info(
                    "Received %s, forwarding to flow step script.",
                    signal.Signals(signum).name,
                )
                try:
                    os.killpg(os.getpgid(proc.pid), signum)
                except ProcessLookupError:
                    pass

        run_cmd        = self.flow.run_cmd
        run_cmd_path   = Path(run_cmd)
        run_dir        = self.workdir / run_cmd_path.parent
        run_executable = run_cmd_path.name

        logging.debug(
            "Executing step '%s': ./%s (cwd=%s)",
            self.recipe_path, run_executable, run_dir,
        )

        backup_sigterm = signal.getsignal(signal.SIGTERM)
        backup_sigint  = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT,  handle_signal)
        try:
            with subprocess.Popen("./" + run_executable, shell=True, cwd=run_dir,
                                  start_new_session=True) as proc:
                heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
                heartbeat_thread.start()
                try:
                    proc.wait()
                finally:
                    heartbeat_stop.set()
                    heartbeat_thread.join()
        finally:
            signal.signal(signal.SIGTERM, backup_sigterm)
            signal.signal(signal.SIGINT, backup_sigint)

        elapsed = _fmt_elapsed(time.monotonic() - start_time)
        if proc.returncode:
            logging.error(
                "Step '%s' failed with return code %d after %s",
                self.recipe_path, proc.returncode, elapsed,
            )
            raise exceptions.BakeStepExecutionError(
                f"Non-zero return code while executing {run_dir / run_cmd}."
            )

        logging.info("Step %s completed in %s", self.name, elapsed)

    @property
    def output_data(self):
        data = self.data.copy()
        data.recipe_prefix = RecipePath(list(self.data.recipe_prefix) + [self.name])
        return data


# ---------------------------------------------------------------------------
# Main orchestration entry point
# ---------------------------------------------------------------------------

class Recipe:
    """An ordered series of steps applied to one block.

    After elaborate(), `steps` holds the instantiated Step objects, `data` the
    StepData before and after each of them, and `dependencies` the Recipe
    objects that the block's recipe-form includes require (direct ones; each
    carries its own dependencies in turn).
    """

    def __init__(self, block_name, recipe):
        self.block_name   = block_name
        self.recipe       = recipe.split("-")
        self.steps        = []
        self.data         = []
        self.dependencies = []

    @property
    def key(self):
        return (self.block_name, "-".join(self.recipe))

    @property
    def last_step(self):
        return self.steps[-1] if self.steps else None

    def all_dependencies(self) -> list:
        """Every dependency recipe, transitively, in build order and without
        duplicates (the same block/recipe reached twice is listed once)."""
        ordered, seen = [], set()

        def visit(recipe):
            for dep in recipe.dependencies:
                visit(dep)
                if dep.key not in seen:
                    seen.add(dep.key)
                    ordered.append(dep)

        visit(self)
        return ordered

    def elaborate(self, resolve_test=False, _visiting: tuple = ()):
        if self.block_name not in context.blocks:
            raise exceptions.BakeRuntimeError(
                f"Block '{self.block_name}' not defined."
            )

        # Resolve block
        block = context.blocks[self.block_name]
        logging.debug("Elaborating recipe '%s' for block '%s'", "-".join(self.recipe), block.name)

        # Validate all step names before any further elaboration so unknown
        # steps surface as a clean BakeRuntimeError instead of a raw KeyError.
        for step_name in self.recipe:
            if step_name not in context.steps:
                raise exceptions.BakeRuntimeError(
                    f"Cannot parse recipe '{'-'.join(self.recipe)}': unknown step '{step_name}'. "
                    f"Available steps: {list(context.steps.keys())}"
                )

        # Resolve test — use CLI selection or auto-select when only one exists.
        test = None
        if resolve_test:
            require_test = any(context.steps[s].require_test for s in self.recipe)
            if require_test:
                if context.config.bake.test:
                    test = context.find_test(context.config.bake.test, block.name)
                    if test is None:
                        raise exceptions.BakeRuntimeError(
                            f"No such test: {context.config.bake.test} (block '{block.name}')"
                        )
                    logging.debug("Using explicitly selected test '%s'", test.name)
                elif len(block.available_tests) == 1:
                    test = context.find_test(block.available_tests[0], block.name)
                    logging.info("Auto-selecting test '%s' (only test for block '%s')", test.name, block.name)
                elif not block.available_tests:
                    raise exceptions.BakeManifestError(
                        f"Block '{block.name}' has no tests; the recipe "
                        f"'{'-'.join(self.recipe)}' needs one. Add a test() for it."
                    )
                else:
                    raise exceptions.BakeManifestError(
                        f"Block '{block.name}' has multiple tests: {block.available_tests}. "
                        f"Use -t <testname> to select one."
                    )
            else:
                logging.debug("No test required for recipe '%s'", "-".join(self.recipe))

        # Create initial StepData; recipe-form includes are elaborated here
        # and recorded as dependencies.
        self.steps        = []
        self.data         = []
        self.dependencies = []
        running_data = StepData.create(
            block=block, env=test, dependencies=self.dependencies, _visiting=_visiting,
        )
        self.data.append(running_data)

        for i, step_name in enumerate(self.recipe):
            running_data.is_last = (i == len(self.recipe) - 1)

            step = context.steps[step_name](running_data)
            logging.debug(
                "Elaborated step '%s' [%d/%d] for block '%s'",
                step_name, i + 1, len(self.recipe), block.name,
            )

            if not step.is_available():
                raise exceptions.BakeRuntimeError(
                    f"Step '{step_name}' requires a flow: "
                    f"set config.{step_name}.flow = \"<flow_name>\" in the manifest."
                )

            step.check_pre()

            running_data = step.output_data
            self.steps.append(step)
            self.data.append(running_data)
