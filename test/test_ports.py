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

"""The ports of a cell as its views declare them, and whether they agree
(bake/ports.py)."""

from pathlib import Path

import pytest

from bake import ports
from bake.ports import Interface, Port

ADC = str(Path(__file__).resolve().parent / "projects" / "blackbox" / "adc.lef")


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def summary(iface):
    return {n: (p.direction, p.bits, p.supply) for n, p in iface.ports.items()}


def test_lef_ports_have_no_bus_order():
    iface = ports.read("lef", [ADC], "adc")
    assert iface.ports["dout"].bits == [2, 1, 0] and not iface.ports["dout"].ordered
    assert iface.ports["VDD"].supply and iface.ports["clk"].supply is False


def test_liberty_pins_buses_and_supplies(tmp_path):
    path = write(tmp_path, "c.lib", r"""
/* a comment */
library (lib) {
  type (b3) { base_type : array ; bit_width : 3 ; bit_from : 0 ; bit_to : 2 ; }
  cell ("other") { pin (z) { direction : output ; } }
  cell ("c") {
    area : 10 ;
    pg_pin (VDD) { pg_type : primary_power ; }
    pin (a, \
         b) { direction : input ; }
    bus (d) { bus_type : b3 ; direction : output ; pin (d[0]) { } }
    pin (q[1]) { direction : output ; }
    pin (q[0]) { direction : output ; }
    bus (x) { bus_type : nope ; direction : input ; }
    type (b2) { bit_from : 1 ; bit_to : 0 ; }
    bus (y) { bus_type : b2 ; pin (y[1]) { direction : output ; } pin (y[0]) { direction : output ; } }
  }
}
""")
    iface = ports.read("liberty", [path], "c")
    assert summary(iface) == {
        "VDD": (None, [], True), "a": ("input", [], False), "b": ("input", [], False),
        "d": ("output", [0, 1, 2], False), "q": ("output", [1, 0], False), "x": ("input", None, False),
        "y": ("output", [1, 0], False)}
    assert iface.notes == ["bus x: bus_type nope is not a type of the library"]
    with pytest.raises(ports.PortsError, match="No cell missing"):
        ports.read("liberty", [path], "missing")


def test_verilog_ansi_header_with_parameters(tmp_path):
    path = write(tmp_path, "m.sv", """
module other (input a); endmodule
// module m (input wrong);
module m #(parameter int W = 4, parameter D = $clog2(W) + 1) (
  input  logic          clk,
  (* keep *) input  wire  [W-1:0] a, b,
  output logic signed [0:D] y,
  inout  wire  [N:0]  unresolved,
  output logic        arr [3],
  \\esc[0]  ,
  intf.mp   bus_if
);
  function automatic f(input int x); endfunction
endmodule
""")
    iface = ports.read("verilog", [path], "m")
    assert summary(iface)["clk"] == ("input", [], None)
    assert summary(iface)["a"] == summary(iface)["b"] == ("input", [3, 2, 1, 0], None)
    assert summary(iface)["y"] == ("output", [0, 1, 2, 3], None)
    assert summary(iface)["unresolved"] == ("inout", None, None)
    assert summary(iface)["esc[0]"] == ("output", [], None)       # inherits from arr
    assert "x" not in iface.ports and "bus_if" in iface.ports
    assert any("range [N:0] not resolved" in n for n in iface.notes)
    assert any("unpacked dimension [3] ignored" in n for n in iface.notes)


def test_verilog_non_ansi_header(tmp_path):
    path = write(tmp_path, "m.v", """
module m (clk, d, q, n);
  parameter W = 2;
  localparam M = W * 2;
  input clk;
  input [M-1:0] d;
  output reg q;
  task t; input [7:0] ignored; begin end endtask
endmodule
""")
    iface = ports.read("verilog", [path], "m")
    assert summary(iface) == {"clk": ("input", [], None), "d": ("input", [3, 2, 1, 0], None),
                              "q": ("output", [], None), "n": (None, None, None)}
    assert "n: in the port list but not declared" in iface.notes
    with pytest.raises(ports.PortsError, match="No module x"):
        ports.read("verilog", [path], "x")


def test_spice_subckt_with_pininfo(tmp_path):
    path = write(tmp_path, "c.cdl", """* netlist
.SUBCKT other a
.ENDS
.subckt c a d<1> d<0>
+ VDD W=1
*.PININFO a:I d<1>:O d<0>:O
* VDD:B is not PININFO
M1 a a VDD VDD p
.ENDS
""")
    iface = ports.read("spice", [path], "c")
    assert summary(iface) == {"a": ("input", [], None), "d": ("output", [1, 0], None),
                              "VDD": (None, [], None)}
    with pytest.raises(ports.PortsError, match="No reader for view gds"):
        ports.read("gds", [path], "c")


@pytest.mark.parametrize("path, view", [
    ("a.lef", "lef"), ("a.LIB", "liberty"), ("a.v.gz", "verilog"), ("a.sv", "verilog"),
    ("a.cdl", "spice"), ("a.gds", None),
])
def test_view_of(path, view):
    assert ports.view_of(path) == view


def iface(view, **ports_):
    return Interface(view, f"{view}.file", "c", {n: Port(n, *p) for n, p in ports_.items()})


def test_compare_finds_what_the_views_disagree_on():
    views = [
        iface("lef", a=("input", [], False, False), d=("output", [2, 1, 0], False, False),
              e=("output", [1, 0], False, False), VDD=("inout", [], False, True),
              VSS=("inout", [], False, True)),
        iface("liberty", a=("output", [], True, False), d=("output", [2, 1, 0], True, False),
              e=("output", [1, 0], True, False), VDD=("inout", [], True, False)),
        iface("verilog", a=("input", [], True, None), d=("output", [0, 1, 2], True, None),
              e=("output", [2, 1, 0], True, None), VSS=("inout", [], True, None)),
        iface("spice", a=(None, [], True, None), d=(None, [2, 1, 0], True, None),
              e=(None, [1, 0], True, None), VDD=(None, [], True, None)),
    ]
    found = {(f.port, f.severity): f.message for f in ports.compare(views)}
    assert found[("a", "error")] == "direction differs: input in lef, verilog; output in liberty"
    assert found[("d", "error")].startswith("the bus runs the other way: [2:0] in liberty, spice; [0:2] in verilog")
    assert found[("e", "error")].startswith("bits differ:")
    assert found[("VDD", "warning")] == "a supply, but a signal pin in liberty"
    # A supply may be missing from Verilog and Liberty, not from the LVS netlist
    assert found[("VSS", "error")] == "missing from spice; in lef, verilog"
    assert len(found) == 5


def test_waive_and_report():
    views = [iface("lef", a=("input", [], False, False)), iface("verilog")]
    findings = ports.waive(ports.compare(views), {"a": "not wired yet"})
    assert findings[0].waived == "not wired yet"
    text = ports.report(views, findings)
    assert "| lef | lef | 1 | lef.file |" in text
    assert "- **error** `a`: missing from verilog; in lef (waived: not wired yet)" in text
    assert "The views agree." in ports.report(views[:1], [])
