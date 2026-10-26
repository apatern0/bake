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
import os
import re
import traceback
from pathlib import Path

from . import file_utils
from .context import Project, ProjectOptions, context, _join, _suggest
from .exceptions import BakeConfigAttributeError, BakeConfigError, BakeManifestError

# Every manifest of this run, by path: its _Scope.
loaded: dict = {}
# The manifests executing now, innermost last.
_stack: list = []

_PROJECT_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*$')


def reset_loaded():
    """Forget which manifests have been executed (a new run reloads them all)."""
    global loaded, _stack
    loaded = {}
    _stack = []


class _Scope:
    """A manifest of this run: the project it belongs to (None for a
    built-in step's) and what it did that needs its project, so that a
    project() after that can be refused."""

    __slots__ = ("path", "project", "declared", "first_use", "given", "loaded_at")

    def __init__(self, path: str, project, given=None, loaded_at=""):
        self.path = path
        self.project = project
        self.declared = ""          # where it calls project(); "" while it does not
        self.first_use = ""         # the first thing it did that needs its project, and where
        self.given = given or {}    # the option values its load() gives
        self.loaded_at = loaded_at  # where it is first loaded

    def line(self) -> str:
        """`manifest:line` of the line of this manifest executing now."""
        for frame in reversed(traceback.extract_stack()):
            if frame.filename == self.path:
                return f"{display_path(self.path)}:{frame.lineno}"
        return display_path(self.path)

    def use(self, what: str) -> None:
        """Note that the manifest does something that needs its project
        (the first such thing only)."""
        if not self.declared and not self.first_use:
            self.first_use = f"{what} at {self.line()}"

    def proj(self) -> ProjectOptions:
        """config.proj: the options of the manifest's project."""
        self.use("reads config.proj")
        project = self.project
        if project is None:
            raise BakeConfigAttributeError("config.proj: a built-in step's manifest belongs to no project.")
        if project.options is None:
            raise BakeConfigAttributeError(
                f"config.proj: {project.label} declares no options. project(\"<name>\", "
                f"<option>=<default>, ...), first thing in its top manifest "
                f"({display_path(project.manifest)}), declares them."
            )
        return project.options


class ManifestConfig:
    """`config` as a manifest sees it: bake's config, but for config.proj,
    the options of the project the manifest belongs to. Each manifest has
    its own, so a function a manifest defines sees its project's options
    whenever it runs."""

    __slots__ = ("_bake_scope",)

    def __init__(self, scope: _Scope):
        object.__setattr__(self, "_bake_scope", scope)

    def __getattr__(self, key):
        if key == "proj":
            return self._bake_scope.proj()
        return getattr(context.config, key)

    def __setattr__(self, key, value):
        if key == "proj":
            raise BakeConfigError(
                "config.proj is the project's options, which project() declares; set one with "
                "config.proj.<option> = value."
            )
        setattr(context.config, key, value)

    def __dir__(self):
        return sorted(set(dir(context.config)) | {"proj"})


def current() -> "_Scope | None":
    """The manifest executing now; None outside of manifests."""
    return _stack[-1] if _stack else None


def _manifest_of(path) -> str:
    return str(Path(file_utils.absolute_path(path)) / "manifest")


def _call(path, options) -> str:
    """load(...) as written, for messages."""
    args = "".join(f", {k}={v!r}" for k, v in options.items())
    return f"load('{path}'{args})"


def _label(project) -> str:
    return project.label if project is not None else "bake's built-in steps"


def load(path, options=None):
    """Load a manifest file.

    Loads a file called "manifest" from the provided path. Relative paths will
    be treated as relative to the current manifest path, and will be converted
    into absolute paths.

    The cwd is temporarily changed to the manifest directory so that relative
    file paths declared inside the manifest resolve correctly at parse time.
    The original cwd is always restored in the finally block.

    Deduplication via the `loaded` registry prevents the same manifest from
    being executed twice when multiple blocks include the same dependency.

    The manifest belongs to the project of the manifest loading it, unless it
    calls project() itself and so starts a project of its own: `options` are
    then the values of that project's options. A manifest loaded again is
    checked to belong to the same project, and to be given the same options.
    """
    manifest_path = _manifest_of(path)
    options = dict(options or {})
    parent = current()
    if parent is not None:
        parent.use(f"loads '{path}'")

    prior = loaded.get(manifest_path)
    if prior is not None:
        logging.debug("Skipping already-loaded manifest: %s", manifest_path)
        _check_reload(prior, parent, path, options)
        return

    logging.debug("Loading manifest: %s", manifest_path)
    scope = _Scope(manifest_path, parent.project if parent else None, options,
                   parent.line() if parent else "")
    loaded[manifest_path] = scope

    file_utils.check_file(manifest_path)

    _exec_in_dir(scope)
    if options and not scope.declared:
        raise BakeManifestError(
            f"{_call(path, options)}: {display_path(manifest_path)} calls no project(), so it "
            f"has no options to set."
        )
    logging.debug("Manifest loaded successfully: %s", manifest_path)


