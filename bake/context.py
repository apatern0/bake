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

import difflib
import functools
import re
import logging
from typing import TYPE_CHECKING
from .exceptions import (
    BakeConfigAttributeError,
    BakeConfigError,
    BakeManifestError,
    BakeOptionError,
)

if TYPE_CHECKING:
    from .manifest import TestSpec


# ---------------------------------------------------------------------------
# Options: an attribute's default with its description, type and choices
# ---------------------------------------------------------------------------

# The kinds of value an attribute can hold, as messages name them. bool comes
# before int: True is an int too.
_KINDS = (bool, int, float, str, list, dict)
_KIND_NAMES = {
    bool:  "a boolean (true or false)",
    int:   "an integer",
    float: "a number",
    str:   "a string",
    list:  "a list",
    dict:  "a dictionary",
}

_TRUE_WORDS  = ("1", "true", "yes", "on")
_FALSE_WORDS = ("0", "false", "no", "off")


def _kind_of(value):
    """The kind of value (one of _KINDS; a tuple is a list), None for any other."""
    if isinstance(value, tuple):
        return list
    return next((k for k in _KINDS if isinstance(value, k)), None)


def _kind_name(kinds) -> str:
    return " or ".join(_KIND_NAMES[k] for k in kinds)


def _value_name(value) -> str:
    """A value as an error message shows it: what it is, then the value."""
    kind = _kind_of(value)
    what = _KIND_NAMES[kind] if kind else f"a {type(value).__name__}"
    return f"{what} ({value!r})"


def _join(values) -> str:
    return ", ".join(str(v) for v in values)


def _suggest(name, known) -> str:
    """' (did you mean 'x'?)' for the closest known name, or ''."""
    close = difflib.get_close_matches(name, list(known), n=1)
    return f" (did you mean '{close[0]}'?)" if close else ""


class Option:
    """An attribute's default value with what bake knows about it: a
    description, the kinds of value it takes and, optionally, the values it
    may take. A section declares one in its __init__ with config.option();
    -o converts and checks command-line values against it, an assignment in
    a manifest is checked against it, and `bake --options` lists it."""

    __slots__ = ("default", "desc", "kinds", "choices")

    def __init__(self, default, desc="", choices=None, kind=None):
        self.default = default
        self.desc = desc
        if kind is None:
            # From the default; None takes anything (no check).
            kinds = () if default is None else (_kind_of(default),)
        else:
            kinds = tuple(kind) if isinstance(kind, (tuple, list)) else (kind,)
        if any(k not in _KINDS for k in kinds):
            raise BakeConfigError(
                f"config.option({default!r}, ...): kind must be one or more of "
                f"{_join(k.__name__ for k in _KINDS)}."
            )
        self.kinds = kinds
        self.choices = None if choices is None else list(choices)
        if self.choices is not None:
            if not self.choices:
                raise BakeConfigError(f"config.option({default!r}, ...): choices is empty.")
            if {list, dict} & set(self.kinds):
                raise BakeConfigError(
                    f"config.option({default!r}, ...): choices apply to a single value, "
                    f"not to a list or a dictionary."
                )
            if default is not None and default not in self.choices:
                raise BakeConfigError(
                    f"config.option({default!r}, ...): the default is not one of its "
                    f"choices ({_join(self.choices)})."
                )

    def accepts(self, value) -> bool:
        """Whether value is of a kind the option takes (an int where a number
        is expected, a tuple where a list is)."""
        if not self.kinds or (value is None and self.default is None):
            return True
        kind = _kind_of(value)
        return kind in self.kinds or (kind is int and float in self.kinds)


def option(default, desc="", choices=None, kind=None) -> Option:
    """Declare a config attribute in a section's __init__:

        self.pixel_pitch = config.option(100, "Pixel pitch in um", choices=[100, 120, 150])

    The attribute starts at `default`; `desc` is what `bake --options` and
    the error messages say about it; `choices` limits the values it may
    take. Its kind (bool, int, float, str, list or dict) is the default's,
    or `kind` (one kind or a tuple of them) when the default does not say
    it, e.g. a default of None."""
    return Option(default, desc, choices, kind)


