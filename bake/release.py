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

"""Releases: implemented blocks saved with what they are and where they come
from, to be used in place of building them.

A release is a directory <root>/<project>/<block>/<version>/ holding the
files of a LibData (the netlist and the abstracts: what a parent block needs
of an implemented one), a release.json describing them and a SHA256SUMS of
every file. It never changes once written. This module reads and writes that
format; the steps that make releases and use them build on it."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import exceptions
from .step import LibData

FORMAT = 1
RELEASE_JSON = "release.json"
CHECKSUMS = "SHA256SUMS"

# A version names a directory: no separators, nothing hidden
VERSION_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")

# The directory of a release root holding the releases of an unnamed project
UNNAMED_PROJECT = "_"


@dataclass(frozen=True)
class View:
    """One kind of file of a release: the LibData field holding it and its
    shape there."""
    name: str
    field: str
    # "list": [files]; "str": one file; "words": files joined by spaces;
    # "corners": {corner: [files]}; "corner": {corner: file}
    shape: str


VIEWS: dict[str, View] = {v.name: v for v in (
    View("netlist",      "netlist_files",    "list"),
    View("lef",          "layout_info",      "words"),
    View("liberty",      "liberty_files",    "corners"),
    View("si",           "si_files",         "corners"),
    View("sdf",          "sdf_files",        "corner"),
    View("def",          "def_file",         "str"),
    View("physical_lef", "physical_lef",     "str"),
    View("sdc",          "sdc_file",         "str"),
    View("spef",         "parasitics_files", "corner"),
    View("stream",       "stream_files",     "list"),
    View("lvs",          "lvs_files",        "list"),
)}


@dataclass
class Release:
    """What release.json says. `data` holds the LibData's views with paths
    relative to the release directory (see libdata_to_dict)."""
    block: str
    top: str
    version: str
    format: int = FORMAT
    label: str = ""
    created: str = ""
    project: dict = field(default_factory=lambda: {"name": "", "options": {}})
    recipe: str = ""
    producer: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    placeholders: list = field(default_factory=list)
    checks: dict = field(default_factory=lambda: {"integrity": {"status": "skipped"}, "quality": {}})
    sources: dict = field(default_factory=dict)

    @classmethod
    def read(cls, path: Path | str) -> "Release":
        """The release in directory `path` (or its release.json)."""
        path = Path(path)
        if path.is_dir():
            path = path / RELEASE_JSON
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as err:
            raise exceptions.BakeFileError(f"No release at {path.parent}: {RELEASE_JSON} is missing.") from err
        except ValueError as err:
            raise exceptions.BakeRuntimeError(f"Release {path.parent}: {RELEASE_JSON} is not JSON ({err}).") from err
        fmt = raw.get("format")
        if fmt != FORMAT:
            raise exceptions.BakeRuntimeError(
                f"Release {path.parent} is in format {fmt!r}; this bake reads format {FORMAT}. "
                f"Use the bake that wrote it, or a newer one."
            )
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            logging.debug("Release %s: ignoring unknown keys %s", path.parent, unknown)
        missing = [k for k in ("block", "top", "version") if not raw.get(k)]
        if missing:
            raise exceptions.BakeRuntimeError(
                f"Release {path.parent}: {RELEASE_JSON} lacks {', '.join(missing)}."
            )
        return cls(**{k: v for k, v in raw.items() if k in known})

    def write(self, directory: Path | str) -> Path:
        path = Path(directory) / RELEASE_JSON
        path.write_text(json.dumps(dataclasses.asdict(self), indent=2) + "\n", encoding="utf-8")
        return path

    @property
    def name(self) -> str:
        """How messages and waivers name it: <block>@<version>."""
        return f"{self.block}@{self.version}"

    def views(self) -> list[str]:
        """The views the release has files for, in VIEWS order."""
        return [v for v in VIEWS if _has_view(self.data, VIEWS[v])]


def _has_view(data: dict, view: View) -> bool:
    value = data.get(view.field)
    if view.shape == "corners":
        return any(value.values()) if value else False
    return bool(value)


# ---------------------------------------------------------------------------
# LibData <-> release data
# ---------------------------------------------------------------------------

def _view_files(data: LibData, view: View) -> list[tuple[str, str]]:
    """The files of one view of data as [(corner or "", path)]."""
    value = getattr(data, view.field)
    if view.shape == "list":
        return [("", f) for f in value]
    if view.shape == "str":
        return [("", value)] if value else []
    if view.shape == "words":
        return [("", f) for f in value.split()]
    if view.shape == "corners":
        return [(c, f) for c, files in value.items() for f in files]
    return [(c, f) for c, f in value.items() if f]   # corner


def libdata_files(data: LibData) -> dict[str, list[tuple[str, str]]]:
    """Every file of data's views, by view: {view: [(corner, path)]}; the
    views without a file are left out. Its macros are not included."""
    files = {name: _view_files(data, view) for name, view in VIEWS.items()}
    return {k: v for k, v in files.items() if v}


def copy_libdata(data: LibData, dest: Path, follow: Callable[[str], str] = os.path.realpath) -> dict:
    """Copy the files of data, and of the macros it places, recursively,
    into dest (a new release's directory, or a macro's under it): one
    directory per view, a subdirectory per corner for the views that have
    corners; the macros under macros/<block>/. Returns the release data:
    the views with paths relative to dest, the netlist include directories,
    the libraries by name, the simulation defines and the macros.

    A file that does not exist is an error naming its view."""
    dest = Path(dest)
    taken: set[Path] = set()

    def place(view: str, corner: str, src: str) -> str:
        source = Path(follow(src))
        if not source.is_file():
            raise exceptions.BakeFileError(
                f"Block '{data.block}': its {view} file {src} does not exist."
            )
        # The name it is given (a link's), the contents of what it points to
        name = Path(src).name
        folder = Path(view if view != "physical_lef" else "lef") / corner
        target = folder / name
        n = 1
        while target in taken:
            target = folder / f"{n}_{name}"
            n += 1
        taken.add(target)
        (dest / folder).mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest / target)
        return target.as_posix()

    out: dict[str, Any] = {}
    for name, view in VIEWS.items():
        value = getattr(data, view.field)
        if view.shape == "list":
            out[view.field] = [place(name, "", f) for f in value]
        elif view.shape == "str":
            out[view.field] = place(name, "", value) if value else ""
        elif view.shape == "words":
            out[view.field] = " ".join(place(name, "", f) for f in value.split())
        elif view.shape == "corners":
            out[view.field] = {c: [place(name, c, f) for f in files] for c, files in value.items()}
        else:
            out[view.field] = {c: place(name, c, f) for c, f in value.items() if f}

    incdirs = []
    for i, src in enumerate(data.netlist_incdirs):
        target = Path("netlist") / "incdirs" / str(i)
        shutil.copytree(follow(src), dest / target, symlinks=False)
        incdirs.append(target.as_posix())
    out["netlist_incdirs"] = incdirs
    out["libs"] = [lib.name for lib in data.libs]
    out["vrf_defines"] = list(data.vrf_defines)

    macros = []
    for macro in data.macros:
        sub = Path("macros") / macro.block
        macro_data = copy_libdata(macro, dest / sub, follow)
        macros.append({"block": macro.block, "top": macro.top, "dir": sub.as_posix(), **macro_data})
    out["macros"] = macros
    return out


def libdata_to_json(data: LibData) -> dict:
    """data's views, absolute paths as they are, its libraries by name and
    its macros, recursively, for a flow to hand to `bake-release pack`."""
    out: dict[str, Any] = {"block": data.block, "top": data.top}
    for view in VIEWS.values():
        value = getattr(data, view.field)
        if isinstance(value, (dict, list)):
            value = type(value)(value)
        out[view.field] = value
    out["netlist_incdirs"] = list(data.netlist_incdirs)
    out["vrf_defines"] = list(data.vrf_defines)
    out["libs"] = [lib.name for lib in data.libs]
    out["macros"] = [libdata_to_json(m) for m in data.macros]
    return out


def libdata_from_dict(raw: dict, directory: Path, block: str, top: str,
                      resolve_lib: Callable[[str], Any], owner: str) -> LibData:
    """The LibData of release data `raw` (copy_libdata's result) whose paths
    are relative to `directory`: paths made absolute, libraries resolved by
    name with resolve_lib (which raises for an unknown one), macros
    recursively. `owner` names the release in messages."""
    directory = Path(directory)

    def absolute(path: str) -> str:
        return str(directory / path)

    fields: dict[str, Any] = {}
    for view in VIEWS.values():
        value = raw.get(view.field)
        if view.shape == "list":
            fields[view.field] = [absolute(f) for f in value or []]
        elif view.shape == "str":
            fields[view.field] = absolute(value) if value else ""
        elif view.shape == "words":
            fields[view.field] = " ".join(absolute(f) for f in (value or "").split())
        elif view.shape == "corners":
            fields[view.field] = {c: [absolute(f) for f in files] for c, files in (value or {}).items()}
        else:
            fields[view.field] = {c: absolute(f) for c, f in (value or {}).items()}

    libs = []
    for name in raw.get("libs", []):
        try:
            libs.append(resolve_lib(name))
        except KeyError as err:
            raise exceptions.BakeManifestError(
                f"Release {owner} is mapped to library '{name}', which is not declared: declare it "
                f"with lib(), or select a release built with the libraries this project has."
            ) from err

    macros = [
        libdata_from_dict(m, directory / m["dir"], m["block"], m.get("top", ""), resolve_lib,
                          f"{owner} (macro {m['block']})")
        for m in raw.get("macros", [])
    ]
    return LibData(
        block=block, block_dir=str(directory), top=top,
        netlist_incdirs=[absolute(d) for d in raw.get("netlist_incdirs", [])],
        vrf_defines=list(raw.get("vrf_defines", [])),
        libs=libs, macros=macros, **fields,
    )


# ---------------------------------------------------------------------------
# Finding releases
# ---------------------------------------------------------------------------

def block_dir(root: Path | str, project: str, block: str) -> Path:
    return Path(root) / (project or UNNAMED_PROJECT) / block


def versions(roots: list, project: str, block: str) -> list[tuple[str, Path]]:
    """The releases of block on the search path: [(version, directory)],
    sorted by version, a version found under several roots listed once (the
    first root's). Unfinished releases (.<version>.tmp) are left out."""
    found: dict[str, Path] = {}
    for root in roots:
        folder = block_dir(root, project, block)
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.name.startswith(".") or not (entry / RELEASE_JSON).is_file():
                continue
            if entry.name in found:
                _warn_if_different(found[entry.name], entry)
                continue
            found[entry.name] = entry
    return sorted(found.items())


def find(roots: list, project: str, block: str, version: str) -> Optional[Path]:
    """The directory of block's release `version`: the first root holding
    it, or None."""
    hits = [block_dir(r, project, block) / version for r in roots]
    hits = [h for h in hits if (h / RELEASE_JSON).is_file()]
    for other in hits[1:]:
        _warn_if_different(hits[0], other)
    return hits[0] if hits else None


def _warn_if_different(first: Path, other: Path) -> None:
    a, b = first / CHECKSUMS, other / CHECKSUMS
    if a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes():
        return
    logging.warning("Release %s exists under two roots with different contents; using %s, not %s.",
                    first.name, first, other)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def source_digests(steps: list, root: Path | str) -> dict[str, str]:
    """{path relative to root: sha256} of what the steps were built from:
    their source files and the files of the flows they run. Files outside
    root (a PDK, an installed flow) are left out: the release records the
    project's own sources, to tell later whether it is older than them."""
    root = Path(root).resolve()
    files: set[Path] = set()
    for s in steps:
        candidates = [Path(f) for f in s.source_files]
        try:
            flowdir = Path(s.flowdir)
            if flowdir.is_dir():
                candidates += [p for p in flowdir.rglob("*") if p.is_file()]
        except exceptions.BakeRuntimeError:
            pass
        for f in candidates:
            path = f.resolve()
            if path.is_file() and path.is_relative_to(root):
                files.add(path)
    return {p.relative_to(root).as_posix(): _sha256(p) for p in sorted(files)}


def stale_sources(recorded: dict[str, str], current: dict[str, str]) -> list[str]:
    """The sources that changed, appeared or disappeared since a release
    recorded `recorded`, sorted."""
    names = set(recorded) | set(current)
    return sorted(n for n in names if recorded.get(n) != current.get(n))


# ---------------------------------------------------------------------------
# Checksums and protection
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_files(directory: Path) -> list[Path]:
    return sorted(p.relative_to(directory) for p in directory.rglob("*")
                  if p.is_file() and p.name != CHECKSUMS)


def write_checksums(directory: Path | str) -> Path:
    """SHA256SUMS of every file of the release but itself, sha256sum's format."""
    directory = Path(directory)
    lines = [f"{_sha256(directory / p)}  {p.as_posix()}\n" for p in _release_files(directory)]
    path = directory / CHECKSUMS
    path.write_text("".join(lines), encoding="utf-8")
    return path


def verify_checksums(directory: Path | str) -> list[str]:
    """The files of the release that do not match SHA256SUMS: changed,
    missing, or not listed. Empty when it is intact."""
    directory = Path(directory)
    path = directory / CHECKSUMS
    if not path.is_file():
        return [CHECKSUMS]
    listed = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            listed[name.strip()] = digest
    bad = [name for name, digest in listed.items()
           if not (directory / name).is_file() or _sha256(directory / name) != digest]
    bad += [p.as_posix() for p in _release_files(directory) if p.as_posix() not in listed]
    return sorted(bad)


def make_read_only(directory: Path | str) -> None:
    """Remove the write permission of everything in directory, itself included."""
    directory = Path(directory)
    write = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    for path in sorted(directory.rglob("*"), reverse=True) + [directory]:
        mode = path.stat().st_mode
        path.chmod(mode & ~write)
