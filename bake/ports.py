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

"""The ports of a cell as each of its views declares them, and whether the
views agree.

    views = [ports.read("lef", ["adc.lef"], "adc"),
             ports.read("liberty", ["adc_tt.lib"], "adc"),
             ports.read("verilog", ["adc.v"], "adc"),
             ports.read("spice", ["adc.cdl"], "adc")]
    findings = ports.compare(views)

Each reader gives an Interface: the cell's ports, by name, with what the
view says of them (direction, bits, whether it is a supply); a view that
does not say something leaves it None. compare() reports, port by port,
what the views disagree on. A flow with a view of its own (an OpenAccess
library read through a vendor's tool, say) builds an Interface from it and
compares it the same way.

The readers cover what views of a cell declare in practice, not the whole
languages: LEF (bake.lef), Liberty (pin, bus, pg_pin and bus types), Verilog
and SystemVerilog module headers (ANSI or not, with ranges that are numbers
or arithmetic on the module's parameters), and SPICE/CDL .SUBCKT lines
(with Calibre's *.PININFO for directions)."""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import lef
from .exceptions import BakeRuntimeError


class PortsError(BakeRuntimeError):
    """A view the ports cannot be read from."""


@dataclass
class Port:
    name: str
    direction: Optional[str] = None     # input, output, inout; None: the view does not say
    bits: Optional[list[int]] = None    # a bus's bits in the order declared ([] scalar; None unknown)
    ordered: bool = True                # whether bits is in a declared order (LEF has none)
    supply: Optional[bool] = None       # a power or ground pin; None: the view does not say

    @property
    def describe_bits(self) -> str:
        if self.bits is None:
            return "unknown width"
        if not self.bits:
            return "scalar"
        if self.ordered:
            return f"[{self.bits[0]}:{self.bits[-1]}]"
        return f"bits {min(self.bits)}..{max(self.bits)}"


@dataclass
class Interface:
    """A cell's ports as one view declares them."""
    view: str                           # lef, liberty, verilog, spice, or a flow's own
    source: str                         # the file(s) it was read from, for messages
    cell: str
    ports: dict[str, Port] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)   # what the reader could not tell
    name: str = ""          # what messages call it ("netlist", "liberty TT"); default the view

    @property
    def label(self) -> str:
        return self.name or self.view


_BIT = re.compile(r"(.+?)(?:\[(\d+)\]|<(\d+)>)$")


def _gather(ports: dict[str, Port], name: str, port: Port) -> None:
    """Add a pin of a view that lists a bus's bits one by one (name[3],
    name<3>) as a bit of the bus."""
    found = _BIT.fullmatch(name)
    if not found:
        ports[name] = port
        return
    base, bit = found.group(1), int(found.group(2) or found.group(3))
    bus = ports.setdefault(base, Port(base, port.direction, [], port.ordered, port.supply))
    if bus.bits is not None:
        bus.bits.append(bit)


# ── LEF ──────────────────────────────────────────────────────────────────────

def read_lef(paths: list[str], cell: str) -> Interface:
    macros = lef.read(*paths)
    if cell not in macros:
        raise PortsError(f"No MACRO {cell} in {' '.join(paths)}")
    iface = Interface("lef", " ".join(paths), cell)
    for p in macros[cell].ports:
        iface.ports[p.name] = Port(p.name, p.direction, sorted(p.bits, reverse=True), False, p.is_supply)
    return iface


# ── Liberty ──────────────────────────────────────────────────────────────────

