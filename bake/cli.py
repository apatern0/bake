#!/usr/bin/env python
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
import argparse
import difflib
import os
import sys
from pathlib import Path
import traceback
import coloredlogs
import argcomplete
import pydantic

from . import loader
from . import manifest
from . import step
from . import exceptions
from . import completion_cache
from . import file_utils
from .context import context


def complete_target_step(prefix, parsed_args, **kw_args):
    if len(parsed_args.target_recipe) == 0:
        return completion_cache.get_targets()
    if len(parsed_args.target_recipe) == 1:
        return completion_cache.get_steps()
    return []


def complete_test(prefix, parsed_args, **kw_args):
    if len(parsed_args.target_recipe):
        return completion_cache.get_tests(parsed_args.target_recipe[0])
    return []


def complete_config(prefix, parsed_args, **kw_args):
    return [key + "=" for key in completion_cache.get_config_keys()]


# ---------------------------------------------------------------------------
# -o option overrides
# ---------------------------------------------------------------------------

def _origin_note(origin: str) -> str:
    return {"default": "", "set": "  (set by a manifest)", "-o": "  (set by -o)",
            "flag": "  (set by the command line)"}.get(origin, "")


def log_options():
    """List every config section and attribute: its value, where the value
    comes from, the kinds and values it takes, and its description."""
    logging.info("Configuration (set an attribute with -o section.attribute=value):")
    for name, rows in context.config.describe():
        logging.info("config.%s%s", name, "" if rows else "  (no attributes)")
        for attr, value, opt, origin in rows:
            logging.info("  %-22s = %r%s", attr, value, _origin_note(origin))
            details = []
            if opt is not None and opt.desc:
                details.append(opt.desc)
            if opt is not None and opt.choices is not None:
                details.append("one of " + ", ".join(str(c) for c in opt.choices))
            elif isinstance(value, list):
                details.append("a list: -o adds one item")
            elif isinstance(value, dict):
                details.append("a dictionary: set its keys in a manifest")
            if details:
                logging.info("  %-22s   %s", "", "; ".join(details))


# ---------------------------------------------------------------------------
# Manifest errors
# ---------------------------------------------------------------------------

def _manifest_location(err: BaseException) -> tuple:
    """(`file:line`, raised_there) for the innermost manifest frame the error
    passed through, relative to the current directory. raised_there says
    the error came from the manifest's own code (a NameError for a typo,
    say) rather than from bake underneath it. ("", False) without one."""
    if isinstance(err, SyntaxError) and err.filename:
        return f"{os.path.relpath(err.filename)}:{err.lineno}", True
    frames = traceback.extract_tb(err.__traceback__)
    manifest_frames = [f for f in frames if Path(f.filename).name == "manifest"]
    if not manifest_frames:
        return "", False
    last = manifest_frames[-1]
    return f"{os.path.relpath(last.filename)}:{last.lineno}", last is frames[-1]


def _validation_messages(err: pydantic.ValidationError) -> list:
    """One line per pydantic error, in manifest terms: the function, the
    argument, and a suggestion for an unknown one."""
    spec = manifest.spec_class(err.title)
    func = f"{spec.manifest_function}()" if spec and spec.manifest_function else err.title
    fields = list(spec.model_fields) if spec else []
    lines = []
    for e in err.errors():
        arg = ".".join(str(x) for x in e["loc"]) or "<arguments>"
        if e["type"] == "extra_forbidden":
            msg = f"unknown argument '{arg}'"
            close = difflib.get_close_matches(arg, fields, n=1)
            if close:
                msg += f" (did you mean '{close[0]}'?)"
        else:
            msg = f"{arg}: {e['msg']}"
        lines.append(f"{func}: {msg}")
    return lines


