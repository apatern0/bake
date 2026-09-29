# Copyright 2025 CERN
# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
#
# This file is a modified version of a file from tmake
# (https://gitlab.cern.ch/tmake/tmake), developed at CERN and
# distributed under the Apache License, Version 2.0.
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

"""bake's test suite.

Every test runs the CLI in-process on one of the projects under
test/projects/ (see conftest.py); the projects are real manifests that can
be run by hand. Tests that need an EDA tool skip themselves when it is
missing.
"""

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from conftest import stderr
from bake.exceptions import BakeConfigError, BakeManifestError

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

tmrg_required = pytest.mark.skipif(
    shutil.which("tmrg") is None,
    reason="tmrg not available"
)


def _sky130_available():
    """True when PDK_ROOT points at an open_pdks sky130 build (see test/pdk/fetch_sky130.sh)."""
    pdk_root = os.environ.get("PDK_ROOT")
    if not pdk_root:
        return False
    variant = os.environ.get("PDK", "sky130A")
    return (Path(pdk_root) / variant / "libs.ref" / "sky130_fd_sc_hd" / "lib").is_dir()


sky130_required = pytest.mark.skipif(
    not _sky130_available(),
    reason="PDK_ROOT does not point at an open_pdks sky130 build"
)

openroad_required = pytest.mark.skipif(
    shutil.which("yosys") is None or shutil.which("openroad") is None,
    reason="yosys or openroad not available"
)

iverilog_required = pytest.mark.skipif(
    shutil.which("iverilog") is None,
    reason="iverilog not available"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_in_stderr(capfd, string):
    assert string in stderr(capfd)


def assert_not_in_stderr(capfd, string):
    assert string not in stderr(capfd)


def assert_stderr(capfd, expect=(), expect_not=()):
    out = stderr(capfd)
    for item in expect:
        assert item in out
    for item in expect_not:
        assert item not in out


def vrf_run_sh(block="sample_target", test="sample_test", recipe="vrf"):
    """The expanded vrf run script: the stand-in flow echoes its template
    variables into it, so it shows what reached the flow."""
    return Path(f"work/{block}/{recipe}/{test}/run.sh").read_text()


# ===========================================================================
# Tests — basic CLI
# ===========================================================================

def test_no_manifest(bake, capfd):
    """Error and non-zero exit when no manifest is present."""
    assert bake.run()
    assert_in_stderr(capfd, "Manifest file not found")


def test_version_flag(bake, capfd):
    """--version prints the installed version and exits 0, manifest or not."""
    assert bake.run(["--version"]) == 0
    assert "bake 1." in str(capfd.readouterr())


def test_dry_run_excludes_clean_restart_populate(bake, capfd, project):
    """-n with -c, -r or -p is a usage error; with -f it is fine."""
    project("sample")
    for flag in ("-c", "-r", "-p"):
        assert bake.run(["sample_target", "impl", "-n", flag]) == 2
        assert_in_stderr(capfd, "cannot be combined")
    assert not bake.run(["sample_target", "impl"])
    assert not bake.run(["sample_target", "impl", "-n", "-f"])
    assert_in_stderr(capfd, "would run:         sample_target impl  [forced]")


def test_empty_manifest(bake, capfd, project):
    """Empty manifest is valid — no error."""
    project("empty")
    assert not bake.run()
    assert_not_in_stderr(capfd, "Manifest file not found")


def test_manifest_dir_flag(bake, capfd, project):
    """The -m flag finds a manifest in the given directory."""
    os.chdir(project("empty").parent)
    assert not bake.run(["-m", "empty"])
    assert_not_in_stderr(capfd, "Manifest file not found")


def test_load_nonexist(bake, capfd, project):
    """Error when load()ing a non-existing path."""
    project("load_nonexist")
    assert bake.run()
    assert_in_stderr(capfd, "does not exist")


def test_unknown_manifest_field_rejected(bake, capfd, project):
    """A misspelled block() argument is an error rather than being dropped."""
    project("unknown_field")
    assert bake.run([])
    assert_stderr(capfd,
                  expect=["manifest:22: block(): unknown argument", "rtl_file", "did you mean", "rtl_files"],
                  expect_not=["Traceback"])
    assert bake.run(["-v"])
    assert_in_stderr(capfd, "Traceback")


def test_manifest_python_errors_reported_with_line(bake, capfd, project):
    """A NameError or SyntaxError in the manifest's own code is one line with
    the location; the traceback only with -v."""
    project("name_error")
    assert bake.run([])
    assert_stderr(capfd, expect=["manifest:20: NameError: name", "blok"], expect_not=["Traceback"])
    project("syntax_error")
    assert bake.run([])
    assert_stderr(capfd, expect=["manifest:20: SyntaxError"], expect_not=["Traceback"])


def test_spec_argument_coercions(bake, capfd, project):
    """A single string or a Path where a list is expected, and a single file
    per corner, are accepted; a missing layout_info entry is a warning."""
    project("coercions")
    assert not bake.run([])
    assert_in_stderr(capfd, "layout_info 'missing.lef' does not exist")
    from bake.context import context
    x, lib, e, t = context.blocks["x"], context.libs["l"], context.envs["e"], context.tests[0]
    assert [Path(f).name for f in x.rtl_files] == ["sample.v"]
    assert x.libs == ["l"] and [Path(f).name for f in x.sdc_files] == ["base.v"]
    assert [Path(f).name for f in lib.liberty_files["TT"]] == ["base.v"]
    assert lib.layout_info.endswith("rtl/leaf.v missing.lef") and lib.layout_info.startswith("/")
    assert [Path(f).name for f in e.vrf_files] == ["sample_tb.v"] and e.vrf_defines == ["X"]
    assert t.includes == ["e"]


def test_duplicate_block_raises(bake, capfd, project):
    """Registering two blocks with the same name raises a manifest error."""
    project("duplicate_block")
    assert bake.run([])
    assert_stderr(capfd, expect=["manifest:23: Redefinition of block dup"], expect_not=["Traceback"])


def test_broken_builtin_is_fatal(bake, capfd, project, monkeypatch):
    """A builtin step that fails to load stops bake instead of being skipped."""
    project("sample")
    import bake.loader as loader
    real_load = loader.load

    def load(path):
        if path.endswith("/builtin/tmr"):
            raise RuntimeError("boom")
        return real_load(path)

    monkeypatch.setattr(loader, "load", load)
    assert bake.run([]) == 1
    assert_in_stderr(capfd, "Failed to load builtin step 'tmr': boom")


def test_duplicate_test_raises(bake, capfd, project):
    """The same test name twice for one block is an error; the same name on
    another block is not."""
    project("duplicate_test")
    assert bake.run([])
    assert_in_stderr(capfd, "Redefinition of test t for block a")


def test_removed_bake_option_rejected(bake, capfd, project):
    """config.bake.vrf_simulator no longer exists; setting it is an error."""
    project("removed_option")
    assert bake.run([])
    assert_in_stderr(capfd, "config.bake has no attribute")


def test_step_config_typo_rejected(bake, capfd, project):
    """Assigning an attribute a builtin step's config does not declare is an
    error, not silently ignored."""
    project("config_typo")
    assert bake.run([])
    assert_stderr(capfd, expect=["config.vrf has no attribute", "simulater", "Known attributes: defines, delays, flow"])


def test_config_missing_section_is_attribute_error():
    """A missing section raises an AttributeError too, so hasattr() works."""
    from bake.context import context
    from bake.exceptions import BakeConfigError
    assert not hasattr(context.config, "no_such_section")
    assert getattr(context.config, "no_such_section", None) is None
    with pytest.raises(BakeConfigError):
        _ = context.config.no_such_section


# ===========================================================================
# Tests — step and block listing
# ===========================================================================

def test_builtin_steps_always_listed(bake, capfd, project):
    """The builtin steps always appear in the step listing; only they do."""
    project("flows_only")
    assert not bake.run()
    assert_stderr(capfd, expect=["- vrf", "- impl", "- tmr"], expect_not=["dummy"])


def test_blocks_listed(bake, capfd, project):
    """Blocks registered with block() appear in the listing."""
    project("sample")
    assert not bake.run()
    assert_in_stderr(capfd, "sample_target")


def test_target_alias_works(bake, capfd, project):
    """The target() function, the deprecated alias of block(), still works
    and warns where it is called."""
    project("target_alias")
    assert not bake.run()
    err = capfd.readouterr().err
    assert "my_block" in err
    assert err.count("manifest:21: target() is deprecated and will be removed in a future major release; "
                     "use block()") == 1


def test_block_without_rtl_files_not_listed(bake, capfd, project):
    """A block without rtl_files is valid metadata but not listed as runnable."""
    project("no_rtl")
    assert not bake.run([])
    assert_stderr(capfd, expect=["withrtl"], expect_not=["nortl"])


def test_lib_listed(bake, capfd, project):
    """A lib() definition appears in the -l library listing."""
    project("lib")
    assert not bake.run(["-l"])
    assert_in_stderr(capfd, "mylib")


def test_custom_step_appears_in_listing(bake, capfd, project):
    """A step loaded via load() in the manifest appears in the step listing."""
    project("sample_check")
    assert not bake.run()
    assert_in_stderr(capfd, "- check")


def test_vcd_and_saif_files_accepted(bake, capfd, project):
    """vcd_files/saif_files take a file, a list or a corner dict; the plain
    forms become the "default" corner."""
    project("vcd_files")
    assert not bake.run([])
    from bake.context import context
    assert list(context.blocks["plain"].vcd_files) == ["default"]
    assert set(context.blocks["corners"].vcd_files) == {"tt", "ss"}
    assert context.blocks["corners"].vcd_files["ss"][0].endswith("rtl/base.v")
    assert context.blocks["corners"].saif_files["default"][0].endswith("rtl/base.v")
    # they reach the step data (dict(block.vcd_files) used to raise on a list)
    assert not bake.run(["corners", "impl"])


# ===========================================================================
# Tests — tab-completion cache
# ===========================================================================

def _cache_enabled(monkeypatch, tmp_run_dir):
    monkeypatch.delenv("BAKE_NO_CACHE")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_run_dir / "xdg"))
    return tmp_run_dir / "xdg" / "bake" / "completion_cache.json"