_LIB_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}();:,]|[^\s{}();:,"]+')


@dataclass
class _Group:
    kind: str
    args: list[str]
    attrs: dict = field(default_factory=dict)
    groups: list = field(default_factory=list)

    def find(self, kind: str) -> list:
        return [g for g in self.groups if g.kind == kind]


def _liberty_tree(text: str, path: str) -> _Group:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S).replace("\\\n", " ")
    tokens = _LIB_TOKEN.findall(text)
    pos = 0

    def unquote(t: str) -> str:
        return t[1:-1] if t.startswith('"') else t

    def body(group: _Group) -> None:
        nonlocal pos
        while pos < len(tokens):
            name = tokens[pos]
            if name == "}":
                pos += 1
                return
            pos += 1
            if pos < len(tokens) and tokens[pos] == ":":            # simple attribute
                end = tokens.index(";", pos) if ";" in tokens[pos:] else len(tokens)
                group.attrs[name] = " ".join(unquote(t) for t in tokens[pos + 1:end])
                pos = end + 1
            elif pos < len(tokens) and tokens[pos] == "(":          # group or complex attribute
                end = pos
                depth = 0
                while end < len(tokens):
                    depth += {"(": 1, ")": -1}.get(tokens[end], 0)
                    if depth == 0:
                        break
                    end += 1
                args = [unquote(t) for t in tokens[pos + 1:end] if t != ","]
                pos = end + 1
                if pos < len(tokens) and tokens[pos] == "{":
                    pos += 1
                    child = _Group(name, args)
                    body(child)
                    group.groups.append(child)
                elif pos < len(tokens) and tokens[pos] == ";":
                    pos += 1
            elif name == ";":
                continue
            else:
                raise PortsError(f"{path}: cannot read Liberty near '{name}'")

    root = _Group("", [])
    body(root)
    return root


def read_liberty(paths: list[str], cell: str) -> Interface:
    iface = Interface("liberty", " ".join(paths), cell)
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            root = _liberty_tree(f.read(), path)
        for library in root.find("library"):
            for c in library.find("cell"):
                if c.args and c.args[0] == cell:
                    # bus types of the library, and of the cell (where some tools write them)
                    _liberty_cell(iface, c, {**_bus_types(library), **_bus_types(c)})
                    return iface
    raise PortsError(f"No cell {cell} in {' '.join(paths)}")


def _bus_types(group: _Group) -> dict:
    """{type: bits from bit_from to bit_to} of a group's bus types."""
    types = {}
    for t in group.find("type"):
        try:
            first, last = int(t.attrs.get("bit_from", "")), int(t.attrs.get("bit_to", ""))
        except ValueError:
            continue
        types[t.args[0]] = list(range(first, last - 1, -1)) if first >= last else list(range(first, last + 1))
    return types


def _liberty_cell(iface: Interface, cell: _Group, types: dict) -> None:
    for g in cell.groups:
        if g.kind == "pg_pin":
            for name in g.args:
                iface.ports[name] = Port(name, None, [], True, True)
        elif g.kind == "pin":
            for name in g.args:
                _gather(iface.ports, name, Port(name, g.attrs.get("direction"), [], True, False))
        elif g.kind == "bus":
            name = g.args[0]
            bits = types.get(g.attrs.get("bus_type", ""))
            if bits is None:
                iface.notes.append(f"bus {name}: bus_type {g.attrs.get('bus_type')} is not a type of the library")
            # A direction on the bus, or else on its bits, which then agree
            directions = {p.attrs["direction"] for p in g.find("pin") if "direction" in p.attrs}
            direction = g.attrs.get("direction") or (directions.pop() if len(directions) == 1 else None)
            if not g.attrs.get("direction") and len(directions) > 1:
                iface.notes.append(f"bus {name}: its bits differ in direction")
            iface.ports[name] = Port(name, direction, bits, True, False)


# ── Verilog ──────────────────────────────────────────────────────────────────

_DIRS = ("input", "output", "inout")
_TYPE_WORDS = {"wire", "reg", "logic", "var", "signed", "unsigned", "tri", "tri0", "tri1", "wand",
               "wor", "triand", "trior", "uwire", "supply0", "supply1", "bit", "integer", "interconnect"}
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.FloorDiv: operator.floordiv, ast.Div: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow, ast.LShift: operator.lshift, ast.RShift: operator.rshift}