class FixedSchemaAttributes:
    """Base class for config sections whose attributes are fixed: __init__
    defines them, and once it returns, assigning a name that does not exist
    is an error — so a typo like `config.vrf.simulater = ...` stops bake
    instead of being ignored.

    An attribute declared with config.option() is checked as well: a
    manifest assigning it a value of another kind, or one outside its
    choices, is an error. An attribute the command line sets (-o) keeps the
    command line's value: a manifest assigning it afterwards changes
    nothing, so manifests see the value the run uses."""

    _bake_frozen = False
    _bake_section = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        init = cls.__init__

        @functools.wraps(init)
        def init_then_freeze(self, *args, **kw):
            init(self, *args, **kw)
            if type(self) is cls:  # the most derived class' __init__ has finished
                object.__setattr__(self, "_bake_frozen", True)

        cls.__init__ = init_then_freeze

    # Per-instance bookkeeping, made on first use: the options declared with
    # config.option(), the values the command line set, and where each
    # attribute's value comes from (default, set, -o).
    def _bake_book(self, name) -> dict:
        book = self.__dict__.get(name)
        if book is None:
            book = {}
            object.__setattr__(self, name, book)
        return book

    def _bake_name(self) -> str:
        return self._bake_section or self.__class__.__name__

    def __setattr__(self, key, value):
        if isinstance(value, Option):
            if self._bake_frozen:
                raise BakeConfigError(
                    f"config.{self._bake_name()}.{key}: config.option() declares an attribute "
                    f"in the section's __init__; assign a plain value here."
                )
            self._bake_book("_bake_options")[key] = value
            self._bake_book("_bake_origin")[key] = "default"
            super().__setattr__(key, value.default)
            return
        if not self._bake_frozen:
            self._bake_book("_bake_origin")[key] = "default"
            super().__setattr__(key, value)
            return
        if key not in dir(self):
            raise BakeConfigAttributeError(
                f"config.{self._bake_name()} has no attribute '{key}'"
                f"{_suggest(key, self._bake_attributes())}. "
                f"Known attributes: {_join(self._bake_attributes())}."
            )
        if key in self._bake_book("_bake_cli"):
            logging.debug("config.%s.%s: keeping the command line's %r, not %r",
                          self._bake_name(), key, getattr(self, key), value)
            return
        self._bake_check(key, value)
        self._bake_book("_bake_origin")[key] = "set"
        super().__setattr__(key, value)

    def _bake_attributes(self) -> list:
        return [a for a in dir(self) if not a.startswith("_") and not callable(getattr(self, a))]

    def _bake_option(self, key):
        """The Option declaring attribute key, or None."""
        return self._bake_book("_bake_options").get(key)

    def _bake_about(self, key) -> str:
        """' config.<section>.<key>: <description>.' of attribute key, or ''."""
        opt = self._bake_option(key)
        if not (opt and opt.desc):
            return ""
        return f" config.{self._bake_name()}.{key}: {opt.desc.rstrip('.')}."

    def _bake_check(self, key, value, what=None, error=BakeConfigError) -> None:
        """Stop if value does not fit the option that declares attribute key;
        the message starts with `what` (the -o that set it) when given."""
        opt = self._bake_option(key)
        if opt is None:
            return
        name = f"config.{self._bake_name()}.{key}"
        prefix = f"{what}: " if what else ""
        if not opt.accepts(value):
            raise error(
                f"{prefix}{name} takes {_kind_name(opt.kinds)}, not {_value_name(value)}."
                f"{self._bake_about(key)}"
            )
        if opt.choices is not None and value not in opt.choices:
            raise error(
                f"{prefix}{name} takes one of {_join(opt.choices)}, not {value!r}."
                f"{self._bake_about(key)}"
            )

    def _bake_kinds(self, key) -> tuple:
        """The kinds attribute key takes: its option's, or its value's."""
        opt = self._bake_option(key)
        if opt is not None and opt.kinds:
            return opt.kinds
        kind = _kind_of(getattr(self, key))
        return (kind,) if kind else (str,)

    def _bake_set_from_cli(self, key, raw, what) -> None:
        """Set attribute key from the command-line text raw, converted to its
        kind and checked; manifests cannot change it afterwards."""
        name = f"config.{self._bake_name()}.{key}"
        kinds = self._bake_kinds(key)
        if dict in kinds:
            raise BakeOptionError(
                f"{what}: {name} is a dictionary, which -o cannot set. Set its keys in a "
                f"manifest instead, e.g. {name}[\"name\"] = value."
            )
        value = _convert(raw, kinds)
        if value is _NOT_CONVERTED:
            raise BakeOptionError(
                f"{what}: {name} takes {_kind_name(kinds)}, not '{raw}'.{self._bake_about(key)}"
            )
        self._bake_check(key, value, what, BakeOptionError)
        object.__setattr__(self, key, value)
        self._bake_book("_bake_cli")[key] = value
        self._bake_book("_bake_origin")[key] = "-o"
        logging.debug("Config option applied: %s = %r", name, value)

    def _bake_set_from_flag(self, key, value) -> None:
        """Set attribute key from a command-line flag (-v, -t, -f, ...): an
        ordinary assignment, listed as coming from the command line when it
        is not the default."""
        setattr(self, key, value)
        opt = self._bake_option(key)
        default = opt.default if opt is not None else None
        self._bake_book("_bake_origin")[key] = "default" if value == default else "flag"

    def _bake_append_from_cli(self, key, raw) -> None:
        """Append the command-line text raw to list attribute key."""
        getattr(self, key).append(raw)
        self._bake_book("_bake_origin")[key] = "-o"
        logging.debug("Config option applied: config.%s.%s += %r", self._bake_name(), key, raw)


