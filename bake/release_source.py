# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
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

"""The source file of an external block: an INI file its makers fill in
once, saying where its views are, which `bake <block> publish` reads to
make a release of them (see docs/release_format.md#source-files).

    [block]
    name = adc
    top = adc_top

    [views]
    lef = export/adc.lef
    netlist = export/adc.v

    [liberty]
    TT = export/adc_tt.lib

Paths are relative to the file, and may use ~ and $VARIABLES; a key taking
several values takes them separated by spaces or new lines (quote a path
with spaces)."""

from __future__ import annotations

import configparser
import difflib
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from . import exceptions
from .step import LibData

# Its sections and their keys; a section mapping to None takes any key (a
# corner, a note).
SECTIONS = {
    "block": ("name", "top", "placeholders"),
    "views": ("netlist", "lef", "def", "physical_lef", "sdc", "stream", "lvs", "libs"),
    "liberty": None,
    "si": None,
    "sdf": None,
    "spef": None,
    "provenance": None,
}

# The key of the source file each LibData field comes from, for messages.
_KEYS = {
    "netlist_files": "[views] netlist", "layout_info": "[views] lef", "def_file": "[views] def",
    "physical_lef": "[views] physical_lef", "sdc_file": "[views] sdc", "stream_files": "[views] stream",
    "lvs_files": "[views] lvs", "liberty_files": "[liberty]", "si_files": "[si]", "sdf_files": "[sdf]",
    "parasitics_files": "[spef]",
}


@dataclass
class Source:
    """What a source file says: the block's views (absolute paths), the
    views holding a stand-in, and notes on where the block comes from."""
    path: Path
    name: str
    top: str
    libdata: LibData
    placeholders: list[str] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)

    def files(self) -> list[tuple[str, str]]:
        """(key, path) of every file it names, the key as the file writes it."""
        result = []
        for attr, key in _KEYS.items():
            value = getattr(self.libdata, attr)
            if isinstance(value, dict):
                for corner, files in value.items():
                    result += [(f"{key} {corner}", f) for f in ([files] if isinstance(files, str) else files)]
            elif isinstance(value, list):
                result += [(key, f) for f in value]
            elif value:
                result += [(key, f) for f in value.split()] if attr == "layout_info" else [(key, value)]
        return result

    def missing(self) -> list[str]:
        """The files it names that do not exist, with their key."""
        return [f"{key}: {path}" for key, path in self.files() if not os.path.isfile(path)]


class _Ini:
    def __init__(self, path: Path):
        self.path = path
        ini = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";", "#"),
                                        empty_lines_in_values=False)
        ini.optionxform = str  # type: ignore[assignment,method-assign]  # keep corners as written
        try:
            with open(path, encoding="utf-8") as f:
                ini.read_file(f)
        except (OSError, configparser.Error) as err:
            raise exceptions.BakeManifestError(f"Source file {path}: {err}") from err
        self.sections: dict[str, dict[str, str]] = {}
        for name in ini.sections():
            if name not in SECTIONS:
                raise self.error(f"unknown section [{name}]" + _hint(name, SECTIONS))
            keys = SECTIONS[name]
            for key in ini[name]:
                if keys is not None and key not in keys:
                    raise self.error(f"unknown key {key} in [{name}]" + _hint(key, keys))
            self.sections[name] = {k: v.strip() for k, v in ini[name].items()}

    def error(self, message: str) -> exceptions.BakeManifestError:
        return exceptions.BakeManifestError(f"Source file {self.path}: {message}")

    def text(self, section: str, key: str) -> str:
        return self.sections.get(section, {}).get(key, "")

    def words(self, section: str, key: str) -> list[str]:
        try:
            return shlex.split(self.text(section, key))
        except ValueError as err:
            raise self.error(f"[{section}] {key}: {err}") from err

    def files(self, section: str, key: str) -> list[str]:
        return [os.path.normpath(self.path.parent / os.path.expanduser(os.path.expandvars(w)))
                for w in self.words(section, key)]

    def file(self, section: str, key: str) -> str:
        files = self.files(section, key)
        if len(files) > 1:
            raise self.error(f"[{section}] {key}: give one file")
        return files[0] if files else ""

    def corners(self, section: str, single: bool = False) -> dict:
        result: dict = {}
        for corner in self.sections.get(section, {}):
            files = self.files(section, corner)
            if single and len(files) != 1:
                raise self.error(f"[{section}] {corner}: give one file per corner")
            result[corner] = files[0] if single else files
        return result


def _hint(name: str, known) -> str:
    close = difflib.get_close_matches(name, list(known), n=1)
    return f" (did you mean {close[0]!r}?)" if close else f" (known: {', '.join(known)})"


def read(path: str | Path) -> Source:
    """The source file at path. Raises BakeManifestError for a file that
    does not read, an unknown section or key, a missing name or top."""
    ini = _Ini(Path(path).absolute())
    name, top = ini.text("block", "name"), ini.text("block", "top")
    missing = [k for k, v in (("name", name), ("top", top)) if not v]
    if missing:
        raise ini.error(f"[block] needs {' and '.join(missing)}")
    libdata = LibData(
        block=name, top=top,
        netlist_files=ini.files("views", "netlist"),
        layout_info=" ".join(ini.files("views", "lef")),
        liberty_files=ini.corners("liberty"),
        si_files=ini.corners("si"),
        sdf_files=ini.corners("sdf", single=True),
        def_file=ini.file("views", "def"),
        physical_lef=ini.file("views", "physical_lef"),
        sdc_file=ini.file("views", "sdc"),
        parasitics_files=ini.corners("spef", single=True),
        stream_files=ini.files("views", "stream"),
        lvs_files=ini.files("views", "lvs"),
        libs=[SimpleNamespace(name=n) for n in ini.words("views", "libs")],
    )
    return Source(path=ini.path, name=name, top=top, libdata=libdata,
                  placeholders=ini.words("block", "placeholders"),
                  provenance=dict(ini.sections.get("provenance", {})))
