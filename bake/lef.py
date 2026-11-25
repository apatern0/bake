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

"""The interface of a hard macro as its LEF describes it, and the views
made from it alone: a port-only Verilog module and a black-box Liberty cell.

    macros = lef.read("adc.lef")             # {name: Macro}
    text = lef.verilog(macros["adc"])
    text = lef.liberty(macros["adc"], timing={"clk": {"clock": True}})

A LEF says which pins a macro has, their direction and use, the bits of its
buses, its size and where each pin is drawn. It says nothing of timing, and
not in which order a bus runs: its buses are written from the highest bit
down. The blackbox step (bake/builtin/blackbox) writes the two views for a
macro(); a flow may import this module too, since a Python flow runs under
bake's interpreter, for instance to check where a block's pins are:

    for shape in macros["core"].shapes["clock_i"]:
        shape.layer, shape.center, shape.x1, shape.y1    # um from the lower left

Read: MACRO with its SIZE and ORIGIN, its PINs (DIRECTION, USE, and the
RECTs and POLYGONs of their PORTs, by layer) and BUSBITCHARS. The rest of
the file (technology, OBS, vias of the ports) is skipped."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .exceptions import BakeRuntimeError


class LefError(BakeRuntimeError):
    """A LEF file the views cannot be made from."""


# LEF DIRECTION -> the direction of a Verilog port and a Liberty pin
_DIRECTIONS = {"INPUT": "input", "OUTPUT": "output", "INOUT": "inout", "FEEDTHRU": "inout"}
# USE of the pins that are no signal
SUPPLY_USES = ("POWER", "GROUND")


@dataclass
class Port:
    """A scalar pin, or the bits of a bus (name[bit]) gathered."""
    name: str
    direction: str              # input, output, inout
    use: str = "SIGNAL"         # LEF USE: SIGNAL, ANALOG, CLOCK, POWER, GROUND, ...
    bits: list[int] = field(default_factory=list)   # empty for a scalar

    @property
    def is_bus(self) -> bool:
        return bool(self.bits)

    @property
    def msb(self) -> int:
        return max(self.bits)

    @property
    def lsb(self) -> int:
        return min(self.bits)

    @property
    def is_supply(self) -> bool:
        return self.use in SUPPLY_USES


@dataclass
class Shape:
    """A rectangle of a pin (a polygon's bounding box), in um from the
    macro's lower-left corner."""
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2


@dataclass
class Macro:
    name: str
    width: float = 0.0          # um
    height: float = 0.0
    ports: list[Port] = field(default_factory=list)   # in the order of the LEF
    # The shapes of each pin, by its LEF name (a bus's bits one by one:
    # "dout[1]"); ORIGIN applied, so that they count from the lower left
    shapes: dict[str, list[Shape]] = field(default_factory=dict)
    origin: tuple[float, float] = (0.0, 0.0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def port(self, name: str) -> Optional[Port]:
        return next((p for p in self.ports if p.name == name), None)


# ── Reading ──────────────────────────────────────────────────────────────────

_TOKEN = re.compile(r'"[^"]*"|;|[^\s;]+')


def _tokens(text: str) -> list[str]:
    """The LEF's tokens, comments (# to the end of the line) left out."""
    lines = (line.split("#", 1)[0] if "#" in line and '"' not in line else line
             for line in text.splitlines())
    return _TOKEN.findall("\n".join(lines))


class _Reader:
    def __init__(self, tokens: list[str], path: str):
        self.tokens = tokens
        self.pos = 0
        self.path = path
        self.busbit = "[]"

    def next(self) -> str:
        if self.pos >= len(self.tokens):
            raise LefError(f"{self.path}: unexpected end of file")
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def statement(self) -> list[str]:
        """The rest of the statement, up to its ';' (left out)."""
        words = []
        while (token := self.next()) != ";":
            words.append(token)
        return words

    def block(self) -> None:
        """Skip statements up to a bare END (PORT, OBS, DENSITY)."""
        while self.next() != "END":
            self.pos -= 1
            self.statement()

    def macros(self) -> dict[str, Macro]:
        found: dict[str, Macro] = {}
        while self.pos < len(self.tokens):
            token = self.next()
            if token == "MACRO":
                macro = self.macro(self.next())
                found[macro.name] = macro
            elif token == "BUSBITCHARS":
                words = self.statement()
                chars = words[0].strip('"') if words else ""
                if len(chars) == 2:
                    self.busbit = chars
            elif token == "END":
                if self.pos < len(self.tokens):
                    self.next()     # END LIBRARY, END <layer>, ...
            else:
                self.pos -= 1
                self.statement()
        return found

    def macro(self, name: str) -> Macro:
        macro = Macro(name)
        while True:
            token = self.next()
            if token == "END":
                if self.next() == name:
                    ox, oy = macro.origin
                    for shapes in macro.shapes.values():
                        for s in shapes:
                            s.x1, s.y1, s.x2, s.y2 = s.x1 + ox, s.y1 + oy, s.x2 + ox, s.y2 + oy
                    return macro
                raise LefError(f"{self.path}: MACRO {name} ends with a stray END")
            if token == "PIN":
                self.pin(macro, self.next())
            elif token in ("OBS", "DENSITY"):
                self.block()
            elif token == "SIZE":
                words = self.statement()
                try:
                    macro.width, macro.height = float(words[0]), float(words[2])
                except (IndexError, ValueError) as err:
                    raise LefError(f"{self.path}: MACRO {name}: SIZE {' '.join(words)}") from err
            elif token == "ORIGIN":
                words = self.statement()
                try:
                    macro.origin = (float(words[0]), float(words[1]))
                except (IndexError, ValueError) as err:
                    raise LefError(f"{self.path}: MACRO {name}: ORIGIN {' '.join(words)}") from err
            else:
                self.pos -= 1
                self.statement()

    def pin(self, macro: Macro, name: str) -> None:
        direction, use = "inout", "SIGNAL"
        while True:
            token = self.next()
            if token == "END":
                if self.next() == name:
                    break
                raise LefError(f"{self.path}: PIN {name} of {macro.name} ends with a stray END")
            if token == "PORT":
                macro.shapes.setdefault(name, []).extend(self.port(macro.name, name))
            elif token == "DIRECTION":
                words = self.statement()
                direction = _DIRECTIONS.get(words[0] if words else "", "inout")
            elif token == "USE":
                words = self.statement()
                use = words[0] if words else use
            else:
                self.pos -= 1
                self.statement()
        self.add(macro, name, direction, use)

    def port(self, macro: str, pin: str) -> list[Shape]:
        """The rectangles and polygons of a PORT, up to its END, each on the
        LAYER before it."""
        shapes: list[Shape] = []
        layer = ""
        while (token := self.next()) != "END":
            words = self.statement()
            if token == "LAYER" and words:
                layer = words[0]
            elif token in ("RECT", "POLYGON"):
                if words[:1] == ["MASK"]:
                    words = words[2:]
                if words[:1] == ["ITERATE"]:
                    continue                    # arrays of shapes: not read
                try:
                    values = [float(w) for w in words]
                except ValueError as err:
                    raise LefError(f"{self.path}: PIN {pin} of {macro}: {token} {' '.join(words)}") from err
                xs, ys = values[0::2], values[1::2]
                if not xs or len(xs) != len(ys):
                    raise LefError(f"{self.path}: PIN {pin} of {macro}: {token} {' '.join(words)}")
                shapes.append(Shape(layer, min(xs), min(ys), max(xs), max(ys)))
        return shapes

    def add(self, macro: Macro, pin: str, direction: str, use: str) -> None:
        opening, closing = self.busbit[0], self.busbit[1]
        found = re.fullmatch(rf"(.+){re.escape(opening)}(\d+){re.escape(closing)}", pin)
        base, bit = (found.group(1), int(found.group(2))) if found else (pin, None)
        port = macro.port(base)
        if port is None:
            macro.ports.append(Port(base, direction, use, [] if bit is None else [bit]))
            return
        if bit is None or not port.is_bus:
            raise LefError(f"{self.path}: MACRO {macro.name} has both a pin {base} and the bits of a bus {base}")
        if bit in port.bits:
            raise LefError(f"{self.path}: MACRO {macro.name} declares pin {pin} twice")
        if port.direction != direction:
            raise LefError(f"{self.path}: MACRO {macro.name}: the bits of bus {base} differ in direction")
        port.bits.append(bit)


def read(*paths: str) -> dict[str, Macro]:
    """The macros of the LEF files, by name; a later file's macro replaces an
    earlier one of the same name."""
    found: dict[str, Macro] = {}
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            found.update(_Reader(_tokens(f.read()), path).macros())
    return found


# ── Verilog ──────────────────────────────────────────────────────────────────

def verilog(macro: Macro, supplies: bool = False) -> str:
    """A port-only module of the macro, its buses from the highest bit down;
    its power and ground pins only if supplies (as inout)."""
    ports = [p for p in macro.ports if supplies or not p.is_supply]
    lines = [f"module {macro.name} ("]
    lines += [f"  {p.name}," for p in ports]
    if ports:
        lines[-1] = lines[-1].rstrip(",")
    lines.append(");")
    for p in ports:
        width = f" [{p.msb}:{p.lsb}]" if p.is_bus else ""
        lines.append(f"  {p.direction}{width} {p.name};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


# ── Liberty ──────────────────────────────────────────────────────────────────

# What config.blackbox.pins may say of a pin or a bus
PIN_KEYS = {
    "clock":        "the pin is a clock",
    "capacitance":  "input capacitance, pF",
    "related_pin":  "the clock the next keys refer to",
    "edge":         "the clock's active edge: rising (default) or falling",
    "setup":        "an input's setup time before the edge, ns",
    "hold":         "an input's hold time after the edge, ns",
    "delay":        "an output's delay after the edge, ns",
    "transition":   "an output's transition time, ns",
    "max_transition": "the largest transition the pin takes or drives, ns",
}


def check_timing(macro: Macro, timing: dict) -> list[str]:
    """What is wrong with a timing spec for the macro: unknown pins or keys,
    keys that do not fit the pin's direction, values that are not numbers."""
    errors = []
    for name, spec in timing.items():
        port = macro.port(name)
        where = f"pin {name}"
        if port is None:
            errors.append(f"{where}: {macro.name} has no such pin")
            continue
        if not isinstance(spec, dict):
            errors.append(f"{where}: expected a dict of {', '.join(PIN_KEYS)}")
            continue
        unknown = [k for k in spec if k not in PIN_KEYS]
        if unknown:
            errors.append(f"{where}: unknown key(s) {', '.join(unknown)}; known: {', '.join(PIN_KEYS)}")
        for key in ("capacitance", "setup", "hold", "delay", "transition", "max_transition"):
            if key in spec and not isinstance(spec[key], (int, float)):
                errors.append(f"{where}: {key} must be a number")
        timed = [k for k in ("setup", "hold", "delay") if k in spec]
        if timed and "related_pin" not in spec:
            errors.append(f"{where}: {', '.join(timed)} need(s) related_pin")
        related = spec.get("related_pin")
        if related is not None and macro.port(related) is None:
            errors.append(f"{where}: related_pin {related}: {macro.name} has no such pin")
        if spec.get("edge", "rising") not in ("rising", "falling"):
            errors.append(f"{where}: edge must be rising or falling")
        if port.direction == "output" and ("setup" in spec or "hold" in spec):
            errors.append(f"{where}: an output has no setup or hold; give delay")
        if port.direction == "input" and ("delay" in spec or "transition" in spec):
            errors.append(f"{where}: an input has no delay or transition; give setup and hold")
    return errors


def untimed(macro: Macro, timing: dict) -> list[str]:
    """The digital pins the timing spec leaves without timing: signal and
    clock pins that are neither clocks nor related to one."""
    timed = {name for name, spec in timing.items()
             if spec.get("clock") or any(k in spec for k in ("setup", "hold", "delay"))}
    return [p.name for p in macro.ports
            if p.use in ("SIGNAL", "CLOCK") and p.direction != "inout" and p.name not in timed]


def _number(value) -> str:
    return f"{float(value):g}"


def _scalar(group: str, value, indent: str) -> list[str]:
    return [f"{indent}{group}(scalar) {{", f'{indent}  values("{_number(value)}") ;', f"{indent}}}"]


def _timing(spec: dict, direction: str, indent: str) -> list[str]:
    edge = spec.get("edge", "rising")
    lines = []
    arcs = []
    if direction != "output":
        arcs += [(f"setup_{edge}", ("rise_constraint", "fall_constraint"), spec["setup"])] if "setup" in spec else []
        arcs += [(f"hold_{edge}", ("rise_constraint", "fall_constraint"), spec["hold"])] if "hold" in spec else []
    if direction != "input" and "delay" in spec:
        arcs.append((f"{edge}_edge", ("cell_rise", "cell_fall"), spec["delay"]))
    for timing_type, groups, value in arcs:
        lines += [f"{indent}timing() {{",
                  f'{indent}  related_pin : "{spec["related_pin"]}" ;',
                  f"{indent}  timing_type : {timing_type} ;"]
        for group in groups:
            lines += _scalar(group, value, indent + "  ")
        if timing_type.endswith("_edge") and "transition" in spec:
            for group in ("rise_transition", "fall_transition"):
                lines += _scalar(group, spec["transition"], indent + "  ")
        lines.append(f"{indent}}}")
    return lines


def _pin_attributes(port: Port, spec: dict, indent: str) -> list[str]:
    lines = [f"{indent}direction : {port.direction} ;"]
    if spec.get("clock"):
        lines.append(f"{indent}clock : true ;")
    if "capacitance" in spec and port.direction != "output":
        lines.append(f"{indent}capacitance : {_number(spec['capacitance'])} ;")
    if "max_transition" in spec:
        lines.append(f"{indent}max_transition : {_number(spec['max_transition'])} ;")
    return lines + _timing(spec, port.direction, indent)


def liberty(macro: Macro, timing: Optional[dict] = None, library: str = "") -> str:
    """A Liberty library (default: named after the macro) of one black-box
    cell: the macro's area and signal pins, buses from the highest bit
    down, with what timing ({pin or bus: {key: value}}, PIN_KEYS) gives;
    the same values for every bit of a bus. Power and ground pins are left
    out. Units: ns, pF, V. Raise LefError on a spec check_timing refuses."""
    timing = timing or {}
    errors = check_timing(macro, timing)
    if errors:
        raise LefError(f"Timing of macro {macro.name}:\n" + "\n".join(f"   - {e}" for e in errors))
    ports = [p for p in macro.ports if not p.is_supply]
    buses = sorted({(p.msb, p.lsb) for p in ports if p.is_bus}, reverse=True)
    lines = [f"library({library or macro.name}) {{",
             "  delay_model : table_lookup ;",
             '  time_unit : "1ns" ;',
             '  voltage_unit : "1V" ;',
             '  current_unit : "1mA" ;',
             "  capacitive_load_unit(1, pf) ;",
             '  pulling_resistance_unit : "1kohm" ;',
             '  leakage_power_unit : "1nW" ;']
    for msb, lsb in buses:
        lines += [f"  type(bus_{msb}_{lsb}) {{",
                  "    base_type : array ;",
                  "    data_type : bit ;",
                  f"    bit_width : {msb - lsb + 1} ;",
                  f"    bit_from : {msb} ;",
                  f"    bit_to : {lsb} ;",
                  "    downto : true ;",
                  "  }"]
    lines += [f"  cell({macro.name}) {{",
              f"    area : {_number(macro.area)} ;",
              "    dont_touch : true ;",
              "    dont_use : true ;",
              "    is_macro_cell : true ;"]
    for port in ports:
        spec = timing.get(port.name, {})
        if port.is_bus:
            lines += [f"    bus({port.name}) {{", f"      bus_type : bus_{port.msb}_{port.lsb} ;"]
            lines += _pin_attributes(port, spec, "      ")
            lines.append("    }")
        else:
            lines.append(f"    pin({port.name}) {{")
            lines += _pin_attributes(port, spec, "      ")
            lines.append("    }")
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"