def load_top(path):
    """Load the manifest bake runs (-m): the top project starts there, and
    the command line sets its options."""
    manifest_path = _manifest_of(path)
    project = Project("", manifest_path, top=True)
    context.projects[project.name] = project
    scope = _Scope(manifest_path, project, loaded_at="the command line")
    loaded[manifest_path] = scope
    file_utils.check_file(manifest_path)
    _exec_in_dir(scope)


def _check_reload(prior: _Scope, parent, path, options) -> None:
    """A manifest loaded again: same project, same options."""
    shown = display_path(prior.path)
    if prior.declared:
        if options != prior.given:
            raise BakeManifestError(
                f"{_call(path, options)} gives {_label(prior.project)} other options than its "
                f"first load, {_call(path, prior.given)} at {prior.loaded_at}: a project is "
                f"loaded once, with one set of options."
            )
        return
    if options:
        raise BakeManifestError(
            f"{_call(path, options)}: {shown} calls no project(), so it has no options to set."
        )
    if parent is not None and prior.project is not parent.project:
        raise BakeManifestError(
            f"load('{path}'): {shown} calls no project(), so its blocks belong to the project "
            f"that loads it, but {_label(parent.project)} loads it here and {_label(prior.project)} "
            f"at {prior.loaded_at}. Give it a project() of its own, or load it from one project only."
        )


def declare_project(name, options: dict) -> None:
    """project(name, **options) in the manifest executing now: the top
    project's name and options in the top manifest, a new project in any
    other."""
    scope = current()
    if scope is None or scope.project is None:
        raise BakeManifestError("project() declares a project in a project's manifest; a built-in step's has none.")
    if scope.declared:
        raise BakeManifestError(f"project() is called twice in this manifest; the first call is at {scope.declared}.")
    if scope.first_use:
        raise BakeManifestError(
            f"project() comes before anything that belongs to the project, but this manifest "
            f"{scope.first_use}. Move project() above it."
        )
    if not isinstance(name, str) or not _PROJECT_NAME.match(name):
        raise BakeManifestError(
            f"project({name!r}): a project's name is a letter followed by letters, digits, _ and -."
        )
    if name in context.projects:
        raise BakeManifestError(
            f"project('{name}'): {display_path(context.projects[name].manifest)} declares a "
            f"project of that name already; project names are unique."
        )
    upper = [k.upper() for k in options]
    clash = sorted(k for k in options if upper.count(k.upper()) > 1)
    if clash:
        raise BakeManifestError(
            f"project('{name}'): options {_join(clash)} differ in case only, and so would be the "
            f"same $BAKE_PROJ_* variable."
        )
    section = ProjectOptions(options)

    if scope.project.top and scope.path == scope.project.manifest:
        project = scope.project
        del context.projects[project.name]
        project.name = name
        context.projects = {name: project, **context.projects}
    else:
        project = Project(name, scope.path)
        scope.project = project
        context.projects[name] = project
    project.options = section
    scope.declared = scope.line()

    if project.top:
        context.config.apply_project_overrides(section, project)
    else:
        known = section._bake_attributes()  # pylint: disable=protected-access
        for key, value in scope.given.items():
            if key not in known:
                raise BakeManifestError(
                    f"load() at {scope.loaded_at} sets option '{key}' of {project.label}, which "
                    f"has no such option{_suggest(key, known)}. "
                    + (f"Its options: {_join(known)}." if known else "It declares none.")
                )
            section._bake_set_given(key, value, f"load() at {scope.loaded_at}")  # pylint: disable=protected-access
    logging.debug("Declared %s in %s (options: %s)", project.label, display_path(scope.path),
                  ", ".join(section._bake_attributes()) or "none")  # pylint: disable=protected-access


# The cwd bake was run from, while manifests execute in their own directory.
_run_dir = None


def display_path(path) -> str:
    """`path` as a message shows it: relative to the directory bake was run
    from, also while a manifest is executing."""
    return os.path.relpath(path, _run_dir or Path.cwd())


def _exec_in_dir(scope: _Scope):
    """``exec`` a manifest with its own directory as cwd and its own view of
    config (ManifestConfig)."""
    global _run_dir
    script_path = scope.path
    oldpath = Path.cwd()
    outermost = _run_dir is None
    if outermost:
        _run_dir = oldpath
    os.chdir(Path(script_path).parent)
    _stack.append(scope)
    try:
        with open(script_path, encoding="utf-8") as f:
            source = f.read()

        # Manifests are trusted Python and run with full interpreter access.
        # Only __file__ and config are injected, but manifests can import
        # anything in the environment.  Do not load manifests from untrusted sources.
        symbols = {'__file__': script_path, 'config': ManifestConfig(scope)}
        exec(compile(source, script_path, "exec"), symbols)
    finally:
        _stack.pop()
        os.chdir(oldpath)
        if outermost:
            _run_dir = None