def test_completion_cache_written_and_read(bake, project, monkeypatch, tmp_run_dir):
    """A successful load stores the project's blocks, tests, steps and config
    keys under $XDG_CACHE_HOME; the completers read them back."""
    from bake import completion_cache
    cache_file = _cache_enabled(monkeypatch, tmp_run_dir)
    project("sample")
    assert not bake.run([])
    assert cache_file.is_file()
    assert not (cache_file.parent / "completion_cache.json.tmp").exists()

    completion_cache.load_from_file()
    assert "sample_target" in completion_cache.get_targets()
    assert completion_cache.get_tests("sample_target") == ["sample_test"]
    assert "vrf" in completion_cache.get_steps()
    assert "vrf.simulator" in completion_cache.get_config_keys()


def test_completion_cache_prunes_missing_directories(bake, project, monkeypatch, tmp_run_dir):
    """Entries whose directory is gone are dropped on the next store."""
    import json
    cache_file = _cache_enabled(monkeypatch, tmp_run_dir)
    project("sample")
    assert not bake.run([])
    gone = str(tmp_run_dir / "gone")
    data = json.loads(cache_file.read_text())
    data[gone] = {"targets_tests": {}, "config_keys": [], "steps": []}
    cache_file.write_text(json.dumps(data))
    assert not bake.run([])
    assert gone not in json.loads(cache_file.read_text())


def test_completion_cache_corrupt_file_ignored(bake, project, monkeypatch, tmp_run_dir):
    """A corrupt cache file is ignored and rewritten, never fatal."""
    from bake import completion_cache
    cache_file = _cache_enabled(monkeypatch, tmp_run_dir)
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("{not json")
    project("sample")
    completion_cache.load_from_file()
    assert completion_cache.get_targets() == []
    assert not bake.run([])
    completion_cache.load_from_file()
    assert "sample_target" in completion_cache.get_targets()


def test_completion_cache_disabled_by_env(bake, project, monkeypatch, tmp_run_dir):
    """BAKE_NO_CACHE suppresses all cache I/O (the fixture sets it)."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_run_dir / "xdg"))
    project("sample")
    assert not bake.run([])
    assert not (tmp_run_dir / "xdg").exists()


# ===========================================================================
# Tests — custom steps
# ===========================================================================

def test_step_directory_loaded_like_builtin(bake, project):
    """A step laid out like a built-in one (manifest + flow/ next to it) is
    brought in with load(); its flow needs no dir= and it runs in a recipe."""
    project("sample_check")
    assert not bake.run(["sample_target", "check-vrf"])
    assert Path("work/sample_target/check/output/check_result.txt").is_file()


def test_step_defined_in_project_manifest(bake, project):
    """A Step subclass in the project manifest itself registers and runs."""
    project("inline_step")
    assert not bake.run(["sample_target", "nop"])
    assert Path("work/sample_target/nop/output/nop.txt").is_file()


def test_custom_step_incremental(bake, capfd, project):
    """A step is skipped on re-run when outputs are newer than sources."""
    project("sample_check")
    assert not bake.run(["sample_target", "check"])
    assert not bake.run(["sample_target", "check", "-v"])
    assert_in_stderr(capfd, "up-to-date")


def test_custom_step_force_reruns(bake, capfd, project):
    """-f causes re-execution even when outputs are up-to-date."""
    project("sample_check")
    assert not bake.run(["sample_target", "check"])
    assert not bake.run(["sample_target", "check", "-f", "-v"])
    assert_not_in_stderr(capfd, "up-to-date")


def test_custom_step_clean(bake, project):
    """-c removes the step's work directory."""
    project("sample_check")
    assert not bake.run(["sample_target", "check"])
    assert Path("work/sample_target/check/output/check_result.txt").exists()
    assert not bake.run(["sample_target", "check", "-c"])
    assert not Path("work/sample_target/check").exists()


def test_is_last_and_base_variables_in_custom_step(bake, project):
    """A custom step sees is_last set by the orchestrator and gets $BAKE_BLOCK
    and $BAKE_TOP from the base class without overriding build_tpl_dict."""
    project("sample_check")
    result = Path("work/sample_target/check/output/check_result.txt")
    assert not bake.run(["sample_target", "check"])
    assert result.read_text().strip() == "BLOCK=sample_target TOP=sample IS_LAST=True"
    assert not bake.run(["sample_target", "check-vrf", "-f"])
    assert result.read_text().strip() == "BLOCK=sample_target TOP=sample IS_LAST=False"


def test_check_post_failure_reported(bake, capfd, project):
    """check_post() failure is reported when a step exits 0 but produces no outputs."""
    project("sample_check")
    assert bake.run(["sample_target", "check", "-o", "check.flow=nothing"])
    assert_in_stderr(capfd, "did not produce all required files")


def test_flow_script_not_a_template_stays_executable(bake, project):
    """A flow file that is not a template keeps its mode in the work
    directory, so a plain run script can be executed."""
    project("sample_check")
    assert not bake.run(["sample_target", "check", "-o", "check.flow=plain_run"])
    assert os.access("work/sample_target/check/run.sh", os.X_OK)


# ===========================================================================
# Tests — up-to-date check
# ===========================================================================

def test_failed_step_is_not_up_to_date(bake, capfd, project, monkeypatch):
    """A step whose script fails after writing its outputs runs again next
    time instead of being reported up to date."""
    project("incremental")
    monkeypatch.setenv("CHECK_EXIT", "1")
    assert bake.run(["sample_target", "gen"])
    assert Path("work/sample_target/gen/output/gen.txt").is_file()
    assert not Path("work/sample_target/gen/.bake_stamp.json").exists()
    assert not bake.run(["sample_target", "gen", "-n"])
    assert_in_stderr(capfd, "would run:         sample_target gen  [last run did not complete]")
    monkeypatch.delenv("CHECK_EXIT")
    assert not bake.run(["sample_target", "gen"])
    assert_stderr(capfd, expect=["did not complete", "Step gen completed"], expect_not=["up-to-date"])
    assert not bake.run(["sample_target", "gen"])
    assert_in_stderr(capfd, "up-to-date")


def test_config_change_reruns_step(bake, capfd, project):
    """A different config value reaching the flow re-runs the step; the same
    value again does not."""
    project("incremental")
    assert not bake.run(["sample_target", "gen"])
    assert not bake.run(["sample_target", "gen", "-o", "gen.mode=fast"])
    assert_stderr(capfd, expect=["different configuration", "Step gen completed"])
    assert Path("work/sample_target/gen/output/gen.txt").read_text().strip() == "MODE=fast"
    assert not bake.run(["sample_target", "gen", "-o", "gen.mode=fast"])
    assert_in_stderr(capfd, "up-to-date")


