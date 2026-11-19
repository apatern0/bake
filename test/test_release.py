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

"""The release format (bake/release.py): writing a block's files and
release.json, reading them back, finding releases, checksums."""

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from bake import exceptions, release
from bake.step import LibData


def _file(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return str(path)


def _libdata(src: Path) -> LibData:
    """An implemented block with most views, a corner dict, a link and a
    hard macro of its own."""
    macro = LibData(
        block="frontend", top="frontend",
        netlist_files=[_file(src / "fe" / "frontend.v", "module frontend; endmodule\n")],
        layout_info=_file(src / "fe" / "frontend.lef", "MACRO frontend\n"),
        liberty_files={"TT": [_file(src / "fe" / "frontend.lib", "library(fe) {}\n")]},
        libs=[SimpleNamespace(name="analog")],
    )
    os.symlink(src / "real_core.v", src / "core.v")
    _file(src / "real_core.v", "module core; endmodule\n")
    return LibData(
        block="core", top="core",
        netlist_files=[str(src / "core.v")],
        netlist_incdirs=[str((src / "inc").mkdir() or src / "inc")],
        layout_info=_file(src / "core.lef", "MACRO core\n"),
        liberty_files={"SS": [_file(src / "ss" / "core.lib", "ss\n")],
                       "TT": [_file(src / "tt" / "core.lib", "tt\n")]},
        sdf_files={"default": _file(src / "core.sdf", "(DELAYFILE)\n")},
        def_file=_file(src / "core.def", "DESIGN core ;\n"),
        parasitics_files={"SS": _file(src / "core.SS.spef", "*SPEF\n")},
        stream_files=[_file(src / "core.gds", "gds")],
        lvs_files=[_file(src / "core.cdl", ".SUBCKT core\n")],
        libs=[SimpleNamespace(name="stdcells")],
        vrf_defines=["NETLIST"],
        macros=[macro],
    )


def _resolve(name):
    if name not in ("stdcells", "analog"):
        raise KeyError(name)
    return SimpleNamespace(name=name)


def _publish(tmp_path: Path, version="v1", root="root") -> Path:
    """A release of _libdata() under tmp_path/root/demo/core/<version>."""
    src = tmp_path / f"src_{root}_{version}"
    src.mkdir()
    dest = release.block_dir(tmp_path / root, "demo", "core") / version
    dest.mkdir(parents=True)
    data = release.copy_libdata(_libdata(src), dest)
    release.Release(block="core", top="core", version=version, data=data,
                    project={"name": "demo", "options": {"width": 8}}).write(dest)
    release.write_checksums(dest)
    return dest


def test_round_trip(tmp_path):
    """The views are copied (a link's target, not the link), laid out by view
    and corner, and read back as the LibData they came from, with absolute
    paths, the libraries resolved and the macro under macros/."""
    dest = _publish(tmp_path)
    rel = release.Release.read(dest)
    assert rel.name == "core@v1"
    assert rel.data["liberty_files"] == {"SS": ["liberty/SS/core.lib"], "TT": ["liberty/TT/core.lib"]}
    assert rel.data["netlist_files"] == ["netlist/core.v"]
    assert not (dest / "netlist" / "core.v").is_symlink()
    assert rel.data["macros"][0]["dir"] == "macros/frontend"
    assert rel.views() == ["netlist", "lef", "liberty", "sdf", "def", "spef", "stream", "lvs"]

    data = release.libdata_from_dict(rel.data, dest, rel.block, rel.top, _resolve, rel.name)
    assert isinstance(data, LibData)
    assert data.block_dir == str(dest)
    assert Path(data.netlist_files[0]).read_text() == "module core; endmodule\n"
    assert data.liberty_files["TT"] == [str(dest / "liberty" / "TT" / "core.lib")]
    assert data.parasitics_files == {"SS": str(dest / "spef" / "SS" / "core.SS.spef")}
    assert data.stream_files == [str(dest / "stream" / "core.gds")]
    assert data.lvs_files == [str(dest / "lvs" / "core.cdl")]
    assert Path(data.netlist_incdirs[0]).is_dir()
    assert [lib.name for lib in data.libs] == ["stdcells"]
    assert data.vrf_defines == ["NETLIST"]
    fe = data.macros[0]
    assert fe.block == "frontend" and fe.top == "frontend"
    assert Path(fe.layout_info).read_text() == "MACRO frontend\n"
    assert [lib.name for lib in fe.libs] == ["analog"]


def test_same_name_in_one_view_kept_apart(tmp_path):
    """Two files of one view with the same name do not overwrite each other."""
    data = LibData(block="b", top="b", netlist_files=[_file(tmp_path / "a" / "x.v", "a"),
                                                     _file(tmp_path / "b" / "x.v", "b")])
    out = release.copy_libdata(data, tmp_path / "rel")
    assert out["netlist_files"] == ["netlist/x.v", "netlist/1_x.v"]
    assert (tmp_path / "rel" / "netlist" / "1_x.v").read_text() == "b"


def test_missing_file_named(tmp_path):
    data = LibData(block="b", top="b", layout_info=str(tmp_path / "gone.lef"))
    with pytest.raises(exceptions.BakeFileError, match="Block 'b': its lef file .*gone.lef does not exist"):
        release.copy_libdata(data, tmp_path / "rel")


def test_unknown_library_refused(tmp_path):
    dest = _publish(tmp_path)
    rel = release.Release.read(dest)
    with pytest.raises(exceptions.BakeManifestError,
                       match="Release core@v1 is mapped to library 'stdcells', which is not declared"):
        release.libdata_from_dict(rel.data, dest, rel.block, rel.top,
                                  lambda n: (_ for _ in ()).throw(KeyError(n)), rel.name)


def test_unknown_format_refused(tmp_path):
    dest = _publish(tmp_path)
    raw = json.loads((dest / "release.json").read_text())
    raw["format"] = 99
    (dest / "release.json").write_text(json.dumps(raw))
    with pytest.raises(exceptions.BakeRuntimeError, match="in format 99; this bake reads format 1"):
        release.Release.read(dest)


def test_missing_release_json(tmp_path):
    with pytest.raises(exceptions.BakeFileError, match="release.json is missing"):
        release.Release.read(tmp_path)


def test_checksums(tmp_path):
    """SHA256SUMS lists every file; a changed, removed or added file is
    reported."""
    dest = _publish(tmp_path)
    assert release.verify_checksums(dest) == []
    sums = (dest / "SHA256SUMS").read_text()
    assert "  release.json\n" in sums and "  macros/frontend/lef/frontend.lef\n" in sums
    (dest / "lef" / "core.lef").write_text("changed")
    (dest / "def" / "core.def").unlink()
    (dest / "extra.txt").write_text("new")
    assert release.verify_checksums(dest) == ["def/core.def", "extra.txt", "lef/core.lef"]


def test_versions_and_search_order(tmp_path, caplog):
    """The first root holding a version wins; a copy that differs is warned
    about; unfinished (.tmp) directories are left out."""
    first = _publish(tmp_path, "v1", "a")
    _publish(tmp_path, "v2", "a")
    _publish(tmp_path, "v1", "b")
    (release.block_dir(tmp_path / "b", "demo", "core") / "v1" / "SHA256SUMS").write_text("other\n")
    (release.block_dir(tmp_path / "a", "demo", "core") / ".v3.tmp").mkdir()
    roots = [tmp_path / "a", tmp_path / "b", tmp_path / "none"]
    with caplog.at_level(logging.WARNING):
        assert release.find(roots, "demo", "core", "v1") == first
    assert "exists under two roots with different contents" in caplog.text
    assert [v for v, _ in release.versions(roots, "demo", "core")] == ["v1", "v2"]
    assert release.find(roots, "demo", "core", "v3") is None
    assert release.find(roots, "other", "core", "v1") is None


def test_unnamed_project_directory(tmp_path):
    assert release.block_dir(tmp_path, "", "core") == tmp_path / "_" / "core"


def test_read_only(tmp_path):
    dest = _publish(tmp_path)
    release.make_read_only(dest)
    try:
        assert not os.access(dest / "lef" / "core.lef", os.W_OK)
        assert not os.access(dest, os.W_OK)
    finally:
        for path in [dest, *dest.rglob("*")]:
            path.chmod(path.stat().st_mode | 0o200)


def test_version_names():
    assert release.VERSION_RE.match("20261118-edef189")
    assert release.VERSION_RE.match("tapeout1.2_b")
    for bad in (".hidden", "-x", "a/b", "", "a b"):
        assert not release.VERSION_RE.match(bad)


# ---------------------------------------------------------------------------
# Checks without tools (bake/release_checks.py)
# ---------------------------------------------------------------------------

from bake import release_checks  # noqa: E402
from bake.step import LibData  # noqa: E402

LEF = """MACRO adc_top
  SIZE 10 BY 20 ;
  PIN clk
    DIRECTION INPUT ;
  END clk
  PIN code[0]
    DIRECTION INPUT ;
  END code[0]
  PIN ready
    DIRECTION OUTPUT ;
  END ready
  PIN VDD
    USE POWER ;
  END VDD
END adc_top
"""
LIB = """library(adc) {
  /* a comment { */
  cell(adc_top) {
    pg_pin(VDD) { pg_type : primary_power; }
    pin(clk) { direction : input; }
    bus(code) { direction : input; pin(code[0]) { } }
    pin(ready) { direction : "output"; }
  }
}
"""
NETLIST = "// netlist\nmodule adc_top(input clk, input [7:0] code, output ready);\nendmodule\n"
CDL = "* adc\n.SUBCKT adc_top clk code<0> code<7>\n+ ready VDD\n.ENDS\n"
PROFILE = """[profile]
name = "hard_macro"
corners = ["TT", "SS"]
power_pins = ["VDD"]

[uses.vrf]
needs = ["netlist"]
[uses.impl]
needs = ["lef", "liberty", "netlist"]
[uses.signoff]
needs = ["stream", "lvs"]

[checks]
max_layer = "M4"
"""


def test_parsers():
    assert release_checks.verilog_ports(NETLIST, "adc_top") == {"clk": "input", "code": "input", "ready": "output"}
    non_ansi = "module m (a, b);\n input [3:0] a;\n output reg b;\nendmodule\nmodule other(x); endmodule"
    assert release_checks.verilog_ports(non_ansi, "m") == {"a": "input", "b": "output"}
    assert release_checks.verilog_ports(non_ansi, "nothere") is None
    signals, power, size = release_checks.lef_ports(LEF, "adc_top")
    assert signals == {"clk": "input", "code": "input", "ready": "output"}
    assert power == {"VDD"} and size == (10.0, 20.0)
    signals, power = release_checks.liberty_ports(LIB, "adc_top")
    assert signals == {"clk": "input", "code": "input", "ready": "output"} and power == {"VDD"}
    assert release_checks.spice_ports(CDL, "adc_top") == ["clk", "code", "code", "ready", "VDD"]
    with pytest.raises(exceptions.BakeRuntimeError, match="braces do not balance"):
        release_checks.liberty_ports("library(x) { cell(y) {", "y")


def _adc(tmp_path, **changes) -> Path:
    src = tmp_path / "views"
    src.mkdir(exist_ok=True)
    views = {"adc.v": NETLIST, "adc.lef": LEF, "adc_tt.lib": LIB, "adc.cdl": CDL, "adc.gds": "gds", **changes}
    for name, text in views.items():
        (src / name).write_text(text)
    (tmp_path / "profile.toml").write_text(PROFILE)
    return src


def _pack_adc(tmp_path, version="a1", corner="TT", views=("netlist", "lef", "liberty", "lvs"), **kwargs):
    """Write a release of the ADC's views under tmp_path/rel."""
    src = _adc(tmp_path)
    data = LibData(
        block="adc", top="adc_top",
        netlist_files=[str(src / "adc.v")] if "netlist" in views else [],
        layout_info=str(src / "adc.lef") if "lef" in views else "",
        liberty_files={corner: [str(src / "adc_tt.lib")]} if "liberty" in views else {},
        lvs_files=[str(src / "adc.cdl")] if "lvs" in views else [],
    )
    return release.write_release(data, root=str(tmp_path / "rel"), project="chip", options={}, version=version,
                                 **kwargs)


def _profile(tmp_path):
    return release_checks.read_profile(tmp_path / "profile.toml")


def _writable(tmp_path):
    for path in [tmp_path, *tmp_path.rglob("*")]:
        path.chmod(path.stat().st_mode | 0o200)


@pytest.mark.parametrize("name, text, message", [
    ("adc.lef", LEF.replace("  PIN ready\n    DIRECTION OUTPUT ;\n  END ready\n", ""),
     "ready in netlist netlist/adc.v, not in lef lef/adc.lef"),
    ("adc_tt.lib", LIB.replace('direction : "output"', "direction : input"),
     "ready is output in netlist netlist/adc.v, output in lef lef/adc.lef, input in liberty"),
    ("adc_tt.lib", "library(adc) { cell(adc_top) {", "liberty: liberty/TT/adc_tt.lib does not parse"),
    ("adc_tt.lib", "library(adc) { cell(other) { } }", "liberty: no cell adc_top in liberty/TT/adc_tt.lib"),
    ("adc.v", "module other(); endmodule", "netlist: no module adc_top in netlist/adc.v"),
    ("adc.cdl", ".SUBCKT adc_top clk code<0> ready extra VDD\n", "extra in lvs lvs/adc.cdl"),
])
def test_integrity_refuses_views_that_disagree(tmp_path, name, text, message):
    _adc(tmp_path)
    (tmp_path / "views" / name).write_text(text)
    with pytest.raises(exceptions.BakeRuntimeError) as err:
        _pack_adc_as_is(tmp_path)
    assert "fails its integrity checks" in str(err.value) and message in str(err.value)
    assert not (tmp_path / "rel" / "chip" / "adc" / "a1").exists()


def _pack_adc_as_is(tmp_path, **kwargs):
    src = tmp_path / "views"
    data = LibData(block="adc", top="adc_top", netlist_files=[str(src / "adc.v")], layout_info=str(src / "adc.lef"),
                   liberty_files={"TT": [str(src / "adc_tt.lib")]}, lvs_files=[str(src / "adc.cdl")])
    return release.write_release(data, root=str(tmp_path / "rel"), project="chip", options={}, version="a1",
                                 **kwargs)


def test_profile_checks_corners(tmp_path):
    _adc(tmp_path)
    with pytest.raises(exceptions.BakeRuntimeError, match=r"liberty: corners FF are not the profile's \(TT, SS\)"):
        _pack_adc(tmp_path, corner="FF", views=("lef", "liberty"), profile=_profile(tmp_path))


def test_report(tmp_path):
    """The report says what the release is, whether its views agree, its
    checks and the uses of the profile."""
    where = _pack_adc(tmp_path, placeholders=["liberty.TT"], label="first cut")
    rel = release.Release.read(where)
    profile = _profile(tmp_path)
    lines = release_checks.report_lines(rel, integrity_result=release_checks.integrity(where, rel, profile),
                                        use_states=release_checks.uses(rel, profile))
    out = "\n".join(lines)
    assert out.startswith("adc a1  (label: first cut)\n")
    assert "integrity   ok    3 ports agree across netlist, lef, liberty, lvs" in out
    assert "placeholder liberty.TT" in out
    assert "uses        vrf ok · impl placeholder (liberty) · signoff missing (stream)" in out
    _writable(tmp_path)


def test_tampered_release(tmp_path):
    where = _pack_adc(tmp_path)
    _writable(tmp_path)
    (where / "lef" / "adc.lef").write_text(LEF + "\n")
    assert release.verify_checksums(where) == ["lef/adc.lef"]


def test_checks_directory(tmp_path):
    """A checks directory's run.py gets the release and the profile's
    [checks] table, and its results become quality checks."""
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "run.py").write_text(
        "import json, os\n"
        "opts = json.load(open(os.environ['BAKE_CHECKS_OPTIONS']))\n"
        "lef = os.path.join(os.environ['BAKE_RELEASE_DIR'], 'lef', 'adc.lef')\n"
        "json.dump({'layers': {'status': 'pass' if os.path.isfile(lef) else 'fail', 'value': opts['max_layer']}},\n"
        "          open(os.environ['BAKE_CHECKS_OUT'], 'w'))\n")
    _adc(tmp_path)
    where = _pack_adc(tmp_path, profile=_profile(tmp_path), checks_dir=str(checks))
    rel = release.Release.read(where)
    assert rel.checks["quality"] == {"layers": {"status": "pass", "value": "M4"}}
    _writable(tmp_path)


