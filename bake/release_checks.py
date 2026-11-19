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

"""The checks of a release that need no tool: whether its views agree with
each other (integrity), what a profile says the release must hold (uses),
and the report of both.

The parsers read only what the checks need: the ports of the top unit in a
Verilog netlist, a LEF macro, a Liberty cell and a SPICE/CDL subcircuit.
Bus bits (a[3], a<3>) count as their bus (a)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import exceptions, release

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

DIRECTIONS = {"input": "input", "output": "output", "inout": "inout"}


@dataclass
class Ports:
    """The ports of the top unit in one view: {bus or pin: direction or ""},
    and the power pins, which the signal ports leave out."""
    view: str
    file: str
    signals: dict = field(default_factory=dict)
    power: set = field(default_factory=set)


def _base(name: str) -> str:
    """A bus bit's bus: a[3], a<3> and a are all a."""
    return re.sub(r"[\[<].*$", "", name.strip().strip("\\"))


def _strip_comments(text: str, line: str, block: Optional[tuple] = None) -> str:
    if block:
        text = re.sub(re.escape(block[0]) + r".*?" + re.escape(block[1]), " ", text, flags=re.S)
    return re.sub(line + r".*", "", text)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def verilog_ports(text: str, top: str) -> Optional[dict]:
    """{port: direction} of module `top`, ANSI or not; None without it."""
    text = _strip_comments(text, r"//", ("/*", "*/"))
    m = re.search(r"\bmodule\s+" + re.escape(top) + r"\b\s*(#\s*\(.*?\)\s*)?(\((.*?)\))?\s*;(.*?)\bendmodule\b",
                  text, re.S)
    if not m:
        return None
    header, body = m.group(3) or "", m.group(4)
    ports: dict = {}
    direction = ""
    for item in header.split(","):
        words = item.replace("[", " [").split()
        if not words:
            continue
        for w in words:
            if w in DIRECTIONS:
                direction = w
        names = re.sub(r"\[.*?\]", "", item).split()
        if names:
            ports[_base(names[-1])] = direction
    for decl in re.finditer(r"\b(input|output|inout)\b([^;]*);", body):
        for word in re.sub(r"\[.*?\]", " ", decl.group(2)).replace(",", " ").split():
            if word not in ("wire", "reg", "logic", "signed", "var", "tri"):
                ports[_base(word)] = decl.group(1)
    return ports


def lef_ports(text: str, top: str) -> tuple[Optional[dict], set, Optional[tuple]]:
    """({pin: direction}, power pins, (width, height)) of macro `top`;
    (None, set(), None) without it."""
    text = _strip_comments(text, r"#")
    m = re.search(r"^\s*MACRO\s+" + re.escape(top) + r"\s*$(.*?)^\s*END\s+" + re.escape(top) + r"\s*$",
                  text, re.S | re.M)
    if not m:
        return None, set(), None
    body = m.group(1)
    size = re.search(r"^\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", body, re.M)
    signals, power = {}, set()
    for pin in re.finditer(r"^\s*PIN\s+(\S+)\s*$(.*?)^\s*END\s+\1\s*$", body, re.S | re.M):
        name, pin_body = pin.group(1), pin.group(2)
        use = re.search(r"^\s*USE\s+(\w+)", pin_body, re.M)
        if use and use.group(1).upper() in ("POWER", "GROUND"):
            power.add(_base(name))
            continue
        d = re.search(r"^\s*DIRECTION\s+(\w+)", pin_body, re.M)
        signals[_base(name)] = DIRECTIONS.get(d.group(1).lower(), "") if d else ""
    return signals, power, (float(size.group(1)), float(size.group(2))) if size else None


def _liberty_group(text: str, kind: str, name: str) -> Optional[str]:
    """The body of group `kind (name) { ... }`, braces balanced; None
    without it."""
    m = re.search(r"\b" + kind + r"\s*\(\s*\"?" + re.escape(name) + r"\"?\s*\)\s*\{", text)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    if depth:
        raise exceptions.BakeRuntimeError(f"its braces do not balance after {kind}({name})")
    return text[m.end():i - 1]


