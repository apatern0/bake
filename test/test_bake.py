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

import os
import shutil
import time
from pathlib import Path

import pytest

from conftest import stderr
from bake.exceptions import BakeConfigError

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
    assert_in_stderr(capfd, "rtl_file")


def test_duplicate_block_raises(bake, capfd, project):
    """Registering two blocks with the same name raises a manifest error."""
    project("duplicate_block")
    assert bake.run([])
    assert_in_stderr(capfd, "Redefinition")


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

def test_steps_all_four_always_listed(bake, capfd, project):
    """All four builtin steps always appear in the step listing."""
    project("flows_only")
    assert not bake.run()
    assert_stderr(capfd, expect=["vrf", "impl", "tmr", "dummy"])


def test_blocks_listed(bake, capfd, project):
    """Blocks registered with block() appear in the listing."""
    project("sample")
    assert not bake.run()
    assert_in_stderr(capfd, "sample_target")


def test_target_alias_works(bake, capfd, project):
    """The target() function (backward-compat alias for block()) still works."""
    project("target_alias")
    assert not bake.run()
    assert_in_stderr(capfd, "my_block")


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
    """Editing the block's copy of a flow script re-runs the step."""
    project("incremental")
    assert not bake.run(["sample_target", "gen"])
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


def test_populate_includes_dependency(bake, project):
    """-p populates the flow directories of dependencies too, and runs nothing."""
    project("hier")
    assert not bake.run(["top2", "vrf", "-p"])
    assert Path("flow/block/impl").is_dir()
    assert Path("flow/top2/vrf/top2_test").is_dir()
    assert not Path("work").exists()


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


def test_tpl_custom_variable_expanded(bake, project):
    """A config.bake.tpl_dict variable is substituted into .tpl files."""
    project("tpl_var")
    assert not bake.run(["dut", "impl"])
    run_sh = Path("work/dut/impl/run.sh").read_text()
    assert "hello_bake" in run_sh and "${BAKE_CUSTOM_VAR}" not in run_sh


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
    """copy() gives lists and dicts (and lists inside dicts) of their own."""
    from bake.step import StepData, RecipePath
    data = StepData(vrf_defines=["A"], liberty_files={"TT": ["a.lib"]}, sdf_files={"default": "x.sdf"},
                    recipe_prefix=RecipePath(["tmr"]))
    other = data.copy()
    other.vrf_defines.append("B")
    other.liberty_files["TT"].append("b.lib")
    other.recipe_prefix.append("impl")
    assert data.vrf_defines == ["A"]
    assert data.liberty_files == {"TT": ["a.lib"]}
    assert str(data.recipe_prefix) == "tmr"
    assert other.sdf_files == {"default": "x.sdf"}


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
    from bake.step import StepData
    parent = StepData(rtl_files=["a.v", "b.v"])
    child  = StepData(rtl_files=["b.v", "c.v"])
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
    """dict fields may hold scalars (sdf_files); the child's value wins when set."""
    from bake.step import StepData
    parent = StepData(sdf_files={"default": "parent.sdf", "fast": "p_fast.sdf"})
    child  = StepData(sdf_files={"default": "child.sdf"})
    child.extend(parent)
    assert child.sdf_files == {"default": "child.sdf", "fast": "p_fast.sdf"}


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
