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