def _evaluate(expr: str, params: dict) -> Optional[int]:
    """An integer expression of numbers and parameters, or None."""
    expr = re.sub(r"\d*'[sS]?[dD](\d+)", r"\1", expr.strip())       # 8'd3 -> 3
    expr = expr.replace("$clog2", "clog2")

    def ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Name) and node.id in params:
            return params[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "clog2"
                and len(node.args) == 1):
            value = ev(node.args[0])
            return max(0, (value - 1).bit_length())
        raise ValueError(expr)

    try:
        return ev(ast.parse(expr.replace("/", "//"), mode="eval").body)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError):
        return None


def _strip_verilog(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r"\(\*.*?\*\)", " ", text, flags=re.S)
    return re.sub(r"^\s*`.*$", " ", text, flags=re.M)


def _balanced(text: str, start: int) -> int:
    """The index just past the parenthesis that closes the one at start."""
    depth = 0
    for i in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return i + 1
    raise PortsError("unbalanced parentheses")


def _split_top(text: str) -> list[str]:
    """text split at the commas outside brackets and parentheses."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in text:
        depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _params(text: str) -> dict:
    """The integer parameters and localparams of a module, in order."""
    params: dict = {}
    for found in re.finditer(r"\b(?:parameter|localparam)\b[^=;]*?(\w+)\s*=", text):
        depth, end = 0, found.end()
        while end < len(text):                  # the value: up to a , ; or ) outside parentheses
            ch = text[end]
            if ch in ",;" and depth == 0 or ch == ")" and depth == 0:
                break
            depth += {"(": 1, ")": -1}.get(ch, 0)
            end += 1
        result = _evaluate(text[found.end():end], params)
        if result is not None:
            params[found.group(1)] = result
    return params


def _declaration(item: str, previous: Optional[tuple], params: dict, iface: Interface):
    """(direction, bits, names) of a port declaration such as
    "input wire [3:0] a, b", inheriting what a bare name in an ANSI list
    leaves out from the previous one."""
    words = re.findall(r"\[[^\]]*\]|\\\S+|[\w$]+(?:\.[\w$]+)?", item)
    direction = None
    if words and words[0] in _DIRS:
        direction = words.pop(0)
    ranges: list[str] = []
    names: list[str] = []
    for w in words:
        if w.startswith("["):
            if names:
                iface.notes.append(f"{names[-1]}: unpacked dimension {w} ignored")
            else:
                ranges.append(w)
        elif w in _TYPE_WORDS:
            continue
        elif "." in w:                                     # an interface port: intf.modport
            continue
        else:
            names.append(w.lstrip("\\"))
    if direction is None and previous is not None and not ranges and len(names) == 1:
        return previous[0], previous[1], names
    bits: Optional[list[int]] = []
    if ranges:
        if len(ranges) > 1:
            iface.notes.append(f"{', '.join(names)}: several packed dimensions, width not compared")
            bits = None
        else:
            msb, _, lsb = ranges[0][1:-1].partition(":")
            hi, lo = _evaluate(msb, params), _evaluate(lsb, params)
            if hi is None or lo is None:
                iface.notes.append(f"{', '.join(names)}: range {ranges[0]} not resolved, width not compared")
                bits = None
            else:
                bits = list(range(hi, lo - 1, -1)) if hi >= lo else list(range(hi, lo + 1))
    return direction, bits, names


def read_verilog(paths: list[str], cell: str) -> Interface:
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = _strip_verilog(f.read())
        found = re.search(rf"\b(?:module|macromodule)\s+(?:automatic\s+|static\s+)?{re.escape(cell)}\b", text)
        if found:
            return _verilog_module(text, found.end(), cell, path)
    raise PortsError(f"No module {cell} in {' '.join(paths)}")


def _verilog_module(text: str, pos: int, cell: str, path: str) -> Interface:
    iface = Interface("verilog", path, cell)
    end = text.find("endmodule", pos)
    module = text[pos:end if end >= 0 else len(text)]
    params = _params(module)
    header = ""
    rest = module
    hash_at = re.match(r"\s*#\s*\(", module)
    if hash_at:
        rest = module[_balanced(module, hash_at.end() - 1):]
    paren = re.match(r"\s*\(", rest)
    if paren:
        close = _balanced(rest, paren.end() - 1)
        header = rest[paren.end():close - 1]
        rest = rest[close:]
    items = _split_top(header)
    ansi = any(re.match(r"(input|output|inout)\b", item) for item in items)
    if ansi:
        previous = None
        for item in items:
            direction, bits, names = _declaration(item, previous, params, iface)
            previous = (direction, bits)
            for name in names:
                iface.ports[name] = Port(name, direction, bits, True, None)
        return iface
    # Non-ANSI: the names in the header, their declarations in the body (not
    # those of the module's functions and tasks)
    body = re.sub(r"\bfunction\b.*?\bendfunction\b|\btask\b.*?\bendtask\b", " ", rest, flags=re.S)
    declared = {}
    for statement in re.findall(r"\b(?:input|output|inout)\b[^;]*;", body):
        direction, bits, names = _declaration(statement.rstrip(";"), None, params, iface)
        for name in names:
            declared[name] = Port(name, direction, bits, True, None)
    for item in items:
        name = item.lstrip("\\").strip()
        iface.ports[name] = declared.get(name, Port(name, None, None, True, None))
        if name not in declared:
            iface.notes.append(f"{name}: in the port list but not declared")
    return iface


# ── SPICE / CDL ──────────────────────────────────────────────────────────────

_PININFO = {"I": "input", "O": "output", "B": "inout"}


def read_spice(paths: list[str], cell: str) -> Interface:
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        joined: list[str] = []
        for line in lines:
            if line.startswith("+") and joined:
                joined[-1] += " " + line[1:]
            else:
                joined.append(line)
        for i, line in enumerate(joined):
            words = line.split()
            if len(words) >= 2 and words[0].lower() == ".subckt" and words[1] == cell:
                iface = Interface("spice", path, cell)
                for name in words[2:]:
                    if "=" in name:
                        break
                    _gather(iface.ports, name, Port(name, None, [], True, None))
                for info in joined[i + 1:]:          # the comments right after the line
                    if not info.startswith("*"):
                        break
                    if info.upper().startswith("*.PININFO"):
                        for spec in info.split()[1:]:
                            name, _, kind = spec.rpartition(":")
                            base = _BIT.fullmatch(name)
                            port = iface.ports.get(base.group(1) if base else name)
                            if port is not None and kind.upper() in _PININFO:
                                port.direction = _PININFO[kind.upper()]
                return iface
    raise PortsError(f"No .SUBCKT {cell} in {' '.join(paths)}")


READERS: dict[str, Callable[[list[str], str], Interface]] = {
    "lef": read_lef, "liberty": read_liberty, "verilog": read_verilog, "spice": read_spice,
}

# The view a file is, by its suffix
SUFFIXES = {
    ".lef": "lef", ".lib": "liberty", ".v": "verilog", ".sv": "verilog", ".vg": "verilog",
    ".vh": "verilog", ".cdl": "spice", ".sp": "spice", ".spi": "spice", ".spice": "spice",
    ".cir": "spice", ".net": "spice",
}


def view_of(path: str) -> Optional[str]:
    """The view a file is, from its suffix (a .gz one too), or None."""
    name = path.lower()
    name = name[:-3] if name.endswith(".gz") else name
    return next((view for suffix, view in SUFFIXES.items() if name.endswith(suffix)), None)


def read(view: str, paths: list[str], cell: str) -> Interface:
    if view not in READERS:
        raise PortsError(f"No reader for view {view}: known {', '.join(READERS)}")
    return READERS[view](paths, cell)


# ── Comparing ────────────────────────────────────────────────────────────────

@dataclass
class Finding:
    severity: str           # error, warning
    port: str
    message: str
    waived: str = ""        # the reason, when config waives it


def compare(views: list[Interface]) -> list[Finding]:
    """What the views disagree on, port by port:

    - a port some views lack: an error, but for a supply (a power or ground
      pin to a view that says so) missing from a Verilog or Liberty view,
      which commonly leave supplies out;
    - a supply that a Liberty view declares as a signal pin: a warning;
    - different directions, among the views that give one: an error;
    - different bits, among the views that know them, or a bus running the
      other way in two views that give an order: an error."""
    findings: list[Finding] = []
    names: dict[str, None] = {}
    for v in views:
        names.update(dict.fromkeys(v.ports))
    supplies = {n for v in views for n, p in v.ports.items() if p.supply}
    for name in names:
        having = [(v, v.ports[name]) for v in views if name in v.ports]
        lacking = [v for v in views if name not in v.ports]
        if name in supplies:
            lacking = [v for v in lacking if v.view not in ("verilog", "liberty")]
            for v, p in having:
                if v.view == "liberty" and p.supply is False:
                    findings.append(Finding("warning", name, f"a supply, but a signal pin in {v.label}"))
        if lacking:
            findings.append(Finding("error", name, "missing from " + ", ".join(v.label for v in lacking)
                                    + "; in " + ", ".join(v.label for v, _ in having)))
        directions: dict[str, list[str]] = {}
        for v, p in having:
            if p.direction and not (name in supplies and v.view == "liberty"):
                directions.setdefault(p.direction, []).append(v.label)
        if len(directions) > 1:
            findings.append(Finding("error", name, "direction differs: " + "; ".join(
                f"{d} in {', '.join(labels)}" for d, labels in directions.items())))
        known = [(v, p) for v, p in having if p.bits is not None]
        widths: dict[tuple, list[str]] = {}
        for v, p in known:
            widths.setdefault(tuple(sorted(p.bits or [])), []).append(f"{p.describe_bits} in {v.label}")
        if len(widths) > 1:
            findings.append(Finding("error", name, "bits differ: " + "; ".join(
                d for labels in widths.values() for d in labels)))
        else:
            orders: dict[tuple, list[str]] = {}
            for v, p in known:
                if p.ordered and p.bits:
                    orders.setdefault(tuple(p.bits), []).append(v.label)
            if len(orders) > 1:
                findings.append(Finding("error", name, "the bus runs the other way: " + "; ".join(
                    f"[{bits[0]}:{bits[-1]}] in {', '.join(labels)}" for bits, labels in orders.items())))
    return findings


def waive(findings: list[Finding], waivers: dict) -> list[Finding]:
    """The findings, with those on a port of waivers ({port: reason})
    marked waived."""
    for f in findings:
        if f.port in waivers:
            f.waived = str(waivers[f.port])
    return findings


def report(views: list[Interface], findings: list[Finding]) -> str:
    """A Markdown report: the views read, then the findings."""
    lines = [f"# Ports of {views[0].cell if views else '?'}", "", "| View | Read as | Ports | Files |",
             "|---|---|---|---|"]
    lines += [f"| {v.label} | {v.view} | {len(v.ports)} | {v.source} |" for v in views]
    notes = [(v, n) for v in views for n in v.notes]
    if notes:
        lines += ["", "Not compared:", ""] + [f"- {v.label}: {n}" for v, n in notes]
    lines += ["", "## Findings", ""]
    if not findings:
        lines.append("The views agree.")
    for f in findings:
        waived = f" (waived: {f.waived})" if f.waived else ""
        lines.append(f"- **{f.severity}** `{f.port}`: {f.message}{waived}")
    return "\n".join(lines) + "\n"