def report_manifest_error(err: BaseException, verbose: bool) -> None:
    """Log a manifest loading error as one line per problem, prefixed with
    where in the manifest it happened. Errors the manifest author can act
    on (a bad argument, a bake error, a Python error in the manifest
    itself) get the traceback only with -v; anything else is a problem in
    bake and always shows it."""
    if isinstance(err, exceptions.BakeOptionError):
        # The command line's fault, wherever the manifest stood when its
        # section was registered.
        logging.error("%s", err)
        return
    where, raised_in_manifest = _manifest_location(err)
    if isinstance(err, pydantic.ValidationError):
        messages, expected = _validation_messages(err), True
    elif isinstance(err, exceptions.BakeRuntimeError):
        messages, expected = [str(err)], True
    else:
        messages, expected = [f"{type(err).__name__}: {err}"], raised_in_manifest

    prefix = f"{where}: " if where else "Error while loading manifest: "
    for msg in messages:
        logging.error("%s%s", prefix, msg)
    if verbose or not expected:
        for line in traceback.format_exception(err):
            for sub in line.rstrip("\n").split("\n"):
                logging.error(sub)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def _dependency_state(dep_recipe) -> str:
    """One-word state of an already elaborated dependency recipe."""
    last = dep_recipe.last_step
    if not last.outputdir.is_dir():
        return "not built"
    reason = last.stale_reason()
    return f"stale ({reason})" if reason else "up to date"


def log_blocks_and_tests():
    """List the blocks a recipe can be run on, with their kind when it is not
    RTL, their tests, and the state of the dependencies their recipe-form
    includes require."""
    blocks = {n: b for n, b in context.blocks.items() if not b.is_empty}
    if not blocks:
        logging.info("No blocks are registered.")
        return

    logging.info("Available blocks and associated tests:")
    for name, b in blocks.items():
        kind = b.data_type.kind
        needs = [] if kind == "rtl" else [kind]
        for dep_name, dep_recipe_str in b.includes.items():
            if dep_recipe_str == "rtl":
                continue
            try:
                dep = step.Recipe(dep_name, dep_recipe_str)
                dep.elaborate()
                state = _dependency_state(dep)
            except exceptions.BakeRuntimeError as err:
                state = f"cannot elaborate: {err}"
            needs.append(f"needs {dep_name} {dep_recipe_str}: {state}")
        suffix = f"  ({'; '.join(needs)})" if needs else ""
        logging.info("- %s%s", name, suffix)
        for t in context.find_test_by_target(name):
            logging.info("    - %s", t.name)


# ---------------------------------------------------------------------------
# Running a recipe
# ---------------------------------------------------------------------------

def _run_steps(recipe, force, owner=None):
    """Clean and execute the steps of one elaborated recipe.

    `owner` names the block whose recipe pulled this one in as a dependency;
    clean/restart never touch dependencies, only the requested block. They
    remove the work directory of the requested block/recipe combination,
    i.e. the last step's: the earlier steps' directories are those of their
    own, shorter recipes (`tmr` for `tmr-impl`) and are left alone.
    """
    is_dependency = owner is not None
    for s in recipe.steps:
        if not is_dependency and s is recipe.last_step and \
                (context.config.bake.clean or context.config.bake.restart):
            s.clean()

        if context.config.bake.clean:
            logging.info("Clean-only mode: skipping execution of '%s'", s.recipe_path)
            continue

        if is_dependency:
            logging.info("Running %s on block %s (dependency of %s)", s.recipe_path, recipe.block_name, owner)
        else:
            logging.info("Running %s on block %s", s.recipe_path, recipe.block_name)
        s.report_flow()
        s.run(force=force)


def _dry_run(recipe):
    """Report what a run would do, without executing anything."""
    def report(r, is_dependency):
        for s in r.steps:
            reason = s.stale_reason()
            state = "would run" if reason else "up to date"
            if not is_dependency and context.config.bake.force and not reason:
                state, reason = "would run", "forced"
            what = f"{r.block_name} {s.recipe_path}"
            if is_dependency:
                what += f"  (dependency of {recipe.block_name})"
            if reason:
                what += f"  [{reason}]"
            logging.info("%-18s %s", state + ":", what)

    for dep in recipe.all_dependencies():
        report(dep, True)
    report(recipe, False)
    logging.info("Dry run — nothing executed.")


