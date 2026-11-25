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

"""Reading a macro's interface from LEF and writing its port-only Verilog
and black-box Liberty (bake/lef.py)."""

import re
from pathlib import Path

import pytest

from bake import lef

ADC = Path(__file__).resolve().parent / "projects" / "blackbox" / "adc.lef"


def write(tmp_path, text, name="m.lef"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_read_gathers_pins_buses_and_size():
    adc = lef.read(str(ADC))["adc"]
    assert (adc.width, adc.height, adc.area) == (40.0, 25.5, 1020.0)
    assert [(p.name, p.direction, p.use) for p in adc.ports] == [
        ("clk", "input", "CLOCK"), ("start", "input", "SIGNAL"), ("dout", "output", "SIGNAL"),
        ("busy", "output", "SIGNAL"), ("vin", "inout", "ANALOG"), ("VDD", "inout", "POWER"),
        ("VSS", "inout", "GROUND")]
    dout = adc.port("dout")
    assert (dout.msb, dout.lsb, sorted(dout.bits)) == (2, 0, [0, 1, 2])


def test_read_skips_what_the_views_do_not_need(tmp_path):
    """Technology sections, a MACRO keyword inside PROPERTYDEFINITIONS,
    comments, another bus-bit syntax, several macros, FEEDTHRU."""
    path = write(tmp_path, """
BUSBITCHARS "<>" ;   # buses as a<0>
PROPERTYDEFINITIONS
  MACRO kind STRING ;
END PROPERTYDEFINITIONS
LAYER M1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
END M1
SITE core
  CLASS CORE ;
  SIZE 0.2 BY 2 ;
END core
MACRO one
  SIZE 1 BY 2 ;
  PROPERTY kind "x" ;
  PIN a<1>
    DIRECTION INPUT ;
  END a<1>
  PIN a<0>
    DIRECTION INPUT ;
  END a<0>
  PIN f # through
    DIRECTION FEEDTHRU ;
  END f
  DENSITY
    LAYER M1 ;
      RECT 0 0 1 2 50 ;
  END
END one
MACRO two
  SIZE 3 BY 4 ;
  PIN y
    DIRECTION OUTPUT TRISTATE ;
  END y
END two
END LIBRARY
""")
    macros = lef.read(path)
    assert sorted(macros) == ["one", "two"]
    assert [(p.name, p.direction, p.bits) for p in macros["one"].ports] == [
        ("a", "input", [1, 0]), ("f", "inout", [])]
    assert macros["two"].port("y").direction == "output"


@pytest.mark.parametrize("pins, message", [
    ("PIN a\n DIRECTION INPUT ;\nEND a\nPIN a[0]\n DIRECTION INPUT ;\nEND a[0]",
     "has both a pin a and the bits of a bus a"),
    ("PIN a[0]\n DIRECTION INPUT ;\nEND a[0]\nPIN a[0]\n DIRECTION INPUT ;\nEND a[0]",
     "declares pin a[0] twice"),
    ("PIN a[0]\n DIRECTION INPUT ;\nEND a[0]\nPIN a[1]\n DIRECTION OUTPUT ;\nEND a[1]",
     "the bits of bus a differ in direction"),
    ("PIN a\n DIRECTION INPUT ;\nEND b", "PIN a of m ends with a stray END"),
])
def test_read_refuses_inconsistent_pins(tmp_path, pins, message):
    path = write(tmp_path, f"MACRO m\n SIZE 1 BY 1 ;\n{pins}\nEND m\n")
    with pytest.raises(lef.LefError, match=re.escape(message)):
        lef.read(path)


def test_read_refuses_a_truncated_file(tmp_path):
    with pytest.raises(lef.LefError, match="unexpected end of file"):
        lef.read(write(tmp_path, "MACRO m\n SIZE 1 BY 1 ;\n PIN a\n"))


def test_verilog_is_port_only_with_supplies_on_request():
    adc = lef.read(str(ADC))["adc"]
    text = lef.verilog(adc)
    assert text.splitlines()[:2] == ["module adc (", "  clk,"]
    assert "  output [2:0] dout;" in text and "  inout vin;" in text
    assert "VDD" not in text and text.endswith("endmodule\n")
    assert "  inout VDD;" in lef.verilog(adc, supplies=True)


def test_liberty_is_a_black_box_with_the_given_timing():
    adc = lef.read(str(ADC))["adc"]
    text = lef.liberty(adc, {"clk": {"clock": True},
                             "dout": {"related_pin": "clk", "delay": 1.5, "edge": "falling"}})
    assert text.startswith("library(adc) {")
    assert "type(bus_2_0) {" in text and "bus_type : bus_2_0 ;" in text
    assert "area : 1020 ;" in text and "dont_use : true ;" in text
    assert "VDD" not in text and "pin(vin) {" in text
    assert "timing_type : falling_edge ;" in text and 'values("1.5") ;' in text
    assert "rise_transition" not in text
    assert lef.liberty(adc, library="analog").startswith("library(analog) {")


@pytest.mark.parametrize("timing, message", [
    ({"nope": {}}, "pin nope: adc has no such pin"),
    ({"clk": {"slew": 1}}, "unknown key(s) slew"),
    ({"start": {"setup": 0.1}}, "setup need(s) related_pin"),
    ({"start": {"related_pin": "nope", "setup": 0.1}}, "related_pin nope: adc has no such pin"),
    ({"busy": {"related_pin": "clk", "setup": 0.1}}, "an output has no setup or hold"),
    ({"start": {"related_pin": "clk", "delay": 0.1}}, "an input has no delay or transition"),
    ({"clk": {"capacitance": "small"}}, "capacitance must be a number"),
    ({"dout": {"related_pin": "clk", "delay": 1, "edge": "both"}}, "edge must be rising or falling"),
    ({"clk": True}, "expected a dict"),
])
def test_liberty_refuses_a_wrong_timing_spec(timing, message):
    adc = lef.read(str(ADC))["adc"]
    with pytest.raises(lef.LefError) as err:
        lef.liberty(adc, timing)
    assert message in str(err.value)


def test_untimed_lists_the_digital_pins_left_without_timing():
    adc = lef.read(str(ADC))["adc"]
    assert lef.untimed(adc, {}) == ["clk", "start", "dout", "busy"]
    assert lef.untimed(adc, {"clk": {"clock": True},
                             "start": {"related_pin": "clk", "setup": 0.1}}) == ["dout", "busy"]
