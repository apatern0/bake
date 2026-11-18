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

"""bake-release: make and check releases without a bake project.

    bake-release pack --block adc --top adc_top --project chip --lef adc.lef \\
                      --liberty TT=adc_tt.lib --netlist adc.v --root /shared/releases

writes a release of block adc (see docs/release_format.md) from the files
given, for a project to include with {"adc": "release"}. The publish step
of bake makes its releases with the same command (pack --from-vars)."""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import coloredlogs

from . import exceptions, release
from .step import LibData, bake_version


# ---------------------------------------------------------------------------
# What pack is given
# ---------------------------------------------------------------------------

def _corner_pairs(values: list, flag: str) -> list[tuple[str, str]]:
    pairs = []
    for value in values or []:
        corner, sep, path = value.partition("=")
        if not sep or not corner or not path:
            raise exceptions.BakeRuntimeError(f"{flag} {value}: give CORNER=FILE, e.g. {flag} TT=block_tt.lib")
        pairs.append((corner, path))
    return pairs


def _option_value(text: str) -> Any:
    """A project option's value as JSON when it reads as JSON (8, true,
    [1, 2]), as the text otherwise."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def _libdata_from_args(args) -> LibData:
    """The views given on the command line, as a LibData."""
    liberty: dict = {}
    for corner, path in _corner_pairs(args.liberty, "--liberty"):
        liberty.setdefault(corner, []).append(path)
    si: dict = {}
    for corner, path in _corner_pairs(args.si, "--si"):
        si.setdefault(corner, []).append(path)
    return LibData(
        block=args.block, top=args.top,
        netlist_files=list(args.netlist or []),
        layout_info=" ".join(args.lef or []),
        liberty_files=liberty,
        si_files=si,
        sdf_files=dict(_corner_pairs(args.sdf, "--sdf")),
        def_file=args.def_file or "",
        physical_lef=args.physical_lef or "",
        sdc_file=args.sdc or "",
        parasitics_files=dict(_corner_pairs(args.spef, "--spef")),
        stream_files=list(args.stream or []),
        lvs_files=list(args.lvs or []),
        libs=[SimpleNamespace(name=n) for n in args.lib or []],
    )


def libdata_from_json(raw: dict) -> LibData:
    """A LibData as release.libdata_to_json() wrote it."""
    fields = {k: v for k, v in raw.items() if k not in ("libs", "macros")}
    return LibData(
        libs=[SimpleNamespace(name=n) for n in raw.get("libs", [])],
        macros=[libdata_from_json(m) for m in raw.get("macros", [])],
        **fields,
    )


# ---------------------------------------------------------------------------
# pack
# ---------------------------------------------------------------------------

def default_version(git: Optional[dict] = None, now: Optional[datetime.datetime] = None) -> str:
    """<date>-<short commit>[-dirty] with a git state, <date>-<time> otherwise."""
    now = now or datetime.datetime.now()
    if git and git.get("commit"):
        return f"{now:%Y%m%d}-{git['commit'][:7]}" + ("-dirty" if git.get("dirty") else "")
    return f"{now:%Y%m%d-%H%M%S}"


def _check_placeholders(placeholders: list, rel_data: dict) -> list[str]:
    errors = []
    for item in placeholders:
        name, _, corner = item.partition(".")
        view = release.VIEWS.get(name) or next((v for v in release.VIEWS.values() if v.field == name), None)
        if view is None:
            errors.append(f"placeholder {item}: no view {name} (views: {', '.join(release.VIEWS)})")
            continue
        value = rel_data.get(view.field)
        if not value or (corner and (not isinstance(value, dict) or corner not in value)):
            errors.append(f"placeholder {item}: the release has no such file")
    return errors


def integrity_errors(directory: Path, rel: release.Release) -> list[str]:  # pylint: disable=unused-argument
    """What makes the release unusable: no view at all, a placeholder that
    names no file of it."""
    errors = []
    if not rel.views():
        errors.append("the release has no view: give at least one file (--lef, --netlist, ...)")
    return errors + _check_placeholders(rel.placeholders, rel.data)


def pack(libdata: LibData, *, project: str, options: dict, version: str, root: Optional[str] = None,
         out: Optional[str] = None, label: str = "", recipe: str = "", producer: Optional[dict] = None,
         placeholders: Optional[list] = None, quality: Optional[dict] = None,
         reports: Optional[list] = None, sources: Optional[dict] = None) -> Path:
    """Write a release of libdata and return its directory: under
    root/<project>/<block>/<version>, or in out. Written in a hidden
    directory beside it, then renamed, then made read-only; refused when
    the release exists or fails its integrity checks."""
    if not release.VERSION_RE.match(version):
        raise exceptions.BakeRuntimeError(
            f"Version {version!r}: a version takes letters, digits and . _ -, and does not start "
            f"with . or -."
        )
    if bool(root) == bool(out):
        raise exceptions.BakeRuntimeError("Give where the release goes: a release root, or an output directory.")
    final = release.block_dir(root, project, libdata.block) / version if root else Path(out)  # type: ignore[arg-type]
    if final.exists():
        raise exceptions.BakeRuntimeError(
            f"Release {libdata.block}@{version} exists ({final}): a release never changes. "
            f"Give another version."
        )
    tmp = final.parent / f".{final.name}.tmp"
    if tmp.exists():
        _make_writable(tmp)
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        data = release.copy_libdata(libdata, tmp)
        for report in reports or []:
            (tmp / "reports").mkdir(exist_ok=True)
            shutil.copy2(report, tmp / "reports" / Path(report).name)
        rel = release.Release(
            block=libdata.block, top=libdata.top, version=version, label=label,
            created=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            project={"name": project, "options": dict(options)},
            recipe=recipe,
            producer={"bake_version": bake_version(), **(producer or {})},
            data=data,
            placeholders=list(placeholders or []),
            sources=dict(sources or {}),
        )
        errors = integrity_errors(tmp, rel)
        if errors:
            raise exceptions.BakeRuntimeError(
                f"Release {rel.name} fails its integrity checks:\n" + "\n".join(f"   - {e}" for e in errors)
            )
        rel.checks = {"integrity": {"status": "pass", "details": []}, "quality": dict(quality or {})}
        rel.write(tmp)
        release.write_checksums(tmp)
        tmp.rename(final)
    except BaseException:
        _make_writable(tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    release.make_read_only(final)
    logging.info("Released %s@%s in %s", libdata.block, version, final)
    return final


def _make_writable(directory: Path) -> None:
    for path in [directory, *directory.rglob("*")]:
        try:
            path.chmod(path.stat().st_mode | 0o200)
        except OSError:
            pass


def _read_json(path: Optional[str], what: str) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise exceptions.BakeRuntimeError(f"{what} {path}: {err}") from err


def cmd_pack(args) -> int:
    from_vars = _read_json(args.from_vars, "--from-vars")
    if from_vars:
        libdata = libdata_from_json(from_vars["BAKE_PUBLISH_LIBDATA"])
        extra = _libdata_from_args(argparse.Namespace(**{**vars(args), "block": libdata.block,
                                                          "top": libdata.top}))
        libdata.stream_files += extra.stream_files
        libdata.lvs_files += extra.lvs_files
        project = from_vars["BAKE_PUBLISH_PROJECT"]["name"]
        options = from_vars["BAKE_PUBLISH_PROJECT"]["options"]
        version = args.version or from_vars["BAKE_PUBLISH_VERSION"]
        root = args.root or from_vars["BAKE_PUBLISH_ROOT"]
        label = args.label or from_vars.get("BAKE_PUBLISH_LABEL", "")
        recipe = from_vars.get("BAKE_PUBLISH_RECIPE", "")
        producer = {"kind": "publish", "git": from_vars.get("BAKE_PUBLISH_GIT") or {}}
        sources = from_vars.get("BAKE_PUBLISH_SOURCES") or {}
        out = None
    else:
        missing = [f"--{n}" for n in ("block", "top", "project") if getattr(args, n) is None]
        if missing:
            raise exceptions.BakeRuntimeError(f"pack needs {', '.join(missing)} (or --from-vars).")
        libdata = _libdata_from_args(args)
        project, root, out = args.project, args.root, args.out
        options = {}
        for item in args.option or []:
            key, sep, value = item.partition("=")
            if not sep or not key:
                raise exceptions.BakeRuntimeError(f"--option {item}: give NAME=VALUE")
            options[key] = _option_value(value)
        version = args.version or default_version()
        label, recipe, sources = args.label or "", "", _read_json(args.sources_json, "--sources-json")
        producer = {"kind": "pack"}
    notes = {}
    for item in args.provenance or []:
        key, _, value = item.partition("=")
        notes[key] = value
    if notes:
        producer["notes"] = notes
    quality = _read_json(args.checks_json, "--checks-json")
    final = pack(libdata, project=project, options=options, version=version, root=root, out=out,
                 label=label, recipe=recipe, producer=producer, placeholders=args.placeholder,
                 quality=quality, reports=args.report, sources=sources)
    if args.published_json:
        Path(args.published_json).write_text(
            json.dumps({"block": libdata.block, "version": version, "path": str(final)}, indent=2) + "\n",
            encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="bake-release", description="Make and check releases of implemented blocks.")
    top.add_argument("-v", "--verbose", action="store_true")
    sub = top.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pack", help="Write a release from the files of a block",
                       description="Write a release of a block from its files: under a release root "
                                   "(--root), or in a directory of its own (--out).")
    what = p.add_argument_group("the block")
    what.add_argument("--block", help="The block's name, as the projects that include it name it")
    what.add_argument("--top", help="Its top unit (module, cell)")
    what.add_argument("--project", help="The project it is made for")
    what.add_argument("--option", action="append", metavar="NAME=VALUE",
                      help="A value of the project's options it was made with (repeatable)")
    where = p.add_argument_group("where it goes")
    where.add_argument("--root", help="A release root: the release goes in <root>/<project>/<block>/<version>")
    where.add_argument("--out", help="The release's own directory (to hand it over)")
    where.add_argument("--version", help="Default: <date>-<commit> for a publish, <date>-<time> otherwise")
    where.add_argument("--label", help="A note shown with the release")
    views = p.add_argument_group("its views (see docs/release_format.md)")
    views.add_argument("--netlist", action="append", metavar="FILE")
    views.add_argument("--lef", action="append", metavar="FILE")
    views.add_argument("--liberty", action="append", metavar="CORNER=FILE")
    views.add_argument("--si", action="append", metavar="CORNER=FILE")
    views.add_argument("--sdf", action="append", metavar="CORNER=FILE")
    views.add_argument("--def", dest="def_file", metavar="FILE")
    views.add_argument("--physical-lef", metavar="FILE")
    views.add_argument("--sdc", metavar="FILE")
    views.add_argument("--spef", action="append", metavar="CORNER=FILE")
    views.add_argument("--stream", action="append", metavar="FILE", help="Layout (GDS, OASIS)")
    views.add_argument("--lvs", action="append", metavar="FILE", help="Netlist for LVS (CDL, SPICE)")
    views.add_argument("--lib", action="append", metavar="NAME", help="A cell library its netlist is mapped to")
    views.add_argument("--placeholder", action="append", metavar="VIEW[.CORNER]",
                       help="A view holding a stand-in, not the real thing (repeatable)")
    more = p.add_argument_group("what it comes with")
    more.add_argument("--checks-json", metavar="FILE",
                      help="Its quality checks: {check: {status, value, report}}")
    more.add_argument("--report", action="append", metavar="FILE", help="A report kept in reports/")
    more.add_argument("--provenance", action="append", metavar="KEY=VALUE",
                      help="Where it comes from (a library, a cell view, a date), kept with it")
    more.add_argument("--sources-json", metavar="FILE", help="{path: sha256} of what it was made from")
    more.add_argument("--from-vars", metavar="BAKE_VARS",
                      help="The bake_vars.json of a publish step: the block, its views and where it goes")
    more.add_argument("--published-json", metavar="FILE", help="Write {block, version, path} here")
    p.set_defaults(func=cmd_pack)
    return top


def main(argv: Optional[list] = None) -> int:
    coloredlogs.install(fmt="[bake-release] %(levelname)s\t %(message)s")
    args = parser().parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        return args.func(args)
    except exceptions.BakeRuntimeError as err:
        logging.error("%s", err)
        return 1


if __name__ == "__main__":
    sys.exit(main())
