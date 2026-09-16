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
import re
import sys
from pathlib import Path
import traceback
import coloredlogs
import argcomplete

from . import loader
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

_TRUE_WORDS  = ("1", "true", "yes", "on")
_FALSE_WORDS = ("0", "false", "no", "off")


def _coerce_option_value(current, value: str):
    """Convert a -o value to the type of the attribute it replaces."""
    if isinstance(current, bool):
        if value.lower() in _TRUE_WORDS:
            return True
        if value.lower() in _FALSE_WORDS:
            return False
        raise exceptions.BakeConfigError(
            f"Expected a boolean (true/false), got '{value}'."
        )
    if isinstance(current, int):
        try:
            return int(value)
        except ValueError as err:
            raise exceptions.BakeConfigError(f"Expected an integer, got '{value}'.") from err
    return value


def apply_option_overrides(options):
    """Apply `-o section.attribute=value` overrides to the loaded config.

    A list attribute gets the value appended; a bool or int attribute gets
    the value converted; anything else is set as a string.  Unknown sections
    and attributes are errors: a silently ignored typo is worse than a stop.
    """
    for o in options:
        m = re.match(r'^([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)=(.*)$', o)
        if not m:
            raise exceptions.BakeConfigError(
                f"Malformed option '{o}': expected the form section.attribute=value "
                f"(e.g. -o vrf.simulator=icarus)."
            )
        section, attribute, value = m.groups()

        try:
            section_obj = getattr(context.config, section)
        except exceptions.BakeConfigError as err:
            raise exceptions.BakeConfigError(
                f"Option '{o}': unknown config section '{section}'. "
                f"Known sections: {', '.join(context.config._section_names())}."
            ) from err

        if attribute.startswith("_") or not hasattr(section_obj, attribute):
            known = [a for a in dir(section_obj) if not a.startswith("_") and not callable(getattr(section_obj, a))]
            raise exceptions.BakeConfigError(
                f"Option '{o}': config.{section} has no attribute '{attribute}'. "
                f"Known attributes: {', '.join(known)}."
            )

        current = getattr(section_obj, attribute)
        if isinstance(current, list):
            current.append(value)
            logging.debug("Config option applied: %s.%s += %r", section, attribute, value)
        else:
            try:
                new_value = _coerce_option_value(current, value)
            except exceptions.BakeConfigError as err:
                raise exceptions.BakeConfigError(f"Option '{o}': {err}") from err
            setattr(section_obj, attribute, new_value)
            logging.debug("Config option applied: %s.%s = %r", section, attribute, new_value)


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
    """List the blocks a recipe can be run on, their tests, and the state of
    the dependencies their recipe-form includes require."""
    blocks = {n: b for n, b in context.blocks.items() if b.rtl_files or b.includes}
    if not blocks:
        logging.info("No blocks with RTL files are registered.")
        return

    logging.info("Available blocks and associated tests:")
    for name, b in blocks.items():
        needs = []
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
    """Populate, clean and execute the steps of one elaborated recipe.

    `owner` names the block whose recipe pulled this one in as a dependency;
    clean/restart never touch dependencies, only the requested block. They
    remove the work directory of the requested block/recipe combination,
    i.e. the last step's: the earlier steps' directories are those of their
    own, shorter recipes (`tmr` for `tmr-impl`) and are left alone.
    """
    is_dependency = owner is not None
    for s in recipe.steps:
        s.copy_flow_tree()

        if context.config.bake.populate:
            logging.info("Populate-only mode: skipping execution of '%s'", s.recipe_path)
            continue

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
        help="Only populates flow directories (dependencies included), does not invoke any step.")
    parser.add_argument("-l", "--list-libs", dest="listlibs", action="store_true",
        help="List all known libraries after evaluating manifests.")

    argcomplete.autocomplete(argument_parser=parser, always_complete_options=False)
    args = parser.parse_args()

    if args.verbose:
        coloredlogs.set_level(logging.DEBUG)
        logging.debug("Verbose mode enabled (level %d)", args.verbose)

    # Start from a clean context (matters when bake runs several times in one
    # process, e.g. the test suite), then record the command-line options.
    loader.reset_loaded()
    context.reset()
    context.config.bake.verbosity = args.verbose
    context.config.bake.interactive = args.interactive
    context.config.bake.test = args.test
    context.config.bake.force = args.force
    context.config.bake.clean = args.clean
    context.config.bake.restart = args.restart
    context.config.bake.populate = args.populate
    context.config.bake.dry_run = args.dry_run

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
    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.error("Error while loading manifest: %s", str(e))
        logging.error("")
        for line in str(traceback.format_exc()).split('\n'):
            logging.error(line)
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
        apply_option_overrides(args.options)
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
