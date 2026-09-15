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
# PYTHON_ARGCOMPLETE_OK

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


def complete_config(prefix, parsed_args, **kw_args):
    return [key + "=" for key in completion_cache.get_config_keys()]


def run(target, recipe):
    """Run a block/step combination, resolving and executing the full chain."""

    if target not in context.blocks:
        raise exceptions.BakeRuntimeError(f"No such block: {target}")

    if context.config.bake.test is not None and not context.test_exists(context.config.bake.test, target):
        raise exceptions.BakeRuntimeError(f"No such test: {context.config.bake.test}")

    logging.debug("Building recipe for target '%s', chain '%s'", target, recipe)
    recipe = step.Recipe(target, recipe)
    recipe.elaborate(resolve_test=True)

    for s in recipe.steps:
        s.copy_flow_tree()

        if context.config.bake.populate:
            logging.info("Populate-only mode: skipping execution of '%s'", s.recipe_path)
            continue

        if context.config.bake.clean or context.config.bake.restart:
            s.clean()

        if context.config.bake.clean:
            logging.info("Clean-only mode: skipping execution of '%s'", s.recipe_path)
            continue

        logging.info("Running %s on block %s", s.recipe_path, target)
        s.run()
        s.check_post()


def main():
    coloredlogs.install(fmt='[bake] %(levelname)s\t %(message)s')
    logging.debug("bake started")
    completion_cache.load_from_file()

    parser = BakeArgumentParser(description="ASIC build and verification framework")
    parser.add_argument("target_recipe", nargs='*',
        help="Block and recipe to be executed").completer = complete_target_step
    parser.add_argument("-m", "--manifest-dir", dest="manifestpath", metavar="path", default=".", type=str,
        help="Directories containing manifests to be parsed by bake")
    parser.add_argument("-i", "--interactive", dest="interactive", action="store_true",
        help="Instructs flows to run interactively if possible.")
    parser.add_argument("-v", "--verbose", dest="verbose", action="count", default=0,
        help="Increases verbosity for bake and flow steps.")
    parser.add_argument("-t", "--test", dest="test", metavar="testname", type=str,
        help="Selects a test for the given block.").completer = complete_test
    parser.add_argument("-o", "--options", dest="options", type=str, default=[], action="append",
        help="User options (e.g. vrf.arguments=\"-GUI\")) to be passed to step configuration.")

    # force, populate, and clean are mutually exclusive run-mode flags
    mx = parser.add_mutually_exclusive_group()
    mx.add_argument("-f", "--force", dest="force", action="store_true",
        help="Forces execution of the specified block/recipe combination")
    mx.add_argument("-c", "--clean", dest="clean", action="store_true",
        help="Removes the working directory for a specified block/recipe combination")
    mx.add_argument("-r", "--restart", dest="restart", action="store_true",
        help="Removes the working directory for a specified block/recipe combination, then runs the recipe")
    mx.add_argument("-p", "--populate-flow", dest="populate", action="store_true",
        help="Only populates flow directories, does not invoke any step.")
    parser.add_argument("-l", "--list-libs", dest="listlibs", action="store_true",
        help="List all known libraries after evaluating manifests.")

    argcomplete.autocomplete(argument_parser=parser, always_complete_options=False)
    args = parser.parse_args()

    # Elaborate lazily, once all steps are defined
    context.config.bake.verbosity = args.verbose
    context.config.bake.interactive = args.interactive
    context.config.bake.test = args.test
    context.config.bake.force = args.force
    context.config.bake.clean = args.clean
    context.config.bake.restart = args.restart
    context.config.bake.populate = args.populate

    if args.verbose:
        coloredlogs.set_level(logging.DEBUG)
        logging.debug("Verbose mode enabled (level %d)", args.verbose)

    loader.reset_context()
    context.reset()
    step.Recipe.clear_cache()

    # Load builtin manifests
    try:
        builtin_dir = Path(__file__).resolve().parent / 'builtin'
        if not builtin_dir.is_dir():
            raise exceptions.BakeRuntimeError("Cannot find builtin folder")

        for entry in builtin_dir.iterdir():
            if not entry.is_dir():
                continue

            try:
                logging.debug("Loading builtin step directory: %s", entry.name)
                loader.load(str(entry))
            except Exception as e:
                logging.debug("Failed to load builtin entry '%s': %s", entry.name, e)

    except Exception:
        logging.error('Error while loading builtin steps')

    try:
        manifest_fname = str(Path(file_utils.absolute_path(args.manifestpath)) / "manifest")
        file_utils.check_file(manifest_fname)
    except exceptions.BakeFileError:
        logging.error("Manifest file not found: %s", manifest_fname)
        sys.exit(1)

    logging.debug("Loading user manifest from: %s", args.manifestpath)
    try:
        loader.load(args.manifestpath)
    except Exception as e:
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
        context.log_targets_and_tests()
        context.log_steps()
        sys.exit(0)

    if len(args.target_recipe) != 2:
        logging.error(
            "Expected 'bake <block> <recipe>' (e.g. 'bake counter vrf'), "
            "got: %s", " ".join(args.target_recipe) if args.target_recipe else "(nothing)"
        )
        sys.exit(1)
    target, recipe = args.target_recipe

    # Apply -o option overrides to the config: each option is step.attribute=value.
    for o in args.options:
        m = re.match(r'^([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)=(.+)$', o)
        if not m:
            raise exceptions.BakeConfigError("Malformed option string: %s. Expecting string in the format of `step.variable=value`.", o)

        section, attribute, value = m.groups()

        try:
            section_obj = getattr(context.config, section)
        except exceptions.BakeConfigError:
            logging.warning("Unknown config section '%s' in option '%s', skipping", section, o)
            continue

        attribute_val = getattr(section_obj, attribute)
        if isinstance(attribute_val, list):
            attribute_val.append(value)
            logging.debug("Config option applied: %s.%s += %r", section, attribute, value)
        else:
            setattr(section_obj, attribute, value)
            logging.debug("Config option applied: %s.%s = %r", section, attribute, value)

    try:
        run(target, recipe)
    except exceptions.BakeStepExecutionError as e:
        logging.error("Error during bake operation: %s", str(e))
        sys.exit(1)
    except exceptions.BakeRuntimeError as e:
        logging.error("Error during bake operation: %s", str(e))
        for line in str(traceback.format_exc()).split('\n'):
            logging.error(line)
        sys.exit(1)
    sys.exit(0)


class BakeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        logging.error(message)
        sys.exit(2)