def run(block, recipe_str):
    """Run a block/recipe combination: its dependencies first, then its own steps."""

    if block not in context.blocks:
        raise exceptions.BakeRuntimeError(f"No such block: {block}")

    if context.config.bake.test is not None and not context.test_exists(context.config.bake.test, block):
        raise exceptions.BakeRuntimeError(f"No such test: {context.config.bake.test}")

    logging.debug("Building recipe for block '%s', recipe '%s'", block, recipe_str)
    recipe = step.Recipe(block, recipe_str)
    recipe.elaborate(resolve_test=True)

    if context.config.bake.dry_run:
        _dry_run(recipe)
        return

    if context.config.bake.populate:
        # The step the command names, only: not the recipe's earlier steps,
        # which have flow directories of their own, nor its dependencies.
        recipe.last_step.populate()
        return

    if context.config.bake.clean:
        # Nothing to build for a clean; dependencies are left alone.
        _run_steps(recipe, force=False)
        return

    for dep in recipe.all_dependencies():
        _run_steps(dep, force=False, owner=block)

    _run_steps(recipe, force=context.config.bake.force)


def main():
    coloredlogs.install(fmt='[bake] %(levelname)s\t %(message)s')
    logging.debug("bake started")
    completion_cache.load_from_file()

    parser = BakeArgumentParser(description="ASIC build and verification framework")
    parser.add_argument("target_recipe", nargs='*',
        help="Block and recipe to be executed").completer = complete_target_step
    parser.add_argument("-m", "--manifest-dir", dest="manifestpath", metavar="path", default=".", type=str,
        help="Directory containing the manifest to be parsed by bake")
    parser.add_argument("-i", "--interactive", dest="interactive", action="store_true",
        help="Instructs flows to run interactively if possible.")
    parser.add_argument("-v", "--verbose", dest="verbose", action="count", default=0,
        help="Increases verbosity for bake and flow steps.")
    parser.add_argument("-t", "--test", dest="test", metavar="testname", type=str,
        help="Selects a test for the given block.").completer = complete_test
    parser.add_argument("-o", "--options", dest="options", type=str, default=[], action="append",
        metavar="section.attribute=value",
        help="Override a config attribute for this run (e.g. -o vrf.simulator=icarus). Repeatable."
    ).completer = complete_config
    parser.add_argument("-n", "--dry-run", dest="dry_run", action="store_true",
        help="Elaborate the recipe and report what would run (dependencies included) without executing anything.")

    # force, populate, and clean are mutually exclusive run-mode flags
    mx = parser.add_mutually_exclusive_group()
    mx.add_argument("-f", "--force", dest="force", action="store_true",
        help="Forces execution of the requested block/recipe (dependencies run only when stale)")
    mx.add_argument("-c", "--clean", dest="clean", action="store_true",
        help="Removes the working directory for a specified block/recipe combination")
    mx.add_argument("-r", "--restart", dest="restart", action="store_true",
        help="Removes the working directory for a specified block/recipe combination, then runs the recipe")
    mx.add_argument("-p", "--populate-flow", dest="populate", action="store_true",
        help="Copy the flow of the recipe's last step into flow/<block>/<recipe>/ to customise it; "
             "that step runs the copy from then on. Runs nothing. On an existing copy, records it as "
             "based on the flow as it is now.")
    parser.add_argument("-l", "--list-libs", dest="listlibs", action="store_true",
        help="List all known libraries after evaluating manifests.")
    parser.add_argument("--list-options", dest="listoptions", action="store_true",
        help="List every config attribute after evaluating manifests: its value, what it takes "
             "and its description.")
    parser.add_argument("--version", action="version", version=f"bake {step.bake_version()}")

    argcomplete.autocomplete(argument_parser=parser, always_complete_options=False)
    args = parser.parse_args()

    # -p only copies a flow; -f, -c and -r are excluded by the group above.
    if args.populate and (args.dry_run or args.interactive):
        parser.error("-p/--populate-flow only copies a flow: it cannot be combined with -n or -i")
    # -n reports what a run would do, so it combines with -f but not with
    # the modes that do something else instead of running.
    if args.dry_run and (args.clean or args.restart):
        parser.error("-n/--dry-run cannot be combined with -c or -r")

    if args.verbose:
        coloredlogs.set_level(logging.DEBUG)
        logging.debug("Verbose mode enabled (level %d)", args.verbose)

    # Start from a clean context (matters when bake runs several times in one
    # process, e.g. the test suite), then record the command-line options.
    loader.reset_loaded()
    context.reset()
    for attr, value in (
        ("verbosity", args.verbose), ("interactive", args.interactive),
        ("manifest_dir", file_utils.absolute_path(args.manifestpath)),
        ("options", list(args.options)), ("test", args.test), ("force", args.force),
        ("clean", args.clean), ("restart", args.restart), ("populate", args.populate),
        ("dry_run", args.dry_run),
    ):
        context.config.bake._bake_set_from_flag(attr, value)  # pylint: disable=protected-access

    # The -o overrides take effect as their sections are registered, so the
    # manifests see them while they load; config.bake exists already.
    try:
        context.config.set_overrides(args.options)
        context.config.apply_overrides("bake")
    except exceptions.BakeConfigError as e:
        logging.error("%s", e)
        sys.exit(1)

    # Load builtin manifests
    builtin_dir = Path(__file__).resolve().parent / 'builtin'
    if not builtin_dir.is_dir():
        logging.error("Cannot find the builtin steps folder: %s", builtin_dir)
        sys.exit(1)

    for entry in sorted(builtin_dir.iterdir()):
        if not entry.is_dir():
            continue
        try:
            logging.debug("Loading builtin step directory: %s", entry.name)
            loader.load(str(entry))
        except exceptions.BakeOptionError as e:
            # An override of the section the step registers.
            logging.error("%s", e)
            sys.exit(1)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # A broken builtin is a broken installation: nothing sensible
            # can run without the step it defines.
            logging.error("Failed to load builtin step '%s': %s", entry.name, e)
            sys.exit(1)

    try:
        manifest_fname = str(Path(file_utils.absolute_path(args.manifestpath)) / "manifest")
        file_utils.check_file(manifest_fname)
    except exceptions.BakeFileError:
        logging.error("Manifest file not found: %s", manifest_fname)
        sys.exit(1)

    logging.debug("Loading user manifest from: %s", args.manifestpath)
    try:
        loader.load(args.manifestpath)
        context.validate()
        context.config.finish_overrides()
    except Exception as e:  # pylint: disable=broad-exception-caught
        report_manifest_error(e, verbose=bool(args.verbose))
        sys.exit(1)

    logging.debug(
        "Manifest loaded: %d blocks, %d tests, %d flows, %d libs, %d steps",
        len(context.blocks), len(context.tests), len(context.flows),
        len(context.libs), len(context.steps),
    )

    completion_cache.store_to_file()

    if args.listlibs:
        context.log_libs()
        sys.exit(0)

    if args.listoptions:
        log_options()
        sys.exit(0)

    if not args.target_recipe:
        logging.info("No block specified.")
        log_blocks_and_tests()
        context.log_steps()
        sys.exit(0)

    if len(args.target_recipe) != 2:
        logging.error(
            "Expected 'bake <block> <recipe>' (e.g. 'bake counter vrf'), "
            "got: %s", " ".join(args.target_recipe)
        )
        sys.exit(1)
    block, recipe = args.target_recipe

    try:
        run(block, recipe)
    except exceptions.BakeStepExecutionError as e:
        logging.error("Error during bake operation: %s", str(e))
        sys.exit(1)
    except exceptions.BakeRuntimeError as e:
        logging.error("Error during bake operation: %s", str(e))
        if args.verbose:
            for line in str(traceback.format_exc()).split('\n'):
                logging.error(line)
        sys.exit(1)
    sys.exit(0)


class BakeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        logging.error(message)
        sys.exit(2)