def test_verbosity_does_not_rerun_step(bake, capfd, project):
    """-v and -i are not build inputs."""
    project("incremental")
    assert not bake.run(["sample_target", "gen"])
    assert not bake.run(["sample_target", "gen", "-v", "-i"])
    assert_in_stderr(capfd, "up-to-date")


def test_flow_script_change_reruns_step(bake, capfd, project):
    """Populating an untouched copy of the flow does not re-run the step;
    editing the copy does."""
    project("incremental")
    assert not bake.run(["sample_target", "gen"])
    assert not bake.run(["sample_target", "gen", "-p"])
    assert not bake.run(["sample_target", "gen"])
    assert_in_stderr(capfd, "up-to-date")
    script = Path("flow/sample_target/gen/run.sh.tpl")
    script.write_text(script.read_text() + "# edited\n")
    assert not bake.run(["sample_target", "gen"])
    assert_stderr(capfd, expect=["different flow scripts", "Step gen completed"])


def test_source_list_change_reruns_step(bake, capfd, project):
    """Removing a file from rtl_files re-runs the step even though the
    remaining files are untouched."""
    project("incremental")
    assert not bake.run(["sample_target", "gen"])
    manifest = Path("manifest")
    manifest.write_text(manifest.read_text().replace(', "../rtl/base.v"', ""))
    assert not bake.run(["sample_target", "gen"])
    assert_stderr(capfd, expect=["different source file list", "Step gen completed"])


def test_symlinked_source_change_detected(bake, capfd, project):
    """A source reached through a symlink is compared by its target's mtime."""
    project("incremental")
    assert Path("linked.v").is_symlink()
    assert not bake.run(["sample_target", "gen"])
    time.sleep(0.05)
    Path("../rtl/sample_tb.v").touch()
    assert not bake.run(["sample_target", "gen"])
    assert_stderr(capfd, expect=["Source files are newer", "linked.v", "Step gen completed"])


def test_up_to_date_step_still_checks_outputs(bake, capfd, project):
    """A skipped step's outputs are verified as if it had just run."""
    project("incremental")
    assert not bake.run(["sample_target", "gen"])
    assert not bake.run(["sample_target", "gen"])
    assert_in_stderr(capfd, "up-to-date")


# ===========================================================================
# Tests — vrf, impl and dummy steps and their recipes
# ===========================================================================

def test_sample_vrf(bake, capfd, project):
    project("sample")
    assert not bake.run(["sample_target", "vrf"])
    assert_not_in_stderr(capfd, "Error during bake operation: Non-zero return code")


def test_legacy_target_step_argument_rejected(bake, capfd, project):
    """Old-style 'target-step' combined argument is rejected with a clear error."""
    project("sample")
    assert bake.run(["sample_target-vrf"])
    assert_in_stderr(capfd, "Expected 'bake <block> <recipe>'")


def test_vrf_nonzero_exitcode(bake, capfd, project):
    """Non-zero exit code from the flow script is surfaced as a bake error."""
    project("sample")
    assert bake.run(["sample_target", "vrf", "-o", "vrf.flow=failing_vrf"])
    assert_in_stderr(capfd, "Error during bake operation: Non-zero return code")


def test_vrf_explicit_test(bake, project):
    project("sample")
    assert not bake.run(["sample_target", "vrf", "-t", "sample_test"])


def test_impl(bake, project):
    project("sample")
    assert not bake.run(["sample_target", "impl"])
    assert Path("work/sample_target/impl/output/sample.v").exists()


def test_impl_update_required(bake, capfd, project):
    """Second impl run is skipped when outputs are newer than sources."""
    project("sample")
    assert not bake.run(["sample_target", "impl"])
    assert not bake.run(["sample_target", "impl", "-v"])
    assert_in_stderr(capfd, "up-to-date")


def _elaborated_lib_names(block, recipe="impl"):
    from bake.step import Recipe
    r = Recipe(block, recipe)
    r.elaborate()
    return [lib.name for lib in r.data[0].libs]


def test_default_libs(bake, capfd, project):
    """A block without libs= gets config.bake.default_libs; one with libs=
    uses exactly those; the manifest can spell out defaults plus extras."""
    project("default_libs")
    assert not bake.run([])
    assert _elaborated_lib_names("plain") == ["cells"]
    assert _elaborated_lib_names("own") == ["other"]
    assert _elaborated_lib_names("more") == ["cells", "other"]
    assert not bake.run(["plain", "impl"])
    assert_not_in_stderr(capfd, "default libs")   # a silent fallback


def test_default_libs_option_appends_and_must_exist(bake, capfd, project):
    """-o bake.default_libs=name adds to the defaults for the run; an unknown
    name is a manifest error."""
    project("default_libs")
    assert not bake.run(["plain", "impl", "-o", "bake.default_libs=other"])
    assert _elaborated_lib_names("plain") == ["cells", "other"]
    assert bake.run(["plain", "impl", "-o", "bake.default_libs=nope"])
    assert_in_stderr(capfd, "default_libs names 'nope', which is not a registered library")


def test_impl_liberty_corners_consistent(bake, capfd, project):
    """A library lacking Liberty for a corner another library uses is
    rejected before anything runs; a corner nobody uses is not required."""
    project("lib_corners")
    assert not bake.run(["ok", "impl", "-n"])
    assert not bake.run(["partial", "impl", "-n"])
    assert bake.run(["broken", "impl", "-n"])
    assert_stderr(capfd, expect=["flow corners in use are TT, SS", "tt_only", ": SS"])


def test_impl_sdf_reaches_vrf(bake, project):
    """The SDF an impl step produces is handed to the following vrf step."""
    project("sample")
    assert not bake.run(["sample_target", "impl-vrf"])
    run_sh = vrf_run_sh(recipe="impl-vrf")
    assert "SDF=" in run_sh and "work/sample_target/impl/output/sample.sdf" in run_sh


def test_dummy_always_reruns(bake, capfd, project):
    """Dummy step (output_files=[]) always re-executes; never skipped."""
    project("sample")
    assert not bake.run(["sample_target", "dummy"])
    assert not bake.run(["sample_target", "dummy", "-v"])
    assert_not_in_stderr(capfd, "up-to-date")


@pytest.mark.parametrize("recipe, impl_dir", [
    ("dummy-vrf", None),
    ("impl-dummy", "impl"),
    ("dummy-impl", "dummy-impl"),        # impl's work dir is named after its recipe path
    ("dummy-impl-vrf", "dummy-impl"),
    ("impl-dummy-vrf", "impl"),
])
def test_recipes_with_dummy(bake, project, recipe, impl_dir):
    """Recipes combining dummy with impl and vrf run through; impl's outputs land
    under its recipe path."""
    project("sample")
    assert not bake.run(["sample_target", recipe])
    if impl_dir:
        assert Path(f"work/sample_target/{impl_dir}/output/sample.v").exists()


# ===========================================================================
# Tests — builtin vrf flow: pass/fail criteria and seed (fake simulator)
# ===========================================================================

def _fake_icarus(monkeypatch, project_dir, output):
    monkeypatch.setenv("PATH", f"{project_dir / 'fake_bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SIM_OUTPUT", output)


def test_vrf_exit_code_only_passes_on_error_line(bake, capfd, project, monkeypatch):
    """Without criteria only the exit code counts: an ERROR line with exit 0
    is a pass (Icarus returns 0 after $error). The seed is always logged."""
    _fake_icarus(monkeypatch, project("criteria"), "ERROR: bad value")
    assert not bake.run(["dut", "vrf", "-t", "exit_code_only"])
    assert_stderr(capfd, expect=["Simulation seed: ", "Step vrf completed"])


def test_vrf_fail_regex(bake, capfd, project, monkeypatch):
    """A line matching vrf_fail_regex fails the test although the simulator
    exited 0; without such a line it passes."""
    _fake_icarus(monkeypatch, project("criteria"), "ERROR: bad value")
    assert bake.run(["dut", "vrf", "-t", "fail_regex"])
    assert_in_stderr(capfd, "match vrf_fail_regex")
    monkeypatch.setenv("FAKE_SIM_OUTPUT", "no errors here")
    assert not bake.run(["dut", "vrf", "-t", "fail_regex"])