def test_checks_directory_failing(tmp_path):
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "run.py").write_text("import sys\nsys.exit('no licence')\n")
    with pytest.raises(exceptions.BakeRuntimeError, match=r"failed \(exit 1, no checks.json\): no licence"):
        _pack_adc(tmp_path, checks_dir=str(checks))


def test_profile_errors(tmp_path):
    (tmp_path / "p.toml").write_text('[uses.x]\nneeds = ["gds"]\n')
    with pytest.raises(exceptions.BakeRuntimeError, match="use x needs gds, which are not views"):
        release_checks.read_profile(tmp_path / "p.toml")
    (tmp_path / "bad.toml").write_text("[uses\n")
    with pytest.raises(exceptions.BakeRuntimeError, match="Profile"):
        release_checks.read_profile(tmp_path / "bad.toml")


def test_grade_skipped_is_not_signoff():
    """A skipped check has not passed: the release is a draft until it is
    waived, like a failing one."""
    rel = release.Release(block="b", top="b", version="v", label="", created="", project={}, recipe="",
                          producer={}, data={}, placeholders=[], sources={},
                          checks={"quality": {"drc": {"status": "pass"}, "lvs": {"status": "skipped"}}})
    grade = release_checks.grade(rel)
    assert grade.name == "draft" and grade.skipped == ["lvs"] and grade.failing == []
    grade = release_checks.grade(rel, {"lvs": "run by hand", "drc": "x"})
    assert grade.name == "signoff" and grade.waived == {"lvs": "run by hand"} and grade.unneeded == ["drc"]