def liberty_ports(text: str, top: str) -> tuple[Optional[dict], set]:
    """({pin or bus: direction}, power pins) of cell `top`; (None, set())
    without it. Raises when the file does not parse."""
    text = _strip_comments(text, r"//", ("/*", "*/"))
    if text.count("{") != text.count("}"):
        raise exceptions.BakeRuntimeError("its braces do not balance")
    body = _liberty_group(text, "cell", top)
    if body is None:
        return None, set()
    signals: dict = {}
    power: set = set()
    for kind in ("pin", "bus"):
        for m in re.finditer(r"\b" + kind + r"\s*\(\s*\"?([^\")]+)\"?\s*\)\s*\{", body):
            group = _liberty_group(body[m.start():], kind, m.group(1)) or ""
            d = re.search(r"\bdirection\s*:\s*\"?(\w+)", group)
            name = _base(m.group(1))
            direction = DIRECTIONS.get(d.group(1), "") if d else ""
            if direction or name not in signals:
                signals[name] = direction or signals.get(name, "")
    for m in re.finditer(r"\bpg_pin\s*\(\s*\"?([^\")]+)\"?\s*\)", body):
        power.add(_base(m.group(1)))
    return signals, power


def spice_ports(text: str, top: str) -> Optional[list]:
    """The ports of subcircuit `top`; None without it."""
    lines: list = []
    for line in text.splitlines():
        if line.startswith("+") and lines:
            lines[-1] += " " + line[1:]
        elif not line.startswith("*"):
            lines.append(line)
    for line in lines:
        words = line.split()
        if len(words) >= 2 and words[0].upper() == ".SUBCKT" and words[1] == top:
            return [_base(w) for w in words[2:] if "=" not in w and w != "/"]
    return None


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    if path.suffix == ".gz":
        import gzip  # pylint: disable=import-outside-toplevel
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            return f.read()
    return path.read_text(encoding="utf-8", errors="replace")


def view_ports(directory: Path, data: dict, top: str) -> tuple[list[Ports], list[str]]:
    """The ports of `top` in each view that declares them, and the errors
    of the views that should and do not (a LEF without the macro, a Liberty
    file without the cell or that does not parse)."""
    found: list[Ports] = []
    errors: list[str] = []

    def files(field_name):
        value = data.get(field_name)
        if isinstance(value, str):
            return value.split()
        if isinstance(value, dict):
            return [f for v in value.values() for f in (v if isinstance(v, list) else [v])]
        return list(value or [])

    netlists = files("netlist_files")
    if netlists:
        hits = []
        for f in netlists:
            ports = verilog_ports(_read(directory / f), top)
            if ports is not None:
                hits.append(Ports("netlist", f, ports))
        if hits:
            found.append(hits[0])
        else:
            errors.append(f"netlist: no module {top} in {', '.join(netlists)}")
    for f in files("layout_info"):
        if not f.lower().endswith(".lef"):
            continue
        signals, power, _ = lef_ports(_read(directory / f), top)
        if signals is None:
            errors.append(f"lef: no MACRO {top} in {f}")
        else:
            found.append(Ports("lef", f, signals, power))
    for f in files("liberty_files"):
        try:
            signals, power = liberty_ports(_read(directory / f), top)
        except exceptions.BakeRuntimeError as err:
            errors.append(f"liberty: {f} does not parse: {err}")
            continue
        if signals is None:
            errors.append(f"liberty: no cell {top} in {f}")
        else:
            found.append(Ports("liberty", f, signals, power))
    for f in files("lvs_files"):
        subckt = spice_ports(_read(directory / f), top)
        if subckt is None:
            errors.append(f"lvs: no .SUBCKT {top} in {f}")
        else:
            found.append(Ports("lvs", f, {p: "" for p in subckt}))
    return found, errors


def compare_ports(found: list[Ports], power_pins: set) -> list[str]:
    """Where the views disagree: a signal port one view has and another
    lacks, a port whose direction differs. Power pins (those a view marks as
    such, and power_pins) are left out; the LVS netlist, which lists them
    as ports, is compared without them."""
    power = set(power_pins)
    for p in found:
        power |= p.power
    errors = []
    sets = {f"{p.view} {p.file}": {n: d for n, d in p.signals.items() if n not in power} for p in found}
    names = list(sets)
    for a, b in zip(names, names[1:], strict=False):
        only_a, only_b = sorted(set(sets[a]) - set(sets[b])), sorted(set(sets[b]) - set(sets[a]))
        if only_a:
            errors.append(f"{', '.join(only_a)} in {a}, not in {b}")
        if only_b:
            errors.append(f"{', '.join(only_b)} in {b}, not in {a}")
    directions: dict = {}
    for where, ports in sets.items():
        for name, d in ports.items():
            if d:
                directions.setdefault(name, {})[where] = d
    for name, seen in sorted(directions.items()):
        if len(set(seen.values())) > 1:
            errors.append(f"{name} is " + ", ".join(f"{d} in {w}" for w, d in seen.items()))
    return errors