def test_vrf_pass_regex(bake, capfd, project, monkeypatch):
    """With vrf_pass_regex, a log without a matching line fails the test."""
    _fake_icarus(monkeypatch, project("criteria"), "sim ran")
    assert bake.run(["dut", "vrf", "-t", "pass_regex"])
    assert_in_stderr(capfd, "no line matches vrf_pass_regex")
    monkeypatch.setenv("FAKE_SIM_OUTPUT", "TEST PASSED")
    assert not bake.run(["dut", "vrf", "-t", "pass_regex"])
    assert "TEST PASSED" in Path("work/dut/vrf/pass_regex/bake_sim.log").read_text()


def _vrf_run_script():
    """The built-in vrf flow's run script, loaded as a module."""
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    import bake as bake_pkg
    path = Path(bake_pkg.__file__).parent / "builtin" / "vrf" / "flow" / "run.py.tpl"
    spec = spec_from_loader("vrf_run", SourceFileLoader("vrf_run", str(path)))
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("counts, retval", [
    ({"UVM_ERROR": 0, "UVM_FATAL": 0}, 0),
    ({"UVM_ERROR": 3, "UVM_FATAL": 0}, 2),
    ({"UVM_ERROR": 0, "UVM_FATAL": 1}, 2),
    ({"UVM_ERROR": 21008, "UVM_FATAL": 0}, 2),     # "%s :%5d" leaves no space
    ({"UVM_ERROR": 123456, "UVM_FATAL": 0}, 2),
])
def test_vrf_uvm_summary_counts(tmp_path, counts, retval):
    """The UVM report summary fails the test on any UVM_ERROR or UVM_FATAL,
    however many digits the count has; a message quoting a severity before
    the summary does not count."""
    log = tmp_path / "sim.log"
    lines = ["UVM_ERROR : 7", "--- UVM Report Summary ---", "", "** Report counts by severity",
             "UVM_INFO :%5d" % 42, "UVM_WARNING :%5d" % 0]
    lines += ["%s :%5d" % (severity, count) for severity, count in counts.items()]
    log.write_text("\n".join(lines) + "\n")
    assert _vrf_run_script().check_uvm_summary(str(log)) == retval


def test_vrf_uvm_summary_missing(tmp_path):
    """A log without the UVM report summary fails: the test did not finish."""
    log = tmp_path / "sim.log"
    log.write_text("UVM_ERROR :    0\n")
    assert _vrf_run_script().check_uvm_summary(str(log)) == 2


def test_vrf_seed_from_config(bake, capfd, project, monkeypatch):
    """-o vrf.seed=N fixes the seed and it reaches the flow."""
    import json
    _fake_icarus(monkeypatch, project("criteria"), "ok")
    assert not bake.run(["dut", "vrf", "-t", "exit_code_only", "-o", "vrf.seed=42"])
    assert_in_stderr(capfd, "Simulation seed: 42")
    assert json.loads(Path("work/dut/vrf/exit_code_only/bake_vars.json").read_text())["BAKE_SIM_SEED"] == "42"


# ===========================================================================
# Tests — TMR step (tmrg required)
# ===========================================================================

@tmrg_required
@pytest.mark.parametrize("recipe, outputs", [
    ("tmr", ["tmr"]),
    ("tmr-vrf", ["tmr"]),
    ("tmr-impl", ["tmr", "tmr-impl"]),
    ("tmr-impl-vrf", ["tmr", "tmr-impl"]),
    ("tmr-dummy", ["tmr"]),
    ("tmr-dummy-impl", ["tmr", "tmr-dummy-impl"]),
])
def test_tmr_recipes(bake, project, recipe, outputs):
    """Recipes starting with tmr produce the triplicated netlist at every step."""
    project("sample")
    assert not bake.run(["sample_target", recipe])
    for step_dir in outputs:
        assert Path(f"work/sample_target/{step_dir}/output/sampleTMR.v").exists()


def test_tmr_refuses_same_basename(bake, capfd, project):
    """Two RTL files with the same name would collide in tmr's output."""
    project("tmr_clash")
    assert bake.run(["sample_target", "tmr", "-n"])
    assert_stderr(capfd, expect=["would overwrite each other", "sample.v:", "Rename one of them"])


@tmrg_required
def test_tmr_impl_update_required(bake, project):
    """tmr-impl is skipped on re-run when outputs are up-to-date."""
    project("sample")
    assert not bake.run(["sample_target", "tmr-impl", "-v"])
    assert not bake.run(["sample_target", "tmr-impl"])
    assert Path("work/sample_target/tmr-impl/output/sampleTMR.v").exists()


@tmrg_required
def test_tmr_clean(bake, project):
    """-c removes only the tmr work directory."""
    project("sample")
    assert not bake.run(["sample_target", "tmr"])
    assert not bake.run(["sample_target", "tmr", "-c"])
    assert not Path("work/sample_target/tmr/output/sampleTMR.v").exists()