_NOT_CONVERTED = object()


def _convert(raw: str, kinds):
    """raw converted to the first of kinds it can be, or _NOT_CONVERTED.
    A string takes any text, so it is tried last."""
    for kind in sorted(kinds, key=lambda k: k is str):
        if kind is bool:
            if raw.lower() in _TRUE_WORDS:
                return True
            if raw.lower() in _FALSE_WORDS:
                return False
        elif kind in (int, float):
            try:
                return kind(raw)
            except ValueError:
                pass
        elif kind is str:
            return raw
    return _NOT_CONVERTED


class TemplateDictionary(dict):
    def __setitem__(self, key, value):
        if not key.startswith("BAKE_"):
            raise BakeConfigError(f"Template variable '{key}' doesn't begin with 'BAKE_'")

        if re.search(r"[^A-Z0-9_]", key) is not None:
            raise BakeConfigError(
                f"Template variable '{key}' can only contain upper case letters, numbers, and underscores"
            )

        if key in self:
            raise BakeConfigError(f"Cannot overwrite template variable '{key}'")

        super().__setitem__(key, value)


class BakeConfig(FixedSchemaAttributes):
    """Global bake settings: what manifests set (tpl_dict, file_copy_method,
    output_dir) and what the command line sets (the rest)."""

    _bake_section = "bake"

    def __init__(self):
        self.tpl_dict = TemplateDictionary()
        self.default_libs = option(
            [], "Libraries of every block that declares none (lib() names)")
        self.file_copy_method = option(
            "copy", "How flows are copied into a work directory", choices=["copy", "symlink"])
        self.options = option(
            [], "The command line's -o overrides, as given (regressions pass them on)")
        self.output_dir = option(
            None, "Directory of the work directories; the manifest's directory when unset", kind=str)
        self.manifest_dir = option(
            "", "The project's manifest directory (-m), absolute")
        self.verbosity = option(0, "Verbosity of bake and the flows (-v)")
        self.interactive = option(False, "Run flows interactively where they can (-i)")
        self.test = option(None, "The test to run (-t)", kind=str)
        self.force = option(False, "Run the recipe even when it is up to date (-f)")
        self.populate = option(False, "Copy the flow of the recipe's last step to customise it (-p)")
        self.clean = option(False, "Remove the recipe's work directory (-c)")
        self.restart = option(False, "Remove the recipe's work directory, then run it (-r)")
        self.dry_run = option(False, "Report what would run without running it (-n)")


class UserConfig:
    """Free-form attributes a project shares between its manifests and its
    own steps; no schema, set from the command line only once loaded."""