@dataclass
class Integrity:
    errors: list
    ports: int = 0
    views: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def integrity(directory: Path | str, rel: release.Release, profile: Optional[dict] = None) -> Integrity:
    """The integrity checks of release `rel` in `directory`: it has a view,
    its placeholders name files of it, its views name the same ports in the
    same directions, and, with a profile, its Liberty corners are the
    profile's."""
    directory = Path(directory)
    errors = []
    if not rel.views():
        errors.append("the release has no view: give at least one file (--lef, --netlist, ...)")
    errors += _placeholder_errors(rel)
    found, view_errors = view_ports(directory, rel.data, rel.top)
    errors += view_errors
    power = set((profile or {}).get("profile", {}).get("power_pins", []))
    errors += compare_ports(found, power)
    corners = (profile or {}).get("profile", {}).get("corners")
    liberty = rel.data.get("liberty_files") or {}
    if corners and liberty:
        extra = sorted(set(liberty) - set(corners))
        if extra:
            errors.append(f"liberty: corners {', '.join(extra)} are not the profile's ({', '.join(corners)})")
    count = max((len([n for n in p.signals if n not in power | p.power]) for p in found), default=0)
    return Integrity(errors, count, [p.view for p in found])


def _placeholder_errors(rel: release.Release) -> list[str]:
    errors = []
    for item in rel.placeholders:
        name, _, corner = item.partition(".")
        view = release.VIEWS.get(name) or next((v for v in release.VIEWS.values() if v.field == name), None)
        if view is None:
            errors.append(f"placeholder {item}: no view {name} (views: {', '.join(release.VIEWS)})")
            continue
        value = rel.data.get(view.field)
        if not value or (corner and (not isinstance(value, dict) or corner not in value)):
            errors.append(f"placeholder {item}: the release has no such file")
    return errors


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def read_profile(path: Path | str) -> dict:
    """A profile (TOML): [profile] name, corners, power_pins; [uses.<use>]
    needs = [views]; [checks], handed as it is to a checks directory."""
    try:
        with open(path, "rb") as f:
            profile = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise exceptions.BakeRuntimeError(f"Profile {path}: {err}") from err
    for use, spec in profile.get("uses", {}).items():
        unknown = [v for v in spec.get("needs", []) if v not in release.VIEWS]
        if unknown:
            raise exceptions.BakeRuntimeError(
                f"Profile {path}: use {use} needs {', '.join(unknown)}, which are not views "
                f"({', '.join(release.VIEWS)})."
            )
    return profile


def uses(rel: release.Release, profile: dict) -> dict[str, tuple[str, list]]:
    """{use: (state, views)} of the profile's uses: ok when the release has
    every view the use needs, placeholder when one of them is a stand-in,
    missing (with the views it lacks) otherwise."""
    have = set(rel.views())
    stand_ins = {item.partition(".")[0] for item in rel.placeholders}
    stand_ins |= {v.name for v in release.VIEWS.values() if v.field in stand_ins}
    out = {}
    for use, spec in profile.get("uses", {}).items():
        needs = list(spec.get("needs", []))
        missing = [v for v in needs if v not in have]
        if missing:
            out[use] = ("missing", missing)
        elif any(v in stand_ins for v in needs):
            out[use] = ("placeholder", [v for v in needs if v in stand_ins])
        else:
            out[use] = ("ok", [])
    return out


# ---------------------------------------------------------------------------
# A checks directory: technology checks, run as a script
# ---------------------------------------------------------------------------