@tmrg_required
def test_tmr_impl_clean(bake, project):
    """-c on tmr-impl removes only the tmr-impl work directory, leaving tmr intact."""
    project("sample")
    assert not bake.run(["sample_target", "tmr-impl"])
    assert not bake.run(["sample_target", "tmr-impl", "-c"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()
    assert not Path("work/sample_target/tmr-impl/output/sampleTMR.v").exists()


# ===========================================================================
# Tests — hierarchical designs (includes and dependencies)
# ===========================================================================

def test_include_forms_parse(bake, capfd, project):
    """List and dict includes parse; a block with a recipe-form include is
    listed with the state of its dependency."""
    project("hier")
    assert not bake.run([])
    assert_stderr(capfd, expect=[
        "- top_dict",
        "- top2  (needs block impl: not built)",
        "- top3  (needs block tmr-impl: not built)",
    ])


def test_include_string_rejected(bake, capfd, project):
    project("hier_string")
    assert bake.run([])
    assert_in_stderr(capfd, "Block includes must be a list or a dict.")


def test_include_unknown_step_rejected(bake, capfd, project):
    """An invalid step name in an include recipe fails once all manifests are loaded."""
    project("hier_bad_step")
    assert bake.run([])
    assert_stderr(capfd, expect=("unknown step", "invalid"))


def test_include_unknown_block_rejected(bake, capfd, project):
    project("hier_unknown_block")
    assert bake.run([])
    assert_stderr(capfd, expect=("includes unknown block", "ghost"))


def test_include_forward_reference(bake, capfd, project):
    """A block may include one that is defined later in the manifest."""
    project("hier_forward")
    assert not bake.run([])
    assert_in_stderr(capfd, "needs block impl: not built")


def test_include_cycle_rejected(bake, capfd, project):
    project("hier_cycle")
    assert bake.run([])
    assert_in_stderr(capfd, "include cycle")


def test_skip_on_include_errors_rejected(bake, capfd, project):
    """The removed flag is reported with the migration message, not silently ignored."""
    project("removed_flag")
    assert bake.run([])
    assert_in_stderr(capfd, "skip_on_include_errors has been removed")


def test_include_builds_dependency(bake, capfd, project):
    """Running vrf on top2 builds `block impl` first and simulates with its netlist."""
    project("hier")
    assert not bake.run(["top2", "vrf"])
    assert "Running impl on block block (dependency of top2)" in stderr(capfd)
    assert Path("work/block/impl/output/block.v").is_file()
    design = next(ln for ln in vrf_run_sh("top2", "top2_test").splitlines() if ln.startswith("echo 'DESIGN="))
    assert "work/block/impl/output/block.v" in design    # the netlist stands in ...
    assert "rtl/block.v" not in design                   # ... for the RTL
    assert "rtl/top.v" in design
    assert not bake.run([])
    assert_in_stderr(capfd, "top2  (needs block impl: up to date)")


def test_include_dependency_up_to_date_skipped(bake, capfd, project):
    project("hier")
    assert not bake.run(["top2", "vrf"])
    assert not bake.run(["top2", "vrf"])
    assert_in_stderr(capfd, "Output files are up-to-date, skipping step impl")


def test_include_stale_dependency_rebuilt(bake, capfd, project):
    """A dependency whose sources changed is rebuilt before the block runs."""
    project("hier")
    assert not bake.run(["top2", "vrf"])
    time.sleep(0.05)
    Path("../rtl/block.v").touch()
    assert not bake.run([])
    assert_in_stderr(capfd, "top2  (needs block impl: stale (source files changed))")
    assert not bake.run(["top2", "vrf"])
    assert_stderr(capfd, expect=["Source files are newer", "Step impl completed"])


def test_force_does_not_force_dependency(bake, capfd, project):
    """-f re-runs the requested recipe only; an up-to-date dependency is skipped."""
    project("hier")
    assert not bake.run(["top2", "vrf"])
    assert not bake.run(["top2", "vrf", "-f"])
    assert_stderr(capfd, expect=["Output files are up-to-date, skipping step impl", "Force flag set"])


def test_clean_leaves_dependency(bake, project):
    """-c removes the requested block's work directory, not the dependency's."""
    project("hier")
    assert not bake.run(["top2", "vrf"])
    assert not bake.run(["top2", "vrf", "-c"])
    assert not Path("work/top2/vrf/top2_test").exists()
    assert Path("work/block/impl/output/block.v").is_file()


def test_populate_only_last_step(bake, project):
    """-p populates the flow of the recipe's last step only: not its
    dependencies', and runs nothing."""
    project("hier")
    assert not bake.run(["top2", "vrf", "-p"])
    assert Path("flow/top2/vrf/top2_test").is_dir()
    assert not Path("flow/block").exists()
    assert not Path("work").exists()


@pytest.mark.parametrize("recipe, message", [
    ("impl-tmr", "Step tmr cannot run on block 'sample_target' after impl: tmr takes rtl, "
                 "and the block after impl is lib."),
    ("impl-impl", "Step impl cannot run on block 'sample_target' after impl"),
])
def test_step_refuses_kind(bake, capfd, project, recipe, message):
    """A step refuses data of a kind it does not take, before anything runs."""
    project("sample")
    assert bake.run(["sample_target", recipe, "-n"])
    assert_stderr(capfd, expect=[message], expect_not=["Traceback"])


def test_macro_is_included_as_a_macro(bake, capfd, project):
    """A macro() included into RTL is a macro: impl gets its abstracts, vrf
    its netlist; on its own it is simulated as a netlist and refused by tmr."""
    project("macro")
    assert not bake.run(["-l"])
    assert_stderr(capfd, expect=["Available macros:\\n[bake] INFO\\t - macro"])
    assert not bake.run([])
    assert_stderr(capfd, expect=["- macro  (lib)", "- impl  (rtl -> lib)", "- tmr  (rtl)", "- vrf  (rtl or lib)"])
    assert not bake.run(["top", "impl"])
    tpl = json.loads(Path("work/top/impl/bake_vars.json").read_text())
    assert tpl["BAKE_MACRO_PHYSICAL"][0].endswith("rtl/block.v")
    assert tpl["BAKE_MACRO_LIBERTY_FILES_TC"][0].endswith("rtl/block.v")
    assert tpl["BAKE_DESIGN_VERILOG_FILES"][0].endswith("rtl/top.v")
    assert not bake.run(["top", "vrf"])
    design = next(ln for ln in vrf_run_sh("top", "top_test").splitlines() if ln.startswith("echo 'DESIGN="))
    assert "rtl/block.v" in design and "rtl/top.v" in design
    assert not bake.run(["macro", "vrf"])
    assert bake.run(["macro", "tmr", "-n"])
    assert_in_stderr(capfd, "tmr takes rtl, and the block is lib.")


@pytest.mark.parametrize("manifest, message", [
    ('block(name="both", top="top", rtl_files=["../rtl/top.v"], netlist_files=["../rtl/block.v"])',
     "Block 'both': netlist_files is not a block() argument: block() declares RTL. "
     "Declare an implemented block with macro() and include it."),
    ('lib(name="cells", netlist_files=["../rtl/block.v"])\n'
     'block(name="top", top="top", includes=["cells"], rtl_files=["../rtl/top.v"])',
     "Block 'top' includes 'cells', which is a lib(): a cell library is named in libs=, "
     "not included."),
    ('macro(name="m", top="block", netlist_files=["../rtl/block.v"])\n'
     'block(name="top", top="top", libs=["m"], rtl_files=["../rtl/top.v"])',
     "Block 'top': libs= names 'm', which is a macro(), not a cell library. "
     "Include it instead: includes=[\"m\"]."),
])
def test_lib_and_macro_roles_enforced(bake, capfd, project, manifest, message):
    """A netlist is declared with lib() (a cell library, named in libs=) or
    macro() (an implemented block, included); each is refused in the
    other's place, and block() takes RTL only."""
    project("macro")
    Path("manifest").write_text("from bake import block, lib, macro\n" + manifest + "\n")
    assert bake.run(["top", "tmr", "-n"])
    assert message in capfd.readouterr().err


def test_include_kind_checked_on_load(bake, capfd, project):
    """An include whose recipe hands a step a kind it does not take is
    refused once all manifests are loaded, before anything is elaborated."""
    project("hier_bad_kind")
    assert bake.run([])
    assert_in_stderr(capfd, "Block 'top' includes 'macro' with recipe 'tmr': step tmr takes rtl, "
                            "and 'macro' is lib.")


def test_custom_kind(bake, capfd, project):
    """A kind of design defined by a manifest is listed with its kind and its
    step's signature, merges with its own kind through an include, is turned
    into RTL by its step as a dependency, and is refused by a step that does
    not take it, with the step that would convert it."""
    project("custom_kind")
    assert not bake.run([])
    assert_stderr(capfd, expect=["- tables  (table)", "- top  (needs tables gen: not built)",
                                 "- gen  (table -> rtl)"])
    assert not bake.run(["top", "vrf"])
    assert "Running gen on block tables (dependency of top)" in stderr(capfd)
    generated = Path("work/tables/gen/output/tables.v").read_text()
    assert generated.index("table.txt") < generated.index("extra.txt")   # the include's first
    design = next(ln for ln in vrf_run_sh("top", "top_test").splitlines() if ln.startswith("echo 'DESIGN="))
    assert "work/tables/gen/output/tables.v" in design and "rtl/top.v" in design
    assert bake.run(["tables", "impl", "-n"])
    assert_in_stderr(capfd, "Step impl cannot run on block 'tables': impl takes rtl, and the block is table. "
                            "A step that turns table into rtl: gen (e.g. recipe gen-impl).")


def test_custom_kind_include_refused(bake, capfd, project, monkeypatch):
    """Including a design as it is into a block that cannot take its kind is
    refused on load, suggesting the step that converts it."""
    monkeypatch.setenv("BAKE_TEST_BAD_INCLUDE", "1")
    project("custom_kind")
    assert bake.run([])
    # The captured log is compared as a repr, which escapes ' once " occurs.
    assert_stderr(capfd, expect=["is rtl and cannot include", "which is table. Include it with a recipe "
                                 'that turns it into rtl or lib, e.g. {"table": "gen"}.'])


def test_custom_spec_argument_typo(bake, capfd, project):
    """A spec a manifest defines reports a misspelled argument like block() does."""
    project("custom_kind_typo")
    assert bake.run([])
    assert_in_stderr(capfd, "note(): unknown argument 'txt' (did you mean 'text'?)")


def test_impl_refuses_include_without_abstracts(bake, capfd, project):
    """impl on a block whose implemented sub-block has no LEF/Liberty (the
    stand-in flow writes none) is refused with the reason."""
    project("hier")
    assert bake.run(["top2", "impl"])
    assert_stderr(capfd, expect=["needs abstracts"], expect_not=["Traceback"])
    assert not Path("work").exists()


def test_dry_run_reports_plan(bake, capfd, project):
    """-n reports dependency and own steps without executing anything."""
    project("hier")
    assert not bake.run(["top2", "vrf", "-n"])
    assert_stderr(capfd, expect=[
        "would run:         block impl  (dependency of top2)",
        "would run:         top2 vrf",
        "Dry run",
    ])
    assert not Path("work").exists()
    assert not bake.run(["top2", "vrf"])
    assert not bake.run(["top2", "vrf", "-n"])
    assert_stderr(capfd, expect=[
        "up to date:        block impl  (dependency of top2)",
        "would run:         top2 vrf",          # vrf declares no outputs
    ])


def test_dry_run_blocked_recipe_exits_nonzero(bake, capfd, project):
    """-n on a recipe a step refuses reports the reason and exits 1."""
    project("hier")
    assert bake.run(["top2", "impl", "-n"])
    assert_in_stderr(capfd, "needs abstracts")


@tmrg_required
def test_include_tmr_impl_builds_dependency(bake, capfd, project):
    """A tmr-impl dependency chain is built on demand."""
    project("hier")
    assert not bake.run([])
    assert_in_stderr(capfd, "needs block tmr-impl: not built")
    assert not bake.run(["top3", "dummy"])
    assert Path("work/block/tmr-impl/output/blockTMR.v").is_file()


# ===========================================================================
# Tests — CLI flags: populate (-p), force (-f), options (-o)
# ===========================================================================

def test_populate_flag_creates_flow_dir_only(bake, project):
    """-p populates the flow skeleton without executing the flow: flow/ exists
    afterwards, work/ does not."""
    project("sample")
    assert not bake.run(["sample_target", "impl", "-p"])
    assert Path("flow/sample_target/impl").is_dir()
    assert not Path("work/sample_target/impl/output").exists()


def test_run_uses_the_flow_itself_without_copy(bake, capfd, project):
    """Without -p, a step runs its flow from the flow's own directory and
    copies nothing into flow/."""
    project("sample")
    assert not bake.run(["sample_target", "vrf"])
    assert not Path("flow").exists()
    assert_in_stderr(capfd, "Flow: 'dummy_vrf' from")
    assert "sample_tb.v" in vrf_run_sh()


def test_populate_last_step_of_longer_recipe(bake, project):
    """impl-vrf -p copies the flow of the gate-level vrf only; impl keeps
    running its flow itself."""
    project("sample")
    assert not bake.run(["sample_target", "impl-vrf", "-p"])
    assert Path("flow/sample_target/impl-vrf/sample_test/run.sh.tpl").is_file()
    assert not Path("flow/sample_target/impl").exists()


def test_populated_copy_is_used_and_recorded(bake, capfd, project):
    """-p writes the copy and its record; the step runs the copy from then on."""
    project("sample")
    assert not bake.run(["sample_target", "vrf", "-p"])
    copy_dir = Path("flow/sample_target/vrf/sample_test")
    record = json.loads((copy_dir / ".bake_flow.json").read_text())
    assert record["flow"] == "dummy_vrf" and record["git"] is None and len(record["digest"]) == 64
    script = copy_dir / "run.sh.tpl"
    script.write_text(script.read_text() + "echo CUSTOMISED\n")
    assert not bake.run(["sample_target", "vrf"])
    assert_in_stderr(capfd, "Flow: the block's copy in")
    assert "CUSTOMISED" in vrf_run_sh()
    assert not Path("work/sample_target/vrf/sample_test/.bake_flow.json").exists()


def test_populated_copy_outdated_warning(bake, capfd, project):
    """A change to the flow after -p is reported at every run, with what to
    do: delete an untouched copy, merge into an edited one and record it
    with -p, after which the warning stops."""
    project("sample")
    assert not bake.run(["sample_target", "vrf", "-p"])
    flow_script = Path("../flows/vrf/run.sh.tpl")
    flow_script.write_text(flow_script.read_text() + "echo FLOW_FIX\n")
    capfd.readouterr()
    assert not bake.run(["sample_target", "vrf"])
    assert_stderr(capfd, expect=["has changed since its copy", "never modified: delete it"])
    copy_script = Path("flow/sample_target/vrf/sample_test/run.sh.tpl")
    copy_script.write_text(copy_script.read_text() + "echo CUSTOMISED\n")
    assert not bake.run(["sample_target", "vrf"])
    assert_stderr(capfd, expect=["Merge the changes into the copy", "bake sample_target vrf -t sample_test -p"])
    assert not bake.run(["sample_target", "vrf", "-p"])
    assert_in_stderr(capfd, "is left as it is, and recorded")
    assert "CUSTOMISED" in copy_script.read_text()
    assert not bake.run(["sample_target", "vrf"])
    assert_not_in_stderr(capfd, "has changed since")


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_populated_copy_records_git_commit(bake, capfd, project, tmp_run_dir):
    """In a git repository the record keeps the flow's commit and whether it
    was clean, and the warning shows how to see what changed since."""
    import subprocess

    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=tmp_run_dir, check=True, capture_output=True)

    project("sample")
    git("init", "-q")
    git("add", "test/projects/flows")
    git("commit", "-qm", "flows")
    assert not bake.run(["sample_target", "vrf", "-p"])
    record = json.loads(Path("flow/sample_target/vrf/sample_test/.bake_flow.json").read_text())
    assert record["git"]["path"] == "test/projects/flows/vrf" and record["git"]["dirty"] is False
    assert record["git"]["repo"] is None
    flow_script = Path("../flows/vrf/run.sh.tpl")
    flow_script.write_text(flow_script.read_text() + "echo FLOW_FIX\n")
    assert not bake.run(["sample_target", "vrf"])
    assert_stderr(capfd, expect=[f"(commit {record['git']['commit'][:12]})",
                                 f"diff {record['git']['commit'][:12]} -- test/projects/flows/vrf"])


def test_copy_without_record_and_switched_flow(bake, capfd, project):
    """A copy from an older bake has no record: the run says changes cannot be
    detected, and -p records it. A copy of another flow than the step's is
    reported."""
    project("sample")
    shutil.copytree("../flows/vrf", "flow/sample_target/vrf/sample_test")
    assert not bake.run(["sample_target", "vrf"])
    assert_in_stderr(capfd, "no populate record")
    assert not bake.run(["sample_target", "vrf", "-p"])
    assert Path("flow/sample_target/vrf/sample_test/.bake_flow.json").is_file()
    assert bake.run(["sample_target", "vrf", "-o", "vrf.flow=failing_vrf"])
    assert_in_stderr(capfd, "was populated from flow 'dummy_vrf', but vrf now uses flow 'failing_vrf'")


def test_populate_excludes_other_modes(bake, capfd, project):
    """-p only copies a flow: combined with -n, -i, -f, -c or -r it is a usage error."""
    project("sample")
    for flag in ("-n", "-i", "-f", "-c", "-r"):
        assert bake.run(["sample_target", "vrf", "-p", flag]) == 2
    assert not Path("flow").exists()


def test_force_flag_reruns_up_to_date_step(bake, capfd, project):
    project("sample")
    assert not bake.run(["sample_target", "impl"])
    assert not bake.run(["sample_target", "impl", "-v"])
    assert_in_stderr(capfd, "up-to-date")
    assert not bake.run(["sample_target", "impl", "-f", "-v"])
    assert_not_in_stderr(capfd, "up-to-date")


def test_option_malformed_errors(bake, capfd, project):
    """-o without section.attribute=value is a clean error, not a traceback."""
    project("sample")
    assert bake.run(["sample_target", "vrf", "-o", "nodothere"]) == 1
    assert_stderr(capfd, expect=["Malformed option", "nodothere"], expect_not=["Traceback"])
    assert not Path("work").exists()


def test_option_unknown_section_errors(bake, capfd, project):
    project("sample")
    assert bake.run(["sample_target", "vrf", "-o", "vrv.simulator=stub"]) == 1
    assert_stderr(capfd, expect=["unknown config section", "vrv"], expect_not=["Traceback"])


def test_option_unknown_attribute_errors(bake, capfd, project):
    project("sample")
    assert bake.run(["sample_target", "vrf", "-o", "vrf.simulatr=stub"]) == 1
    # The known attributes are listed with the error.
    assert_stderr(capfd, expect=["config.vrf has no attribute", "simulatr", "simulator"],
                  expect_not=["Traceback"])


def test_option_string_and_bool_applied(bake, project):
    """-o sets a string attribute and converts to bool where the attribute is one."""
    project("sample")
    assert not bake.run(["sample_target", "vrf", "-o", "vrf.simulator=stub", "-o", "bake.interactive=true"])
    assert "SIM=stub INTERACTIVE=1" in vrf_run_sh()


def test_option_bad_bool_errors(bake, capfd, project):
    project("sample")
    assert bake.run(["sample_target", "vrf", "-o", "bake.interactive=maybe"]) == 1
    assert_in_stderr(capfd, "Expected a boolean")


def test_option_list_appends(bake, project):
    """-o on a list attribute appends to it."""
    project("sample")
    assert not bake.run(["sample_target", "vrf", "-o", "vrf.options=-a", "-o", "vrf.options=-b"])
    from bake.context import context
    assert context.config.vrf.options == ["-a", "-b"]


def test_vrf_delays_is_a_scalar(bake, project):
    """config.vrf.delays names one corner and reaches the template as given."""
    project("sample")
    assert not bake.run(["sample_target", "vrf"])
    assert "DELAY=typ" in vrf_run_sh()
    assert not bake.run(["sample_target", "vrf", "-o", "vrf.delays=min"])
    assert "DELAY=min" in vrf_run_sh()


def test_flow_option_defaults(bake, project):
    """A flow's tpl_defaults expand to $BAKE_FLOW_OPT_*, dict options to one
    variable per key."""
    project("sample")
    assert not bake.run(["sample_target", "vrf"])
    assert "SPEED=slow TIE_HI= TIE_LO='" in vrf_run_sh()


def test_flow_option_overrides(bake, project):
    """config.<step>.flow_options overrides the defaults; a partial dict keeps
    the other keys' defaults and a tuple value is space-joined."""
    project("flow_options")
    assert not bake.run(["sample_target", "vrf"])
    assert "SPEED=fast TIE_HI=conb_1 HI TIE_LO='" in vrf_run_sh()


# ===========================================================================
# Tests — test selection
# ===========================================================================

def test_multiple_tests_require_explicit_t(bake, capfd, project):
    project("two_tests")
    assert bake.run(["dut", "vrf"])
    assert_in_stderr(capfd, "Use -t")


def test_wrong_test_name_errors(bake, capfd, project):
    project("two_tests")
    assert bake.run(["dut", "vrf", "-t", "nonexistent_test"])
    assert_in_stderr(capfd, "No such test")


def test_vrf_no_tests_defined_errors(bake, capfd, project):
    project("no_tests")
    assert bake.run(["notested", "vrf"])
    assert_in_stderr(capfd, "has no tests")


def test_unknown_step_in_recipe_errors(bake, capfd, project):
    project("sample")
    assert bake.run(["sample_target", "vrf-bogus"])
    assert_in_stderr(capfd, "bogus")


# ===========================================================================
# Tests — environments, templates, output directory
# ===========================================================================

def test_env_three_level_inheritance(bake, project):
    """Files from a three-level env chain (env -> env -> test) all reach the vrf step."""
    project("env_chain")
    assert not bake.run(["dut", "vrf"])
    run_sh = vrf_run_sh("dut", "leaf_test")
    assert "base.v" in run_sh and "mid.v" in run_sh and "leaf.v" in run_sh


def test_test_inherits_target_from_env(bake, capfd, project):
    """A test that includes an env with a target is listed under that block
    and runnable without naming the target itself."""
    project("env_target_inherit")
    assert not bake.run()
    assert_in_stderr(capfd, "    - leaf_test")
    assert not bake.run(["dut", "vrf"])
    assert Path("work/dut/vrf/leaf_test").is_dir()


def test_vrf_runtime_options_reach_flow(bake, project):
    """vrf_runtime_options merge from the env and the test, config.vrf.runtime_options
    follow; the shared build directory sits next to the tests' work directories."""
    project("runtime_options")
    assert not bake.run(["dut", "vrf", "-t", "plus_test", "-o", "vrf.runtime_options=+FROM_CLI=3"])
    run_sh = vrf_run_sh("dut", "plus_test")
    assert "RUNTIME=+FROM_ENV=1 +FROM_TEST=2 +FROM_CLI=3 " in run_sh
    assert f"BUILD_DIR={Path('work/dut/vrf/_build').resolve()}" in run_sh
    vars_json = json.loads(Path("work/dut/vrf/plus_test/bake_vars.json").read_text())
    assert vars_json["BAKE_SIM_OPTIONS"] == ["-build_opt"]


def test_vrf_runtime_options_unknown_simulator_errors(bake, capfd, project):
    project("runtime_options")
    assert bake.run(["dut", "vrf", "-t", "bad_sim_test"]) == 1
    assert_in_stderr(capfd, "Simulator 'nosim' (in vrf_runtime_options)")


def test_vrf_test_named_like_build_dir_errors(bake, capfd, project):
    project("runtime_options")
    assert bake.run(["dut", "vrf", "-t", "_build"]) == 1
    assert_in_stderr(capfd, "the name is reserved")


def test_vrf_clean_removes_shared_builds(bake, project):
    """-c on a test removes its work directory and the builds shared by the
    block's tests, so -r rebuilds from scratch."""
    project("runtime_options")
    assert not bake.run(["dut", "vrf", "-t", "plus_test"])
    Path("work/dut/vrf/_build/abc").mkdir(parents=True)
    assert not bake.run(["dut", "vrf", "-t", "plus_test", "-c"])
    assert not Path("work/dut/vrf/plus_test").exists()
    assert not Path("work/dut/vrf/_build").exists()


def test_tpl_custom_variable_expanded(bake, project):
    """A config.bake.tpl_dict variable is substituted into .tpl files."""
    project("tpl_var")
    assert not bake.run(["dut", "impl"])
    run_sh = Path("work/dut/impl/run.sh").read_text()
    assert "hello_bake" in run_sh and "${BAKE_CUSTOM_VAR}" not in run_sh


def test_bake_vars_json_keeps_lists(bake, project):
    """Every run writes the template variables to bake_vars.json, lists kept
    as lists, and hands the flow its path in $BAKE_VARS; a path with a space
    is one entry there, while the template variable is space-joined."""
    import json
    project("spaces")
    assert not bake.run(["sample_target", "impl"])
    work = Path("work/sample_target/impl")
    v = json.loads((work / "bake_vars.json").read_text())
    assert v["BAKE_TOP"] == "sample"
    assert [Path(f).name for f in v["BAKE_DESIGN_VERILOG_FILES"]] == ["sample.v", "base.v"]
    assert " " in v["BAKE_DESIGN_VERILOG_FILES"][0]
    files = (work / "output/files.txt").read_text().splitlines()
    assert files == v["BAKE_DESIGN_VERILOG_FILES"]


def test_tpl_undefined_variable_in_flow_errors(bake, capfd, project):
    """A .tpl file referencing an undefined $BAKE_ variable surfaces as an error."""
    project("tpl_undefined")
    assert bake.run(["m", "impl"])
    assert_in_stderr(capfd, "undefined")


def test_output_dir_override(bake, project):
    """config.bake.output_dir redirects step work output to a custom path."""
    project("output_dir")
    assert not bake.run(["sample_target", "impl"])
    assert Path("custom_out/sample_target/impl/output/sample.v").exists()
    assert not Path("work/sample_target/impl").exists()


# ===========================================================================
# Tests — StepData and Recipe (unit)
# ===========================================================================

def test_step_data_copy_is_independent():
    """copy() gives lists and dicts (and lists inside dicts) of their own,
    and copies the data nested in a list (macros)."""
    from bake.step import LibData, RecipePath, RtlData
    data = LibData(vrf_defines=["A"], liberty_files={"TT": ["a.lib"]}, sdf_files={"default": "x.sdf"},
                   recipe_prefix=RecipePath(["tmr"]))
    other = data.copy()
    other.vrf_defines.append("B")
    other.liberty_files["TT"].append("b.lib")
    other.recipe_prefix.append("impl")
    assert data.vrf_defines == ["A"]
    assert data.liberty_files == {"TT": ["a.lib"]}
    assert str(data.recipe_prefix) == "tmr"
    assert other.sdf_files == {"default": "x.sdf"}
    assert type(other) is LibData

    rtl = RtlData(macros=[LibData(netlist_files=["m.v"])])
    rtl.copy().macros[0].netlist_files.append("n.v")
    assert rtl.macros[0].netlist_files == ["m.v"]


def test_step_data_convert_keeps_base_fields():
    """convert() carries identity, test state and bookkeeping to the new kind,
    as copies, and sets the fields it is given."""
    from bake.step import LibData, RecipePath, RtlData
    rtl = RtlData(block="b", top="t", rtl_files=["a.v"], vrf_defines=["SIM"], recipe_prefix=RecipePath(["tmr"]))
    lib = rtl.convert(LibData, netlist_files=["t.v"])
    assert type(lib) is LibData
    assert (lib.block, lib.top, lib.netlist_files, str(lib.recipe_prefix)) == ("b", "t", ["t.v"], "tmr")
    lib.vrf_defines.append("NETLIST")
    assert rtl.vrf_defines == ["SIM"]


def test_step_output_data_does_not_alter_input():
    """A step appending to its output_data leaves its own data untouched, and
    reading output_data twice does not duplicate the addition."""
    from bake.step import Step, StepData

    class Appender(Step):
        name = ""   # not registered
        source_files = []
        output_files = []

        @property
        def output_data(self):
            data = super().output_data
            data.vrf_defines.append("NETLIST")
            return data

    s = Appender(StepData(vrf_defines=["SIM"]))
    assert s.output_data.vrf_defines == ["SIM", "NETLIST"]
    assert s.output_data.vrf_defines == ["SIM", "NETLIST"]
    assert s.data.vrf_defines == ["SIM"]


def test_step_data_isolated_from_manifest(bake, project):
    """Working state is a copy: mutating it never reaches the registered BlockSpec."""
    from bake.context import context
    from bake.step import StepData
    project("sample")
    assert not bake.run([])
    block = context.blocks["sample_target"]
    data = StepData.create(block=block)
    assert data.block == "sample_target" and data.block_dir == block.dir
    data.rtl_files.append("extra.v")
    data.top = "changed"
    assert block.rtl_files == [str(Path("../rtl/sample.v").resolve())]
    assert block.top == "sample"


def test_step_data_extend_list_deduplication():
    """extend() merges rtl_files with parent-first ordering and no duplicates."""
    from bake.step import RtlData
    parent = RtlData(rtl_files=["a.v", "b.v"])
    child  = RtlData(rtl_files=["b.v", "c.v"])
    child.extend(parent)
    assert child.rtl_files == ["a.v", "b.v", "c.v"]


def test_step_data_extend_dict_inheritance():
    """extend() inherits parent dict keys absent in child (vrf_options)."""
    from bake.step import StepData
    parent = StepData(vrf_options={"xcelium": ["-64bit"], "icarus": ["-g2012"]})
    child  = StepData(vrf_options={"icarus": ["-Wall"]})
    child.extend(parent)
    assert child.vrf_options["xcelium"] == ["-64bit"]
    assert "-Wall" in child.vrf_options["icarus"]


def test_step_data_extend_scalar_dict_values():
    """dict fields may hold scalars (vrf_options); the child's value wins when set."""
    from bake.step import StepData
    parent = StepData(vrf_options={"icarus": "-g2012", "vcs": "-full64"})
    child  = StepData(vrf_options={"icarus": "-g2005"})
    child.extend(parent)
    assert child.vrf_options == {"icarus": "-g2005", "vcs": "-full64"}


def test_step_data_extend_lib_into_rtl_is_a_macro():
    """An implemented block included into RTL is kept whole as a macro, and
    brings its cell libraries; RTL cannot be included into a hard block."""
    from bake.step import LibData, RtlData
    parent = RtlData(block="top", rtl_files=["top.v"], libs=["cells_a"])
    sub = LibData(block="sub", netlist_files=["sub.v"], layout_info="sub.lef", libs=["cells_b"])
    parent.extend(sub)
    parent.extend(sub)
    assert parent.macros == [sub] and parent.rtl_files == ["top.v"]
    assert parent.libs == ["cells_b", "cells_a"]
    with pytest.raises(BakeManifestError, match="cannot include"):
        sub.extend(parent)


def test_recipe_objects_are_not_shared():
    """Constructing the same block/recipe twice gives independent objects."""
    from bake.step import Recipe
    a, b = Recipe("x", "impl"), Recipe("x", "impl")
    assert a is not b
    assert a.key == b.key == ("x", "impl")


# ===========================================================================
# Tests — TemplateDictionary validation (unit)
# ===========================================================================

def test_bake_template_leaves_other_dollars_alone():
    """Only $BAKE_* is a placeholder: shell/Tcl variables need no escaping,
    $$ still collapses, and an unknown $BAKE_ name is an error."""
    from bake.step import BakeTemplate
    tpl = BakeTemplate("read_lef $lef ${x} $$y $1 $BAKE_TOP ${BAKE_TOP}_x $bake_top ${BAKE_TOP")
    assert tpl.substitute({"BAKE_TOP": "cnt"}) == "read_lef $lef ${x} $y $1 cnt cnt_x $bake_top ${BAKE_TOP"
    with pytest.raises(KeyError):
        BakeTemplate("$BAKE_NOPE").substitute({"BAKE_TOP": "cnt"})


def test_template_dict_prefix_enforced():
    from bake.context import TemplateDictionary
    d = TemplateDictionary()
    with pytest.raises(BakeConfigError, match="BAKE_"):
        d["NO_PREFIX"] = "value"


def test_template_dict_uppercase_enforced():
    from bake.context import TemplateDictionary
    d = TemplateDictionary()
    with pytest.raises(BakeConfigError):
        d["BAKE_lower_case"] = "value"


def test_template_dict_no_overwrite():
    from bake.context import TemplateDictionary
    d = TemplateDictionary()
    d["BAKE_KEY"] = "first"
    with pytest.raises(BakeConfigError):
        d["BAKE_KEY"] = "second"


# ===========================================================================
# Tests — the reference PDK manifest and the impl flow on sky130
# ===========================================================================

def test_sky130_manifest_requires_pdk_root(bake, capfd, project, monkeypatch):
    """Without PDK_ROOT the reference PDK manifest fails to load with a clear message."""
    monkeypatch.delenv("PDK_ROOT", raising=False)
    project("sky130")
    assert bake.run(["-l"])
    assert_in_stderr(capfd, "PDK_ROOT is not set")


@sky130_required
def test_sky130_libs_listed(bake, capfd, project):
    """Loading the reference PDK manifest registers the sky130 libraries."""
    project("sky130")
    assert not bake.run(["-l"])
    assert_in_stderr(capfd, "sky130_fd_sc_hd")


@sky130_required
def test_sky130_impl_populate(bake, project):
    """impl populates its flow dir using a library the PDK manifest registered;
    yosys-openroad is the default flow, so no config.impl.flow is needed."""
    project("sky130")
    assert not bake.run(["counter", "impl", "-p"])
    assert Path("flow/counter/impl").is_dir()


@sky130_required
@openroad_required
def test_sky130_impl_run(bake, capfd, project):
    """Full impl run on sky130: synthesis, floorplan, CTS on the constrained
    clock, routing without violations, a netlist of sky130 cells and an SDF
    per corner."""
    project("sky130")
    assert not bake.run(["counter", "impl"])
    assert_stderr(capfd, expect=["TritonCTS found 1 clock nets", "Number of violations = 0"],
                  expect_not=["WARNING: no clock defined"])
    netlist = Path("work/counter/impl/output/counter.v").read_text()
    assert "sky130_fd_sc_hd__" in netlist
    assert "$_" not in netlist                      # nothing left unmapped
    for corner in ("", "_TT", "_FF", "_SS"):
        assert "IOPATH" in Path(f"work/counter/impl/output/counter{corner}.sdf").read_text()
    assert Path("work/counter/impl/output/counter.def").is_file()


@sky130_required
@openroad_required
@iverilog_required
def test_sky130_impl_vrf(bake, capfd, project):
    """impl-vrf simulates the implemented netlist with the sky130 cell models
    and the SDF from impl annotated; the counter testbench passes."""
    project("sky130")
    assert not bake.run(["counter", "impl-vrf"])
    assert_stderr(capfd, expect=["Test finished."],
                  expect_not=["Expected:",                  # no $error from the testbench
                              "Omitting $sdf_annotate"])    # -gspecify was passed
    assert Path("work/counter/impl-vrf/counter_test/counter.sdf").is_symlink()


@sky130_required
@openroad_required
@iverilog_required
def test_sky130_hierarchical_impl(bake, capfd, project):
    """example/05 as shipped: the adder is implemented on demand, the accumulator
    is implemented with it as a hard macro, and both netlists simulate."""
    os.chdir(project("sky130").parents[2] / "example" / "05_hierarchical")
    assert not bake.run(["accumulator_hard", "impl-vrf"])
    out = stderr(capfd)
    assert "Running impl on block adder (dependency of accumulator_hard)" in out
    assert "Test finished." in out and "Expected:" not in out
    for f in ("adder.lef", "adder_TT.lib", "adder_FF.lib", "adder_SS.lib"):
        assert Path(f"work/adder/impl/output/{f}").is_file()
    assert "- u_adder adder + FIXED" in Path("work/accumulator_hard/impl/output/accumulator.def").read_text()
    assert Path("work/accumulator_hard/impl/output/accumulator.lef").is_file()
