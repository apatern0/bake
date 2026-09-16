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

"""Step base class, shared utilities, and chain orchestration.

Built-in steps are discovered from the `steps/` directory at the root of
this repository.  Additional steps can be registered by calling
add_steps_dir() in the manifest; any .py file in those directories that
defines a Step subclass will be discovered automatically.

Chain names are parsed dynamically: "tmr-impl-vrf" is split into the
ordered sequence ["tmr", "impl", "vrf"] by greedy prefix matching against
the set of known primitive names.  No predefined chain list is required.
"""

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
from typing import Any, Optional

from . import exceptions, file_utils
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

    Two immutable original references give any step access to the unmodified
    manifest objects at any point in the chain.  All other fields are the
    *current* working state — initialised from those objects and freely
    modifiable by steps.

    Attributes
    ----------
    target : TargetSpec
        Original manifest target.  Read-only: steps must not reassign this.
    test : EnvSpec | None
        Original manifest test/env.  Read-only: steps must not reassign this.

    top, rtl_files, rtl_incdirs, libs
        Target-derived working state.  TmrStep renames `top` and replaces
        `rtl_files`; any step may modify these.

    vrf_top … default_sim
        Test-derived working state.  VrfStep consumes these; a user step
        may transform them before vrf runs.

    recipe_prefix, is_last
        Bookkeeping updated by the Recipe orchestrator.
    """

    # ── Immutable original references ────────────────────────────────────────
    # Reassigning `target` or `test` raises AttributeError (enforced in
    # __post_init__ / __setattr__).  Mutating their *contents* is also
    # strongly discouraged; treat them as read-only snapshots.
    target: Any = None  # BlockSpec; read-only after __post_init__
    test:   Any = None  # EnvSpec or None; read-only after __post_init__

    # ── Mutable target-derived working state ─────────────────────────────────
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

    # ── Block gate-level / lib fields (from BlockSpec, passed along pipeline) ─
    netlist_files:      list = field(default_factory=list)   # gate-level Verilog
    netlist_incdirs:    list = field(default_factory=list)   # gate-level include dirs
    liberty_files:    dict = field(default_factory=dict)   # {corner: [files]}
    si_files:     dict = field(default_factory=dict)   # {corner: [files]}
    layout_info:  str  = ""

    # ── Constraint and activity files ─────────────────────────────────────────
    sdf_files:    dict = field(default_factory=dict)   # annotated delays {corner: file}
    sdc_files:    list = field(default_factory=list)   # design constraints
    vcd_files:    dict = field(default_factory=dict)   # value change dump {corner: [files]}
    saif_files:   dict = field(default_factory=dict)   # switching activity {corner: [files]}

    # ── Bookkeeping ──────────────────────────────────────────────────────────
    recipe_prefix: RecipePath = field(default_factory=RecipePath)
    is_last:      bool        = False

    def __post_init__(self):
        object.__setattr__(self, '_locked', frozenset({'target', 'test'}))

    def __setattr__(self, name, value):
        locked = self.__dict__.get('_locked', frozenset())
        if name in locked:
            raise AttributeError(
                f"StepData.{name} is read-only — it preserves the original manifest object. "
                f"Modify the working-state fields instead (top, rtl_files, vrf_top, …)."
            )
        object.__setattr__(self, name, value)

    def copy(self) -> "StepData":
        return dataclasses.replace(self)

    def extend(self, data: StepData):
        def dict_inherit(child, parent):
            child = child.copy()

            for opt_k, opt_v in parent.items():
                if opt_k not in child:
                    child[opt_k] = opt_v.copy()
                else:
                    child[opt_k] = list_inherit(child[opt_k], opt_v)

            return child

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

        str_extend = [
            "vrf_top", "vrf_framework", "vrf_framework_top",
            "default_sim", "layout_info"
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

    def _process_env_includes(self):
        for dep_name in self.test.includes:
            logging.debug(
                "Processing env include '%s' for test '%s'",
                dep_name, self.test.name,
            )
            if dep_name not in context.envs:
                raise exceptions.BakeIncludeError(
                    f"Include {dep_name}: env not found"
                )

            data = StepData.create_from_env(context.envs[dep_name])
            self.extend(data)


    def _process_block_includes(self):
        for dep_name, dep_recipe_str in self.target.includes.items():
            logging.debug(
                "Processing block include '%s' (recipe='%s') for target '%s'",
                dep_name, dep_recipe_str, self.target.name,
            )
            if dep_name not in context.blocks:
                raise exceptions.BakeIncludeError(
                    f"Include {dep_name}: block not found"
                )

            data = None
            if dep_recipe_str == "rtl":
                # RTL include: pull in source files directly, no step outputs needed.
                data = StepData.create_from_block(context.blocks[dep_name])
            else:
                try:
                    dep_recipe = Recipe(dep_name, dep_recipe_str)
                    dep_recipe.elaborate()

                    last_step = dep_recipe.last_step
                    if last_step.run_required() or not last_step.outputdir.is_dir():
                        raise exceptions.BakeIncludeError(
                            f"Include {dep_name}/{dep_recipe_str}: output not found or obsolete at "
                            f"{last_step.outputdir}. Run '{dep_name} {dep_recipe_str}' first."
                        )

                    logging.debug(
                        "Include '%s/%s' resolved to outputdir: %s",
                        dep_name, dep_recipe_str, last_step.outputdir,
                    )
                    data = last_step.output_data

                except exceptions.BakeIncludeError:
                    if self.target.skip_on_include_errors:
                        logging.warning(
                            "Skipping include %s (recipe '%s') for block %s",
                            dep_name, dep_recipe_str, self.target.name,
                        )
                    else:
                        raise

            self.extend(data)

    @staticmethod
    def create(block: Optional["BlockSpec"] = None, env: Optional["EnvSpec"] = None):
        obj = StepData(
            target=block,
            test=env,

            # block-derived working state
            top         = block.top if block else "",
            rtl_files   = list(block.rtl_files) if block else [],
            rtl_incdirs = list(block.rtl_incdirs) if block else [],
            libs        = block.resolved_libs if block else [],
            netlist_files   = list(block.netlist_files) if block else [],
            netlist_incdirs = list(block.netlist_incdirs) if block else [],
            liberty_files   = dict(block.liberty_files) if block else {},
            si_files    = dict(block.si_files) if block else {},
            layout_info = block.layout_info if block else "",
            sdc_files   = list(block.sdc_files) if block else [],
            vcd_files   = dict(block.vcd_files) if block else {},
            saif_files  = dict(block.saif_files) if block else {},

            # env-derived working state
            vrf_top           = env.vrf_top if env else "",
            vrf_files         = list(env.vrf_files) if env else [],
            vrf_incdirs       = list(env.vrf_incdirs) if env else [],
            vrf_libs          = env.resolved_libs if env else [],
            vrf_defines       = list(env.vrf_defines) if env else [],
            vrf_options       = dict(env.vrf_options) if env else {},
            vrf_framework     = env.vrf_framework if env else "",
            vrf_framework_top = env.vrf_framework_top if env else "",
            default_sim       = env.default_sim if env else ""
        )

        if env:
            obj._process_env_includes()
        if block:
            obj._process_block_includes()

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
        name  -- short identifier used in chain names, e.g. "vrf"

    All target and test data is available via self.data (StepData).
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

    def check_post(self):
        """Verify that expected output files were produced."""
        missing = [f for f in self.output_files if not Path(f).is_file()]
        if missing:
            missing_str = "\n".join("   -" + f for f in missing)
            raise exceptions.BakeRuntimeError(
                f"Step {self.recipe_path} for target {self.data.target.name} "
                f"did not produce all required files:\n{missing_str}"
            )
        if self.output_files:
            logging.debug(
                "Step '%s' post-check passed (%d output files verified)",
                self.recipe_path, len(self.output_files),
            )

    def clean(self) -> None:
        """Remove the work directory for this step step."""
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
        except Exception:
            return False

    @property
    def config(self):
        return getattr(context.config, self.name)

    @property
    def flowdir(self) -> Path:
        return Path(self.data.target.dir) / "flow" / self.data.target.name / self.recipe_path

    @property
    def workdir(self) -> Path:
        if hasattr(self.config, 'output_dir') and self.config.output_dir:
            return Path(self.config.output_dir)

        if context.config.bake.output_dir:
            return Path(context.config.bake.output_dir) / self.data.target.name / self.recipe_path

        return Path(self.data.target.dir) / "work" / self.data.target.name / self.recipe_path

    @property
    def outputdir(self) -> Path:
        return self.workdir / "output"

    def run_required(self) -> bool:
        """Return True if step execution is needed.

        Uses ctime (inode change time) rather than mtime so that link
        retargeting and permission changes also trigger a re-run.
        """

        def log_first_five(files):
            for f in files[:5]:
                logging.info("   - %s", f)
            if len(files) > 5:
                logging.info("   - …")

        if not self.output_files:
            logging.debug("Step '%s' declares no output files; will always run.", self.name)
            return True  # step produces no trackable output; always execute

        output_missing = [f for f in self.output_files if not Path(f).is_file()]
        if output_missing:
            logging.info("Expected output files missing for step '%s':", self.name)
            log_first_five(output_missing)
            return True

        in_files  = [f for f in self.source_files if not Path(f).is_symlink()]
        out_files = [f for f in self.output_files if not Path(f).is_symlink()]

        if self.source_files and not in_files:
            raise exceptions.BakeRuntimeError(
                "All input files are symlinks — cannot reliably check modification dates."
            )
        if not out_files:
            logging.warning(
                "All output files for step '%s' are symlinks — treating as up-to-date.",
                self.name,
            )
            return False

        oldest_out  = min(out_files, key=lambda f: Path(f).stat().st_ctime)
        oldest_time = datetime.datetime.fromtimestamp(Path(oldest_out).stat().st_ctime)
        newer_files = [f for f in in_files if Path(f).stat().st_ctime > Path(oldest_out).stat().st_ctime]
        if newer_files:
            logging.info(
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

    def run(self):
        if context.config.bake.force:
            logging.info("Force flag set — running step '%s' unconditionally.", self.name)
        elif not self.run_required():
            logging.info("Output files are up-to-date, skipping step %s.", self.name)
            return
        self.copy_and_template()
        self.execute_flow_step()

    def build_tpl_dict(self) -> dict:
        """Base template variables from bake global config."""
        tpl_dict = context.config.bake.tpl_dict.copy()
        tpl_dict["BAKE_INTERACTIVE"] = int(context.config.bake.interactive)
        tpl_dict["BAKE_VERBOSITY"]   = context.config.bake.verbosity
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
                    with open(subfile_src, "r") as f_in, open(subfile_dest, "w") as f_out:
                        template = string.Template(f_in.read())
                        try:
                            f_out.write(template.substitute(tpl_dict))
                        except KeyError as err:
                            raise exceptions.BakeInternalError(
                                f"{subfile_src}: Template variable {err} is undefined."
                            )
                        except ValueError as err:
                            raise exceptions.BakeInternalError(f"{subfile_src}: {err}")
                    shutil.copymode(subfile_src, subfile_dest)
                else:
                    subfile_dest = current_dir_dest / subfile
                    if subfile_dest.exists():
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

        def handle_signal(signum, frame):
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

        proc = subprocess.Popen("./" + run_executable, shell=True, cwd=run_dir,
                                start_new_session=True)

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()

        backup_sigterm = signal.getsignal(signal.SIGTERM)
        backup_sigint  = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT,  handle_signal)
        proc.wait()
        heartbeat_stop.set()
        heartbeat_thread.join()
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
class CachedMeta:
    """Memoizing metaclass mixin for Recipe.

    Recipe objects with identical (target_name, recipe) arguments are
    returned from cache rather than re-elaborated.  This prevents redundant
    elaboration when the same dependency recipe is referenced from multiple
    block includes in a single bake run.
    """
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._cache = {}

    def __new__(cls, *args, **kwargs):
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cls._cache:
            instance = super().__new__(cls)
            cls._cache[key] = instance
        return cls._cache[key]

    @classmethod
    def clear_cache(cls):
        cls._cache.clear()

    def __init__(self, *args, **kwargs):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True


class Recipe(CachedMeta):
    def __init__(self, target_name, recipe):
        super().__init__()

        self.target_name = target_name
        self.recipe      = recipe.split("-")
        self.steps      = []
        self.data        = []

    @property
    def last_step(self):
        return self.steps[-1] if self.steps else None

    def elaborate(self, resolve_test=False):
        if self.target_name not in context.blocks:
            raise exceptions.BakeRuntimeError(
                f"Block '{self.target_name}' not defined."
            )

        # Resolve block
        block = context.blocks[self.target_name]
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
                    logging.debug("Using explicitly selected test '%s'", test.name if test else context.config.bake.test)
                elif len(block.available_tests) == 1:
                    test = context.find_test(block.available_tests[0], block.name)
                    logging.info("Auto-selecting test '%s' (only test for block '%s')", test.name, block.name)
                else:
                    raise exceptions.BakeManifestError(
                        f"Target '{block.name}' has multiple tests: {block.available_tests}. "
                        f"Use -t <testname> to select one."
                    )
            else:
                logging.debug("No test required for recipe '%s'", "-".join(self.recipe))

        # Create initial StepData
        running_data = StepData.create(block=block, env=test)
        self.data.append(running_data)

        for i, step_name in enumerate(self.recipe):
            is_last = (i == len(self.recipe) - 1)

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

            running_data         = step.output_data
            running_data.is_last = is_last

            self.steps.append(step)
            self.data.append(running_data)