def run_checks_dir(checks_dir: Path | str, release_dir: Path | str, options: dict) -> dict:
    """Run checks_dir/run.py on the release: it gets the release directory
    ($BAKE_RELEASE_DIR) and the profile's [checks] table (a JSON file,
    $BAKE_CHECKS_OPTIONS), and writes {check: {status, value, report}} to
    $BAKE_CHECKS_OUT. Returns what it wrote; a script that fails or writes
    nothing is an error."""
    script = Path(checks_dir) / "run.py"
    if not script.is_file():
        raise exceptions.BakeRuntimeError(f"Checks directory {checks_dir}: it has no run.py.")
    with tempfile.TemporaryDirectory(prefix="bake-checks-") as tmp:
        options_file, out = Path(tmp) / "options.json", Path(tmp) / "checks.json"
        options_file.write_text(json.dumps(options), encoding="utf-8")
        env = {**os.environ, "BAKE_RELEASE_DIR": str(Path(release_dir).resolve()),
               "BAKE_CHECKS_OPTIONS": str(options_file), "BAKE_CHECKS_OUT": str(out)}
        proc = subprocess.run([sys.executable, str(script.resolve())], cwd=tmp, env=env,
                              capture_output=True, text=True, check=False)
        if proc.returncode or not out.is_file():
            raise exceptions.BakeRuntimeError(
                f"Checks {script} failed (exit {proc.returncode}"
                f"{', no checks.json' if not out.is_file() else ''}): {proc.stderr.strip()[-2000:]}"
            )
        try:
            results = json.loads(out.read_text(encoding="utf-8"))
        except ValueError as err:
            raise exceptions.BakeRuntimeError(f"Checks {script}: checks.json is not JSON ({err})") from err
    logging.debug("Checks %s: %s", script, results)
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

STATE = {"pass": "ok", "fail": "FAIL", "skipped": "skip"}


def _value(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, dict):
        return " ".join(f"{k} {v}" for k, v in value.items())
    return str(value)


def report_lines(rel: release.Release, *, integrity_result: Optional[Integrity] = None,
                 quality: Optional[dict] = None, waived: Optional[dict] = None,
                 grade: str = "", stale: Optional[list] = None,
                 use_states: Optional[dict] = None, others: Optional[list] = None,
                 checksums: Optional[list] = None) -> list[str]:
    """The report of a release, one line each, as `bake <block> release`
    prints it."""
    head = f"{rel.block} {rel.version}"
    if grade:
        head += f"  {grade}"
    if rel.label:
        head += f"  (label: {rel.label})"
    lines = [head]
    git = (rel.producer or {}).get("git") or {}
    origin = [rel.recipe or (rel.producer or {}).get("kind", "")]
    if git.get("commit"):
        origin.append(f"{rel.project.get('name', '')} {git['commit'][:7]} ({'dirty' if git.get('dirty') else 'clean'})")
    if (rel.producer or {}).get("bake_version"):
        origin.append(f"bake {rel.producer['bake_version']}")
    if rel.created:
        origin.append(rel.created[:10])
    lines.append(f"  {'from':<11} {', '.join(o for o in origin if o)}")
    if integrity_result is not None:
        if integrity_result.ok:
            views = ", ".join(integrity_result.views) or "no view with ports"
            lines.append(f"  {'integrity':<11} ok    {integrity_result.ports} ports agree across {views}")
        else:
            lines.append(f"  {'integrity':<11} FAIL  {integrity_result.errors[0]}")
            lines += [f"  {'':<11}       {e}" for e in integrity_result.errors[1:]]
    if checksums:
        lines.append(f"  {'checksums':<11} FAIL  {', '.join(checksums[:5])}" + (" ..." if len(checksums) > 5 else ""))
    for name, check in sorted((quality if quality is not None else rel.checks.get("quality", {})).items()):
        state = STATE.get(check.get("status", ""), check.get("status", "?"))
        text = f"  {name:<11} {state:<5} {_value(check.get('value'))}".rstrip()
        reason = (waived or {}).get(name)
        if reason and check.get("status") == "fail":
            text += f"   waived: {reason}"
        lines.append(text)
    if rel.placeholders:
        lines.append(f"  {'placeholder':<11} {', '.join(rel.placeholders)}")
    if stale:
        more = f" (and {len(stale) - 3} more)" if len(stale) > 3 else ""
        lines.append(f"  {'stale':<11} {', '.join(stale[:3])}{more} changed since this release")
    if use_states:
        parts = []
        for use, (state, views) in use_states.items():
            parts.append(f"{use} {state}" + (f" ({', '.join(views)})" if views and state != "ok" else ""))
        lines.append(f"  {'uses':<11} " + " · ".join(parts))
    if others:
        lines.append(f"  {'other':<11} " + ", ".join(others))
    return lines