# What -o names: section.attribute=value
_OVERRIDE = re.compile(r'^([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)=(.*)$', re.DOTALL)
# A section exposed to the flows: its name goes into $BAKE_<SECTION>_<ATTR>
_TEMPLATE_SECTION = re.compile(r'^[a-z][a-z0-9_]*$')


class Override:
    """One -o section.attribute=value of the command line."""

    __slots__ = ("section", "attribute", "value", "text")

    def __init__(self, text: str):
        m = _OVERRIDE.match(text)
        if not m:
            hint = ("it has no '='" if "=" not in text else
                    "it names no section: write section.attribute" if "." not in text.split("=", 1)[0] else
                    "the section and the attribute take letters, digits and _ only")
            raise BakeOptionError(
                f"Malformed option '-o {text}': {hint}. -o takes section.attribute=value, "
                f"e.g. -o vrf.simulator=icarus."
            )
        self.section, self.attribute, self.value = m.groups()
        self.text = text

    @property
    def label(self) -> str:
        return f"Option '-o {self.text}'"


class Config:
    """Groups all user-facing configuration sections.

    bake and user are always present. Step-specific sections (impl, vrf, tmr, ...)
    are registered dynamically when step modules are discovered via build_registry();
    a project registers its own sections the same way.

    The command line's -o overrides are given before any manifest loads
    (set_overrides). Each one takes effect as soon as its section exists,
    when it is registered, so manifests see it while they load; a manifest
    assigning the attribute afterwards keeps the command line's value. List
    attributes get their items appended once every manifest has loaded,
    after the manifests' own (finish_overrides).
    """

    bake = BakeConfig()   # replaced by a fresh instance on every reset_sections()
    user = UserConfig()
    # Exposed for use in manifest exec scope
    TemplateDictionary = TemplateDictionary
    FixedSchemaAttributes = FixedSchemaAttributes
    Option = Option
    option = staticmethod(option)

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)

    # Per-run state, in the instance so reset_sections() drops it.
    def _bake_state(self, name, default):
        if name not in vars(self):
            object.__setattr__(self, name, default)
        return vars(self)[name]

    @property
    def _overrides(self) -> list:
        return self._bake_state("_bake_overrides", [])

    @property
    def _template_sections(self) -> list:
        return self._bake_state("_bake_templates", [])

    def register(self, name: str, section, templates: bool = False) -> None:
        """Register a config section by name. Idempotent.

        The command line's overrides of the section take effect at once.
        With templates=True every attribute of the section reaches every
        step's flow as $BAKE_<NAME>_<ATTRIBUTE> (upper case): a project's
        own settings, e.g. config.register("si3", Si3Config(), templates=True)
        gives $BAKE_SI3_PIXEL_PITCH."""
        if name in vars(self):
            return
        if templates and not _TEMPLATE_SECTION.match(name):
            raise BakeConfigError(
                f"config.register('{name}', ..., templates=True): a section that reaches the "
                f"flows needs a name of lower-case letters, digits and _, starting with a letter."
            )
        if isinstance(section, FixedSchemaAttributes):
            object.__setattr__(section, "_bake_section", name)
        object.__setattr__(self, name, section)
        if templates:
            self._template_sections.append(name)
        logging.debug("Registered config section '%s' (%s)", name, type(section).__name__)
        self.apply_overrides(name)

    def set_overrides(self, texts) -> None:
        """Take the command line's -o texts, checking their form; each takes
        effect when its section is registered (apply_overrides)."""
        self._overrides.extend(Override(t) for t in texts)

    def apply_overrides(self, name: str) -> None:
        """Apply the overrides of section name, but for list items, which
        finish_overrides appends."""
        section = getattr(self, name)
        for o in self._overrides:
            if o.section != name:
                continue
            if not isinstance(section, FixedSchemaAttributes):
                continue    # no schema to check against yet: finish_overrides sets it
            if o.attribute.startswith("_") or o.attribute not in section._bake_attributes():
                known = section._bake_attributes()
                raise BakeOptionError(
                    f"{o.label}: config.{name} has no attribute '{o.attribute}'"
                    f"{_suggest(o.attribute, known)}. Its attributes: {_join(known)} "
                    f"(`bake --list-options` describes them)."
                )
            if list in section._bake_kinds(o.attribute):
                continue
            section._bake_set_from_cli(o.attribute, o.value, o.label)

    def finish_overrides(self) -> None:
        """Once every manifest has loaded: stop on an override of a section
        that never appeared, append list items, and set the attributes of
        sections without a schema (user, or a step's plain object)."""
        sections = self._section_names()
        for o in self._overrides:
            if o.section not in sections:
                raise BakeOptionError(
                    f"{o.label}: unknown config section '{o.section}'"
                    f"{_suggest(o.section, sections)}. Sections: {_join(sections)} "
                    f"(`bake --list-options` lists their attributes)."
                )
        for o in self._overrides:
            section = getattr(self, o.section)
            if isinstance(section, FixedSchemaAttributes):
                if list in section._bake_kinds(o.attribute):
                    section._bake_append_from_cli(o.attribute, o.value)
                continue
            self._set_schemaless(section, o)

    @staticmethod
    def _set_schemaless(section, o) -> None:
        """An override of a section without a schema: the attribute must
        exist, and the value takes the current value's kind."""
        known = [a for a in dir(section) if not a.startswith("_") and not callable(getattr(section, a))]
        if o.attribute.startswith("_") or o.attribute not in known:
            raise BakeOptionError(
                f"{o.label}: config.{o.section} has no attribute '{o.attribute}'"
                f"{_suggest(o.attribute, known)}"
                + (f". Its attributes: {_join(known)}." if known else
                   ": a manifest has to assign it first.")
            )
        current = getattr(section, o.attribute)
        kind = _kind_of(current) or str
        if kind is list:
            current.append(o.value)
            return
        if kind is dict:
            raise BakeOptionError(
                f"{o.label}: config.{o.section}.{o.attribute} is a dictionary, which -o cannot "
                f"set. Set its keys in a manifest instead."
            )
        value = _convert(o.value, (kind,))
        if value is _NOT_CONVERTED:
            raise BakeOptionError(
                f"{o.label}: config.{o.section}.{o.attribute} takes {_KIND_NAMES[kind]}, "
                f"not '{o.value}'."
            )
        setattr(section, o.attribute, value)

    def template_vars(self) -> dict:
        """$BAKE_<SECTION>_<ATTRIBUTE> of the sections registered with
        templates=True: booleans as 1/0, lists as lists, dictionaries left
        out (their keys are the section's own business)."""
        out = {}
        for name in self._template_sections:
            section = getattr(self, name)
            for attr in self._attributes_of(section):
                value = getattr(section, attr)
                if isinstance(value, dict):
                    continue
                out[f"BAKE_{name.upper()}_{attr.upper()}"] = int(value) if isinstance(value, bool) else value
        return out

    @staticmethod
    def _attributes_of(section) -> list:
        if isinstance(section, FixedSchemaAttributes):
            return section._bake_attributes()
        return [a for a in dir(section) if not a.startswith("_") and not callable(getattr(section, a))]

    def describe(self) -> list:
        """What `bake --options` lists, section by section: (section,
        [(attribute, value, Option or None, origin)])."""
        out = []
        for name in self._section_names():
            section = getattr(self, name)
            rows = []
            for attr in self._attributes_of(section):
                value = getattr(section, attr)
                if isinstance(value, TemplateDictionary):
                    continue
                if isinstance(section, FixedSchemaAttributes):
                    opt = section._bake_option(attr)
                    origin = section._bake_book("_bake_origin").get(attr, "default")
                else:
                    opt, origin = None, "set"
                rows.append((attr, value, opt, origin))
            out.append((name, rows))
        return out

    def reset_sections(self) -> None:
        """Drop every dynamically registered section (impl, vrf, tmr, ...) and
        start `bake` from its defaults.

        The step manifests register their sections again on the next load, so
        each run starts clean; the CLI sets its options on the fresh `bake`
        afterwards. `user` is untouched: it holds free-form user attributes.
        """
        for name in list(vars(self)):
            delattr(self, name)
            if not name.startswith("_"):
                logging.debug("Dropped config section '%s'", name)
        Config.bake = BakeConfig()

    def __getattr__(self, key):
        sections = self._section_names()
        raise BakeConfigAttributeError(
            f"config has no section '{key}'{_suggest(key, sections)}. Sections: {_join(sections)}. "
            f"A project's own section exists once a manifest registers it with config.register()."
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
        self.config.reset_sections()
        self.flows = {}
        self.libs = {}    # LibSpec objects (PDK/foundry cell libraries)
        self.blocks = {}  # BlockSpec objects (user design blocks)
        self.envs = {}
        self.tests = []
        self.steps = {}

    def validate(self):
        """Check the declarations once every manifest has loaded.

        Includes may reference blocks and environments defined later, so
        their existence, the step names in include recipes, the absence of
        include cycles and the kinds of data they resolve to are verified
        here rather than at registration.
        Whether an included recipe has been *run* is not a manifest property;
        that is decided when a recipe is elaborated.
        """
        for name, b in self.blocks.items():
            for dep_name, recipe in b.includes.items():
                if dep_name not in self.blocks:
                    if dep_name in self.libs:
                        raise BakeManifestError(
                            f"Block '{name}' includes '{dep_name}', which is a lib(): a cell "
                            f"library is named in libs=, not included. Declare an implemented "
                            f"block to include with macro()."
                        )
                    raise BakeManifestError(
                        f"Block '{name}' includes unknown block '{dep_name}'"
                    )
                if recipe == "rtl":
                    continue
                for part in recipe.split("-"):
                    if part not in self.steps:
                        raise BakeManifestError(
                            f"Block '{name}' includes '{dep_name}' with recipe '{recipe}': "
                            f"unknown step '{part}'"
                        )

        for e in list(self.envs.values()) + self.tests:
            for dep_name in e.includes:
                if dep_name not in self.envs:
                    kind = "Test" if e.is_test else "Environment"
                    raise BakeManifestError(
                        f"{kind} '{e.name}' includes unknown environment '{dep_name}'"
                    )

        self._check_cycles(self.blocks, lambda b: b.includes, "Block")
        self._check_cycles(self.envs, lambda e: e.includes, "Environment")

        # Each include must reach a kind of data its block can take, through
        # steps that each take the kind before them: decided by the steps'
        # declared signatures, before anything is elaborated.
        from .step import include_kind  # pylint: disable=import-outside-toplevel  # step imports context
        for b in self.blocks.values():
            for dep_name, recipe in b.includes.items():
                include_kind(b, self.blocks[dep_name], recipe)

    @staticmethod
    def _check_cycles(registry, deps_of, kind):
        state = {}  # name -> "visiting" | "done"

        def visit(name, path):
            if state.get(name) == "done":
                return
            if state.get(name) == "visiting":
                cycle = path[path.index(name):] + [name]
                raise BakeManifestError(
                    f"{kind} include cycle: {' -> '.join(cycle)}"
                )
            state[name] = "visiting"
            for dep in deps_of(registry[name]):
                if dep in registry:
                    visit(dep, path + [name])
            state[name] = "done"

        for name in registry:
            visit(name, [])

    def libs_defined(self):
        return len(self.libs) > 0

    def blocks_defined(self):
        return len(self.blocks) > 0

    def flows_defined(self):
        return len(self.flows) > 0

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
        for name, cls in self.steps.items():
            signature = cls.signature()
            logging.info("- %s%s", name, f"  ({signature})" if signature else "")

    def log_tests(self, target_name=None):
        if target_name:
            logging.info("Available tests for block %s:", target_name)
            for t in self.find_test_by_target(target_name):
                logging.info("- %s", t.name)
        else:
            logging.info("Available tests:")
            for t in self.tests:
                logging.info("- %s", t.name)


    def log_libs(self):
        logging.info("Available libraries (PDK):")
        for name in self.libs:
            logging.info("- %s", name)
        logging.info("Available macros:")
        for name, b in self.blocks.items():
            if b.manifest_function == "macro":
                logging.info("- %s", name)


    def log_targets(self):
        logging.info("Available blocks:")
        for name, b in self.blocks.items():
            if not b.is_empty:
                logging.info("- %s", name)

context = Context()
