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

import os
import shutil
from pathlib import Path
import pytest

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

# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def tmp_run_dir(monkeypatch, tmp_path):
    """Run each test in an isolated temporary directory."""
    monkeypatch.chdir(tmp_path)


class Bake:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch

    def run(self, arg_list=None):
        """Execute bake main; assert it calls sys.exit() and return the exit code."""
        arg_list = arg_list or []
        self._monkeypatch.setattr("sys.argv", ["bake"] + arg_list)

        from bake.cli import main as bake_main
        with pytest.raises(SystemExit) as retval:
            bake_main()
        return retval.value.code


@pytest.fixture
def bake(monkeypatch):
    yield Bake(monkeypatch)


# ---------------------------------------------------------------------------
# Flow fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dummy_flows(tmp_run_dir):
    """Minimal impl and vrf flows backed by simple shell scripts."""
    flow_dir = Path("dummy_flows")
    flow_dir.mkdir()

    with open(flow_dir / "manifest", "w") as f:
        f.write(
            """
import os
from bake import flow, lib

_base = os.path.dirname(os.path.abspath(__file__))

flow(
    name="dummy_impl",
    corners=[("TC", "Typical Case")],
    run_cmd="run.sh",
    dir=os.path.join(_base, "impl"),
)

# The impl step needs a library to hand to the flow; supply a stub one so the
# tests do not depend on a PDK being present in the environment.
lib(name="dummy_lib", liberty_files={"TC": [os.path.join(_base, "dummy_lib_tc.lib")]})
config.impl.default_libs.append("dummy_lib")

flow(
    name="dummy_vrf",
    simulators=[("stub", "Sample Simulator")],
    simulation_frameworks=[],
    run_cmd="run.sh",
    dir=os.path.join(_base, "vrf"),
)
            """
        )

    (flow_dir / "dummy_lib_tc.lib").write_text("library (dummy_lib_tc) {}\n")

    (flow_dir / "impl").mkdir()
    with open(flow_dir / "impl" / "run.sh.tpl", "w") as f:
        f.write(
            """
#!/bin/bash
mkdir output
touch output/${BAKE_TOP}.v
touch output/${BAKE_TOP}.sdf
touch output/${BAKE_TOP}_tc.lib
            """
        )
    (flow_dir / "impl" / "run.sh.tpl").chmod(0o744)

    (flow_dir / "vrf").mkdir()
    with open(flow_dir / "vrf" / "run.sh.tpl", "w") as f:
        f.write("#!/bin/bash\n")
    (flow_dir / "vrf" / "run.sh.tpl").chmod(0o744)


@pytest.fixture
def patch_dummy_flows_nonzero_vrf():
    flow_dir = Path("dummy_flows")
    with open(flow_dir / "vrf" / "run.sh.tpl", "w") as f:
        f.write("#!/bin/bash\nexit 1\n")
    (flow_dir / "vrf" / "run.sh.tpl").chmod(0o744)


# ---------------------------------------------------------------------------
# Custom step fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def custom_step_dir(tmp_run_dir):
    """A directory containing a custom 'check' step loadable via load()."""
    step_dir = Path("custom_step_dir")
    step_dir.mkdir()
    flow_dir = step_dir / "flow"
    flow_dir.mkdir()

    with open(flow_dir / "run.sh.tpl", "w") as f:
        f.write("#!/bin/bash\nmkdir -p output\ntouch output/check_result.txt\n")
    (flow_dir / "run.sh.tpl").chmod(0o744)

    with open(step_dir / "manifest", "w") as f:
        f.write(
            """
import os
from bake.step import Step
from bake.manifest import FlowSpec


class CheckConfig:
    def __init__(self):
        self.flow = ""
        self.flow_options = {}


config.register('check', CheckConfig())


class CheckStep(Step):
    name = "check"
    default_flow = "check_flow"

    @property
    def source_files(self):
        return list(self.data.rtl_files)

    @property
    def output_files(self):
        return [os.path.join(self.outputdir, "check_result.txt")]


FlowSpec(name="check_flow", run_cmd="run.sh")
            """
        )


# ---------------------------------------------------------------------------
# Design fixtures
# ---------------------------------------------------------------------------

SAMPLE_V = """
`timescale 1ns/1ps
module sample();
endmodule
"""

SAMPLE_TB_V = """
`timescale 1ns/1ps
module sample_tb();
    sample sample();
endmodule
"""


@pytest.fixture
def sample_target(tmp_run_dir, dummy_flows):
    """Two blocks sharing a test environment; impl and vrf flows configured."""
    with open("manifest", "w") as f:
        f.write(
            """
from bake import load, block, test, env

load("dummy_flows")
config.impl.flow = "dummy_impl"
config.vrf.flow = "dummy_vrf"

block(
    name="sample_target",
    top="sample",
    rtl_files=["sample.v"],
)

block(
    name="sample_target_2",
    top="sample",
    rtl_files=["sample.v"],
)

env(
    name="sample_test_env",
    vrf_files=["sample_tb.v"],
    default_sim="stub"
)

test(
    name="sample_test",
    target="sample_target",
    includes=["sample_test_env"]
)

test(
    name="sample_test",
    target="sample_target_2",
    includes=["sample_test_env"]
)
            """
        )
    with open("sample.v", "w") as f:
        f.write(SAMPLE_V)
    with open("sample_tb.v", "w") as f:
        f.write(SAMPLE_TB_V)


@pytest.fixture
def sample_with_check_step(tmp_run_dir, dummy_flows, custom_step_dir):
    """Single block with the custom check step and dummy vrf/impl flows."""
    with open("manifest", "w") as f:
        f.write(
            """
from bake import load, block, test, env

load("dummy_flows")
load("custom_step_dir")
config.impl.flow = "dummy_impl"
config.vrf.flow = "dummy_vrf"

block(
    name="sample_target",
    top="sample",
    rtl_files=["sample.v"],
)

env(
    name="sample_test_env",
    vrf_files=["sample_tb.v"],
    default_sim="stub"
)

test(
    name="sample_test",
    target="sample_target",
    includes=["sample_test_env"]
)
            """
        )
    with open("sample.v", "w") as f:
        f.write(SAMPLE_V)
    with open("sample_tb.v", "w") as f:
        f.write(SAMPLE_TB_V)


# ---------------------------------------------------------------------------
# Hierarchical design fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def hier_target_files(tmp_run_dir, dummy_flows):
    with open("block.v", "w") as f:
        f.write("`timescale 1ns/1ps\nmodule block();\nendmodule\n")
    with open("top.v", "w") as f:
        f.write("`timescale 1ns/1ps\nmodule top();\n    block block();\nendmodule\n")


@pytest.fixture
def hier_target_include_list(tmp_run_dir, hier_target_files, dummy_flows):
    """Include targets as a list — coerced to dict{block: 'rtl'} by the validator."""
    with open("manifest", "w") as f:
        f.write(
            """
from bake import load, block

load("dummy_flows")
config.impl.flow = "dummy_impl"
config.vrf.flow = "dummy_vrf"

block(name="block", top="block", rtl_files=["block.v"])
block(name="top", top="top", includes=["block"], rtl_files=["top.v"])
            """
        )


@pytest.fixture
def hier_target_include_string(tmp_run_dir, hier_target_files, dummy_flows):
    """Type-confusion: include field is a bare string (should be rejected)."""
    with open("manifest", "w") as f:
        f.write(
            """
from bake import load, block

load("dummy_flows")
config.impl.flow = "dummy_impl"
config.vrf.flow = "dummy_vrf"

block(name="block", top="block", rtl_files=["block.v"])
block(name="top", top="top", includes="block", rtl_files=["top.v"])
            """
        )


@pytest.fixture
def hier_target_include_dict(tmp_run_dir, hier_target_files, dummy_flows):
    """Include using explicit dict syntax."""
    with open("manifest", "w") as f:
        f.write(
            """
from bake import load, block

load("dummy_flows")
config.impl.flow = "dummy_impl"
config.vrf.flow = "dummy_vrf"

block(name="block", top="block", rtl_files=["block.v"])
block(name="top", top="top", includes={"block": "rtl"}, rtl_files=["top.v"])
            """
        )


@pytest.fixture
def hier_target_include_dict_invalid(hier_target_include_dict):
    with open("manifest", "a") as f:
        f.write(
            """
block(
    name="top2",
    top="top",
    includes={"block": "invalid"},
    rtl_files=["top.v"],
)
            """
        )


@pytest.fixture
def hier_target_include_dict_impl(hier_target_include_dict):
    with open("manifest", "a") as f:
        f.write(
            """
block(
    name="top2",
    top="top",
    includes={"block": "impl"},
    rtl_files=["top.v"],
)
            """
        )


@pytest.fixture
def hier_target_include_dict_impl_skip(hier_target_include_dict):
    with open("manifest", "a") as f:
        f.write(
            """
block(
    name="top2",
    top="top",
    includes={"block": "impl"},
    rtl_files=["top.v"],
    skip_on_include_errors=True,
)
            """
        )


@pytest.fixture
def hier_target_include_dict_tmr_impl_skip(hier_target_include_dict):
    with open("manifest", "a") as f:
        f.write(
            """
block(
    name="top2",
    top="top",
    includes={"block": "tmr-impl"},
    rtl_files=["top.v"],
    skip_on_include_errors=True,
)
            """
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stderr(capfd):
    return str(capfd.readouterr())


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


# ===========================================================================
# Tests — basic CLI
# ===========================================================================

def test_no_manifest(bake, capfd):
    """Error and non-zero exit when no manifest is present."""
    assert bake.run()
    assert_in_stderr(capfd, "Manifest file not found")


def test_empty_manifest(bake, capfd):
    """Empty manifest is valid — no error."""
    Path("manifest").touch()
    assert not bake.run()
    assert_not_in_stderr(capfd, "Manifest file not found")


def test_manifest_filename(bake, capfd):
    """The -m flag finds a manifest in the given directory."""
    manifest_dir = Path("manifest_dir")
    manifest_dir.mkdir()
    (manifest_dir / "manifest").touch()
    assert not bake.run(["-m", "manifest_dir"])
    assert_not_in_stderr(capfd, "Could not open file")


def test_load_nonexist(bake, capfd):
    """Error when load()ing a non-existing path."""
    Path("manifest").write_text('from bake import load\nload("does_not_exist")\n')
    assert bake.run()
    assert_in_stderr(capfd, "does not exist")


# ===========================================================================
# Tests — step and target listing
# ===========================================================================

def test_steps_all_four_always_listed(bake, dummy_flows, capfd):
    """All four builtin steps always appear in the step listing.

    Step availability is not gated by flow configuration — all builtins have a
    default_flow, so they always appear in context.steps and are always logged.
    """
    Path("manifest").write_text('from bake import load\nload("dummy_flows")\n')
    assert not bake.run()
    assert_stderr(capfd, expect=["vrf", "impl", "tmr", "dummy"])


def test_block_api_targets_listed(bake, sample_target, capfd):
    """Blocks registered with block() appear in the target listing."""
    assert not bake.run()
    assert_in_stderr(capfd, "sample_target")


def test_target_alias_works(bake, dummy_flows, capfd):
    """The target() function (backward-compat alias for block()) still works."""
    Path("my_block.v").write_text("`timescale 1ns/1ps\nmodule top();\nendmodule\n")
    Path("manifest").write_text(
        'from bake import load, target\nload("dummy_flows")\n'
        'target(name="my_block", top="top", rtl_files=["my_block.v"])\n'
    )
    assert not bake.run()
    assert_in_stderr(capfd, "my_block")


def test_custom_step_appears_in_listing(bake, sample_with_check_step, capfd):
    """A custom step loaded via load() in the manifest appears in step listing."""
    assert not bake.run()
    assert_in_stderr(capfd, "check")


def test_add_steps_dir_loads_py_files(bake, sample_target, capfd):
    """add_steps_dir() executes every .py file in the directory; a Step defined
    there is registered and usable in a recipe without a manifest file."""
    steps = Path("steps")
    steps.mkdir()
    flow = steps / "lint_flow"
    flow.mkdir()
    (flow / "run.sh.tpl").write_text("#!/bin/bash\nmkdir -p output\ntouch output/lint.log\n")
    (flow / "run.sh.tpl").chmod(0o744)
    (steps / "lint.py").write_text(
        """
from pathlib import Path
from bake.step import Step
from bake.manifest import FlowSpec

class LintConfig:
    def __init__(self):
        self.flow = ""
        self.flow_options = {}

config.register('lint', LintConfig())

class LintStep(Step):
    name = "lint"
    default_flow = "lint_flow"

    @property
    def source_files(self):
        return list(self.data.rtl_files)

    @property
    def output_files(self):
        return [str(self.outputdir / "lint.log")]

FlowSpec(name="lint_flow", run_cmd="run.sh", dir=str(Path(__file__).parent / "lint_flow"))
"""
    )
    with open("manifest", "a") as f:
        f.write('\nfrom bake import add_steps_dir\nadd_steps_dir("steps")\n')

    assert not bake.run()
    assert_in_stderr(capfd, "- lint")
    assert not bake.run(["sample_target", "lint-vrf"])
    assert Path("work/sample_target/lint/output/lint.log").is_file()


def test_test_inherits_target_from_env(bake, capfd, dummy_flows):
    """A test that includes an env with a target is listed under that block
    and runnable without naming the target itself."""
    with open("manifest", "w") as f:
        f.write(
            """
from bake import load, block, env, test
load("dummy_flows")
config.vrf.flow = "dummy_vrf"
block(name="dut", top="sample", rtl_files=["sample.v"])
env(name="base", target="dut", vrf_files=["sample_tb.v"], default_sim="stub")
env(name="mid", includes=["base"])
test(name="leaf_test", includes=["mid"])
"""
        )
    with open("sample.v", "w") as f:
        f.write(SAMPLE_V)
    with open("sample_tb.v", "w") as f:
        f.write(SAMPLE_TB_V)

    assert not bake.run()
    assert_in_stderr(capfd, "    - leaf_test")
    assert not bake.run(["dut", "vrf"])
    assert Path("work/dut/vrf/leaf_test").is_dir()


# ===========================================================================
# Tests — VRF step
# ===========================================================================

def test_sample_vrf(bake, capfd, sample_target):
    """Run vrf step on a valid sample target."""
    assert not bake.run(["sample_target", "vrf"])
    assert_not_in_stderr(capfd, "Error during bake operation: Non-zero return code")


def test_sample_legacy_target_step_rejected(bake, capfd, sample_target):
    """Old-style 'target-step' combined argument is rejected with a clear error."""
    assert bake.run(["sample_target-vrf"])
    assert_in_stderr(capfd, "Expected 'bake <block> <recipe>'")


def test_sample_vrf_nonzero_exitcode(bake, capfd, sample_target, patch_dummy_flows_nonzero_vrf):
    """Non-zero exit code from the flow script is surfaced as a bake error."""
    assert bake.run(["sample_target", "vrf"])
    assert_in_stderr(capfd, "Error during bake operation: Non-zero return code")


def test_sample_vrf_explicit_test(bake, sample_target):
    """VRF step works when the test is selected explicitly with -t."""
    assert not bake.run(["sample_target", "vrf", "-t", "sample_test"])


# ===========================================================================
# Tests — impl step
# ===========================================================================

def test_sample_impl(bake, sample_target):
    """Run impl step on a valid sample target."""
    assert not bake.run(["sample_target", "impl"])
    assert Path("work/sample_target/impl/output/sample.v").exists()


def test_sample_impl_vrf(bake, sample_target):
    """Run impl-vrf dependency chain."""
    assert not bake.run(["sample_target", "impl-vrf"])
    assert Path("work/sample_target/impl/output/sample.v").exists()


def test_impl_update_required(bake, capfd, sample_target):
    """Second impl run is skipped when outputs are newer than sources."""
    assert not bake.run(["sample_target", "impl"])
    assert Path("work/sample_target/impl/output/sample.v").exists()
    assert not bake.run(["sample_target", "impl", "-v"])
    assert_in_stderr(capfd, "up-to-date")


# ===========================================================================
# Tests — dummy step
# ===========================================================================

def test_sample_dummy(bake, sample_target):
    """Dummy step runs and exits 0; no output files to check."""
    assert not bake.run(["sample_target", "dummy"])


def test_sample_dummy_always_reruns(bake, capfd, sample_target):
    """Dummy step (output_files=[]) always re-executes; never skipped."""
    assert not bake.run(["sample_target", "dummy"])
    assert not bake.run(["sample_target", "dummy", "-v"])
    assert_not_in_stderr(capfd, "up-to-date")


def test_sample_dummy_vrf(bake, sample_target):
    """dummy-vrf: dummy passes state unchanged into vrf."""
    assert not bake.run(["sample_target", "dummy-vrf"])


def test_sample_impl_dummy(bake, sample_target):
    """impl-dummy: impl output flows through dummy; impl artifacts must exist."""
    assert not bake.run(["sample_target", "impl-dummy"])
    assert Path("work/sample_target/impl/output/sample.v").exists()


def test_sample_dummy_impl(bake, sample_target):
    """dummy-impl: dummy passes RTL data to impl unchanged.

    impl's recipe_path is 'dummy-impl', so its workdir is work/.../dummy-impl/.
    """
    assert not bake.run(["sample_target", "dummy-impl"])
    assert Path("work/sample_target/dummy-impl/output/sample.v").exists()


def test_sample_dummy_impl_vrf(bake, sample_target):
    """dummy-impl-vrf: all three steps execute in sequence."""
    assert not bake.run(["sample_target", "dummy-impl-vrf"])
    assert Path("work/sample_target/dummy-impl/output/sample.v").exists()


def test_sample_impl_dummy_vrf(bake, sample_target):
    """impl-dummy-vrf: impl output passes through dummy into vrf."""
    assert not bake.run(["sample_target", "impl-dummy-vrf"])
    assert Path("work/sample_target/impl/output/sample.v").exists()


# ===========================================================================
# Tests — TMR step (tmrg required)
# ===========================================================================

@tmrg_required
def test_sample_tmr(bake, sample_target):
    """Run tmr step on a valid sample target."""
    assert not bake.run(["sample_target", "tmr"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()


@tmrg_required
def test_sample_tmr_vrf(bake, sample_target):
    """Run tmr-vrf dependency chain."""
    assert not bake.run(["sample_target", "tmr-vrf"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()


@tmrg_required
def test_sample_tmr_impl(bake, sample_target):
    """Run tmr-impl dependency chain."""
    assert not bake.run(["sample_target", "tmr-impl"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()
    assert Path("work/sample_target/tmr-impl/output/sampleTMR.v").exists()


@tmrg_required
def test_sample_tmr_impl_vrf(bake, sample_target):
    """Run tmr-impl-vrf dependency chain."""
    assert not bake.run(["sample_target", "tmr-impl-vrf"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()
    assert Path("work/sample_target/tmr-impl/output/sampleTMR.v").exists()


@tmrg_required
def test_sample_tmr_dummy(bake, sample_target):
    """tmr-dummy: triplication output passes through dummy."""
    assert not bake.run(["sample_target", "tmr-dummy"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()


@tmrg_required
def test_sample_tmr_dummy_impl(bake, sample_target):
    """tmr-dummy-impl: full triplication → passthrough → synthesis chain."""
    assert not bake.run(["sample_target", "tmr-dummy-impl"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()
    assert Path("work/sample_target/tmr-dummy-impl/output/sampleTMR.v").exists()


# ===========================================================================
# Tests — incremental rebuild and clean
# ===========================================================================

@tmrg_required
def test_update_required(bake, sample_target):
    """tmr-impl is skipped on re-run when outputs are up-to-date."""
    assert not bake.run(["sample_target", "tmr-impl", "-v"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()
    assert Path("work/sample_target/tmr-impl/output/sampleTMR.v").exists()
    assert not bake.run(["sample_target", "tmr-impl"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()
    assert Path("work/sample_target/tmr-impl/output/sampleTMR.v").exists()


@tmrg_required
def test_tmr_clean(bake, sample_target):
    """Clean removes only the tmr workdir."""
    assert not bake.run(["sample_target", "tmr"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()
    assert not bake.run(["sample_target", "tmr", "-c"])
    assert not Path("work/sample_target/tmr/output/sampleTMR.v").exists()


@tmrg_required
def test_impl_clean(bake, sample_target):
    """Clean on tmr-impl removes only the tmr-impl workdir, leaving tmr intact."""
    assert not bake.run(["sample_target", "tmr-impl"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()
    assert Path("work/sample_target/tmr-impl/output/sampleTMR.v").exists()
    assert not bake.run(["sample_target", "tmr-impl", "-c"])
    assert Path("work/sample_target/tmr/output/sampleTMR.v").exists()
    assert not Path("work/sample_target/tmr-impl/output/sampleTMR.v").exists()


# ===========================================================================
# Tests — custom step
# ===========================================================================

def test_custom_step_basic(bake, sample_with_check_step):
    """Custom step runs and creates its declared output file."""
    assert not bake.run(["sample_target", "check"])
    assert Path("work/sample_target/check/output/check_result.txt").exists()


def test_custom_step_incremental(bake, capfd, sample_with_check_step):
    """Custom step is skipped on re-run when outputs are newer than sources."""
    assert not bake.run(["sample_target", "check"])
    assert not bake.run(["sample_target", "check", "-v"])
    assert_in_stderr(capfd, "up-to-date")


def test_custom_step_force_reruns(bake, capfd, sample_with_check_step):
    """Force flag (-f) causes re-execution even when outputs are up-to-date."""
    assert not bake.run(["sample_target", "check"])
    assert not bake.run(["sample_target", "check", "-f", "-v"])
    assert_not_in_stderr(capfd, "up-to-date")


def test_custom_step_clean(bake, sample_with_check_step):
    """Clean removes the custom step workdir."""
    assert not bake.run(["sample_target", "check"])
    assert Path("work/sample_target/check/output/check_result.txt").exists()
    assert not bake.run(["sample_target", "check", "-c"])
    assert not Path("work/sample_target/check").exists()


def test_custom_step_chain_with_vrf(bake, sample_with_check_step):
    """check-vrf: custom step followed by vrf; check output is produced."""
    assert not bake.run(["sample_target", "check-vrf"])
    assert Path("work/sample_target/check/output/check_result.txt").exists()


# ===========================================================================
# Tests — SkyWater PDK (sky130_required)
# ===========================================================================

@sky130_required
def test_sky130_libs_listed(bake, capfd):
    """sky130 standard-cell libraries are listed when PDK_ROOT holds the PDK."""
    Path("manifest").touch()
    assert not bake.run(["-l"])
    assert_in_stderr(capfd, "sky130_fd_sc_hd")


@sky130_required
def test_sky130_impl_available_without_config(bake, capfd, dummy_flows):
    """impl step is available without setting config.impl.flow when sky130 is present.

    The impl builtin manifest sets ImplStep.default_flow = 'sky130' when the
    PDK is found through PDK_ROOT, making the step available by default.
    """
    Path("manifest").write_text(
        'from bake import load, block\nload("dummy_flows")\n'
        'block(name="my_block", top="top", rtl_files=[])\n'
    )
    assert not bake.run()
    assert_in_stderr(capfd, "impl")


@sky130_required
def test_sky130_impl_populate(bake):
    """impl step populates flow dir without running synthesis (-p flag).

    Uses the sky130 default flow (no config.impl.flow needed).
    """
    Path("sample.v").write_text(SAMPLE_V)
    Path("manifest").write_text(
        'from bake import block\nblock(name="my_block", top="sample", rtl_files=["sample.v"])\n'
    )
    assert not bake.run(["my_block", "impl", "-p"])
    assert Path("flow/my_block/impl").is_dir()


@sky130_required
@openroad_required
def test_sky130_impl_run(bake):
    """Full impl run with the sky130 flow produces a netlist and SDF file."""
    Path("sample.v").write_text(SAMPLE_V)
    Path("manifest").write_text(
        'from bake import block\nblock(name="my_block", top="sample", rtl_files=["sample.v"])\n'
    )
    assert not bake.run(["my_block", "impl"])
    assert Path("work/my_block/impl/output/sample.v").exists()
    assert Path("work/my_block/impl/output/sample.sdf").exists()


# ===========================================================================
# Tests — hierarchical designs (includes)
# ===========================================================================

def test_include_list(bake, hier_target_include_list):
    """A list in the include field is coerced to a dict by the validator."""
    assert not bake.run([])


def test_include_string(bake, capfd, hier_target_include_string):
    """A bare string in the include field is correctly rejected."""
    assert bake.run([])
    assert_in_stderr(capfd, "Target includes must be dict.")


def test_include_dict(bake, hier_target_include_dict):
    """A dict in the include field is correctly parsed."""
    assert not bake.run([])


def test_include_dict_invalid(bake, capfd, hier_target_include_dict_invalid):
    """An invalid step name in the includes dict fails at parse time."""
    assert bake.run([])
    assert_in_stderr(capfd, "Unsupported step")


def test_include_dict_impl(bake, capfd, hier_target_include_dict_impl):
    """Requesting impl results from a dependency that hasn't been built yet fails."""
    assert bake.run([])
    assert_in_stderr(capfd, "Unable to create impl library")


def test_include_dict_impl_skip(bake, capfd, hier_target_include_dict_impl_skip):
    """skip_on_include_errors=True defers a missing impl dep until it is built."""
    assert not bake.run([])                          # parse — top2 deferred
    assert_in_stderr(capfd, "Skipping registration of block 'top2'")
    assert not bake.run(["block", "impl"])           # build the dep
    assert_in_stderr(capfd, "Skipping registration of block 'top2'")
    assert not bake.run([])                          # parse again — top2 now resolves
    assert_not_in_stderr(capfd, "Skipping registration of block 'top2'")


@tmrg_required
def test_include_dict_tmr_impl_skip(bake, capfd, hier_target_include_dict_tmr_impl_skip):
    """skip_on_include_errors=True works for a tmr-impl dependency chain."""
    assert not bake.run([])
    assert_in_stderr(capfd, "Skipping registration of block 'top2'")
    assert not bake.run(["block", "tmr-impl"])
    assert_in_stderr(capfd, "Skipping registration of block 'top2'")
    assert not bake.run([])
    assert_not_in_stderr(capfd, "Skipping registration of block 'top2'")


# ===========================================================================
# Tests — CLI flags: populate (-p), force (-f), option format (-o)
# ===========================================================================

def test_populate_flag_creates_flow_dir_only(bake, sample_target):
    """-p populates the flow skeleton directory without executing the flow.

    The flow/ directory must exist after -p, but the work/ output directory
    must not — it is only created when the flow script actually runs.
    """
    assert not bake.run(["sample_target", "impl", "-p"])
    assert Path("flow/sample_target/impl").is_dir()
    assert not Path("work/sample_target/impl/output").exists()


def test_force_flag_reruns_up_to_date_step(bake, capfd, sample_target):
    """-f causes re-execution even when outputs are newer than sources."""
    assert not bake.run(["sample_target", "impl"])
    assert Path("work/sample_target/impl/output/sample.v").exists()
    # Without -f: skipped.
    assert not bake.run(["sample_target", "impl", "-v"])
    assert_in_stderr(capfd, "up-to-date")
    # With -f: re-executed, "up-to-date" must not appear.
    assert not bake.run(["sample_target", "impl", "-f", "-v"])
    assert_not_in_stderr(capfd, "up-to-date")


def test_invalid_option_format_errors(monkeypatch, sample_target, capfd):
    """-o with no dot separator is rejected before any step runs."""
    monkeypatch.setattr("sys.argv", ["bake", "sample_target", "vrf", "-o", "nodothere"])
    from bake.cli import main as bake_main
    with pytest.raises(BaseException):
        bake_main()


# ===========================================================================
# Tests — test selection and error paths
# ===========================================================================

@pytest.fixture
def two_test_block(tmp_run_dir, dummy_flows):
    """A single block with two tests — requires explicit -t to disambiguate."""
    Path("dut.v").write_text("`timescale 1ns/1ps\nmodule dut();\nendmodule\n")
    Path("tb1.v").write_text("`timescale 1ns/1ps\nmodule tb1();\nendmodule\n")
    Path("tb2.v").write_text("`timescale 1ns/1ps\nmodule tb2();\nendmodule\n")
    Path("manifest").write_text(
        """
from bake import load, block, test

load("dummy_flows")
config.vrf.flow = "dummy_vrf"

block(name="dut", top="dut", rtl_files=["dut.v"])

test(name="test_a", target="dut", vrf_files=["tb1.v"], default_sim="stub")
test(name="test_b", target="dut", vrf_files=["tb2.v"], default_sim="stub")
        """
    )


def test_multiple_tests_require_explicit_t(bake, capfd, two_test_block):
    """Running vrf with no -t when the block has multiple tests is an error."""
    assert bake.run(["dut", "vrf"])
    assert_in_stderr(capfd, "Use -t")


def test_wrong_test_name_errors(bake, capfd, two_test_block):
    """-t with a name that does not exist for the block is an error."""
    assert bake.run(["dut", "vrf", "-t", "nonexistent_test"])
    assert_in_stderr(capfd, "No such test")


def test_vrf_no_tests_defined_errors(bake, capfd, dummy_flows):
    """Running vrf when no tests are defined for the block is an error."""
    Path("block.v").write_text("`timescale 1ns/1ps\nmodule block();\nendmodule\n")
    Path("manifest").write_text(
        """
from bake import load, block

load("dummy_flows")
config.vrf.flow = "dummy_vrf"

block(name="notested", top="block", rtl_files=["block.v"])
        """
    )
    assert bake.run(["notested", "vrf"])
    assert_in_stderr(capfd, "Use -t")


# ===========================================================================
# Tests — StepData (unit)
# ===========================================================================

def test_step_data_target_immutable():
    """StepData.target is read-only; writing it raises AttributeError."""
    from bake.step import StepData
    data = StepData()
    with pytest.raises(AttributeError, match="read-only"):
        data.target = object()


def test_step_data_test_immutable():
    """StepData.test is read-only; writing it raises AttributeError."""
    from bake.step import StepData
    data = StepData()
    with pytest.raises(AttributeError, match="read-only"):
        data.test = object()


def test_step_data_extend_list_deduplication():
    """extend() merges rtl_files with parent-first ordering and no duplicates."""
    from bake.step import StepData
    parent = StepData(rtl_files=["a.v", "b.v"])
    child  = StepData(rtl_files=["b.v", "c.v"])
    child.extend(parent)
    # Parent comes first; 'b.v' deduped; child unique files appended.
    assert child.rtl_files == ["a.v", "b.v", "c.v"]


def test_step_data_extend_dict_inheritance():
    """extend() inherits parent dict keys absent in child (vrf_options)."""
    from bake.step import StepData
    parent = StepData(vrf_options={"xcelium": ["-64bit"], "icarus": ["-g2012"]})
    child  = StepData(vrf_options={"icarus": ["-Wall"]})
    child.extend(parent)
    # Parent key 'xcelium' inherited; 'icarus' merged (parent first, then child).
    assert "xcelium" in child.vrf_options
    assert child.vrf_options["xcelium"] == ["-64bit"]
    assert "-Wall" in child.vrf_options["icarus"]


# ===========================================================================
# Tests — TemplateDictionary validation (unit)
# ===========================================================================

def test_template_dict_prefix_enforced():
    """Keys without the BAKE_ prefix are rejected."""
    from bake.context import TemplateDictionary
    d = TemplateDictionary()
    with pytest.raises(Exception, match="BAKE_"):
        d["NO_PREFIX"] = "value"


def test_template_dict_uppercase_enforced():
    """Keys with lowercase characters are rejected."""
    from bake.context import TemplateDictionary
    d = TemplateDictionary()
    with pytest.raises(Exception):
        d["BAKE_lower_case"] = "value"


def test_template_dict_no_overwrite():
    """Setting the same key twice is rejected."""
    from bake.context import TemplateDictionary
    d = TemplateDictionary()
    d["BAKE_KEY"] = "first"
    with pytest.raises(Exception):
        d["BAKE_KEY"] = "second"


# ===========================================================================
# Tests — manifest registration validation
# ===========================================================================

def test_duplicate_block_raises(bake, capfd, dummy_flows):
    """Registering two blocks with the same name raises a manifest error."""
    Path("block.v").write_text("`timescale 1ns/1ps\nmodule m();\nendmodule\n")
    Path("manifest").write_text(
        """
from bake import load, block

load("dummy_flows")
block(name="dup", top="m", rtl_files=["block.v"])
block(name="dup", top="m", rtl_files=["block.v"])
        """
    )
    assert bake.run([])
    assert_in_stderr(capfd, "Redefinition")


def test_block_without_rtl_files_not_listed(bake, capfd, dummy_flows):
    """A block without rtl_files is not shown in the runnable block listing.

    Blocks without rtl_files are valid as metadata-only aggregates (e.g. for
    use as library dependencies) but are omitted from the target listing because
    there is nothing to run them against.
    """
    Path("block.v").write_text("`timescale 1ns/1ps\nmodule m();\nendmodule\n")
    Path("manifest").write_text(
        """
from bake import load, block

load("dummy_flows")
block(name="nortl", top="m")                          # no rtl_files — omitted
block(name="withrtl", top="m", rtl_files=["block.v"]) # has rtl_files — listed
        """
    )
    assert not bake.run([])
    out = stderr(capfd)
    assert "withrtl" in out
    assert "nortl" not in out


def test_lib_listed(bake, capfd, dummy_flows):
    """A lib() definition appears in the -l library listing."""
    Path("lib.v").write_text("`timescale 1ns/1ps\nmodule lib_cell();\nendmodule\n")
    Path("manifest").write_text(
        """
from bake import load, lib

load("dummy_flows")
lib(name="mylib", desc="Test library", netlist_files=["lib.v"])
        """
    )
    assert not bake.run(["-l"])
    assert_in_stderr(capfd, "mylib")


# ===========================================================================
# Tests — template variable expansion
# ===========================================================================

@pytest.fixture
def tpl_var_flow(tmp_run_dir):
    """An impl flow whose run script bakes ${BAKE_TOP} and a custom var into output."""
    flow_dir = Path("tpl_var_flows")
    flow_dir.mkdir()

    # Flow manifest
    with open(flow_dir / "manifest", "w") as f:
        f.write(
            """
import os
from bake import flow, lib
_base = os.path.dirname(os.path.abspath(__file__))
flow(
    name="tpl_impl",
    corners=[("TC", "Typical Case")],
    run_cmd="run.sh",
    dir=os.path.join(_base, "impl"),
)
lib(name="tpl_lib", liberty_files={"TC": [os.path.join(_base, "tpl_lib_tc.lib")]})
config.impl.default_libs.append("tpl_lib")
            """
        )
    (flow_dir / "tpl_lib_tc.lib").write_text("library (tpl_lib_tc) {}\n")

    (flow_dir / "impl").mkdir()
    # The .tpl substitutes BAKE_TOP and a custom BAKE_ variable.
    # $$ becomes a literal $ in the output (escapes the shell variable).
    with open(flow_dir / "impl" / "run.sh.tpl", "w") as f:
        f.write(
            "#!/bin/bash\n"
            "mkdir -p output\n"
            "touch output/${BAKE_TOP}.v\n"
            "touch output/${BAKE_TOP}.sdf\n"
            "touch output/${BAKE_TOP}_tc.lib\n"
            "echo ${BAKE_CUSTOM_VAR} > output/custom_var.txt\n"
        )
    (flow_dir / "impl" / "run.sh.tpl").chmod(0o744)


def test_tpl_custom_variable_expanded(bake, tpl_var_flow):
    """config.bake.tpl_dict custom variable is substituted into .tpl files."""
    Path("block.v").write_text("`timescale 1ns/1ps\nmodule dut();\nendmodule\n")
    Path("manifest").write_text(
        """
from bake import load, block

load("tpl_var_flows")
config.impl.flow = "tpl_impl"
config.bake.tpl_dict["BAKE_CUSTOM_VAR"] = "hello_bake"

block(name="dut", top="dut", rtl_files=["block.v"])
        """
    )
    assert not bake.run(["dut", "impl"])
    # The expanded run.sh has the literal value baked in at template-expansion time.
    run_sh = Path("work/dut/impl/run.sh").read_text()
    assert "hello_bake" in run_sh
    assert "${BAKE_CUSTOM_VAR}" not in run_sh


def test_tpl_undefined_variable_in_flow_errors(bake, capfd, dummy_flows):
    """A .tpl file referencing an undefined $BAKE_ variable surfaces as an error."""
    Path("block.v").write_text("`timescale 1ns/1ps\nmodule m();\nendmodule\n")

    # Create a flow with an undefined template variable.
    flow_dir = Path("bad_tpl_flows")
    flow_dir.mkdir()
    (flow_dir / "impl").mkdir()
    with open(flow_dir / "impl" / "run.sh.tpl", "w") as f:
        f.write(
            "#!/bin/bash\n"
            "mkdir -p output\n"
            "touch output/m.v output/m.sdf output/m_tc.lib\n"
            "echo ${BAKE_UNDEFINED_VAR_XYZ}\n"
        )
    (flow_dir / "impl" / "run.sh.tpl").chmod(0o744)
    with open(flow_dir / "manifest", "w") as f:
        f.write(
            """
import os
from bake import flow
_base = os.path.dirname(os.path.abspath(__file__))
flow(name="bad_tpl_impl", corners=[("TC","TC")], run_cmd="run.sh",
     dir=os.path.join(_base, "impl"))
            """
        )

    Path("manifest").write_text(
        """
from bake import load, block

load("dummy_flows")
load("bad_tpl_flows")
config.impl.flow = "bad_tpl_impl"

block(name="m", top="m", rtl_files=["block.v"])
        """
    )
    assert bake.run(["m", "impl"])
    assert_in_stderr(capfd, "undefined")


# ===========================================================================
# Tests — environment and test inheritance
# ===========================================================================

def test_env_three_level_inheritance(bake, dummy_flows):
    """Files from a three-level env chain (env→env→test) all reach the vrf step.

    After template expansion BAKE_SIM_FILES is baked into the vrf run script,
    so reading run.sh lets us verify that every level's files are present.
    """
    # Create a vrf flow that writes BAKE_SIM_FILES into the run script body.
    flow_dir = Path("dummy_flows") / "vrf3"
    flow_dir.mkdir()
    with open(flow_dir / "run.sh.tpl", "w") as f:
        f.write("#!/bin/bash\necho ${BAKE_SIM_FILES}\n")
    (flow_dir / "run.sh.tpl").chmod(0o744)

    with open(Path("dummy_flows") / "manifest", "a") as f:
        f.write(
            """
import os
_base = os.path.dirname(os.path.abspath(__file__))
flow(name="vrf3", simulators=[("stub","Stub")], run_cmd="run.sh",
     dir=os.path.join(_base, "vrf3"))
            """
        )

    for name in ("dut.v", "base.v", "mid.v", "leaf.v"):
        Path(name).write_text(f"`timescale 1ns/1ps\nmodule {name[:-2]}();\nendmodule\n")

    Path("manifest").write_text(
        """
from bake import load, block, env, test

load("dummy_flows")
config.vrf.flow = "vrf3"

block(name="dut", top="dut", rtl_files=["dut.v"])

env(name="base_env", target="dut", vrf_files=["base.v"])
env(name="mid_env",  target="dut", includes=["base_env"], vrf_files=["mid.v"])

test(name="leaf_test", target="dut", includes=["mid_env"],
     vrf_files=["leaf.v"], default_sim="stub")
        """
    )
    assert not bake.run(["dut", "vrf"])
    # VrfStep includes the test name in its workdir (work/<block>/vrf/<test>/).
    run_sh = Path("work/dut/vrf/leaf_test/run.sh").read_text()
    assert "base.v" in run_sh
    assert "mid.v" in run_sh
    assert "leaf.v" in run_sh


# ===========================================================================
# Tests — recipe and output directory error paths
# ===========================================================================

def test_unknown_step_in_chain_errors(bake, capfd, sample_target):
    """A recipe containing an unknown step name is rejected with a clear error."""
    assert bake.run(["sample_target", "vrf-bogus"])
    assert_in_stderr(capfd, "bogus")


def test_output_dir_override(bake, sample_target):
    """config.bake.output_dir redirects step work output to a custom path."""
    Path("manifest").write_text(
        Path("manifest").read_text() +
        '\nconfig.bake.output_dir = "custom_out"\n'
    )
    assert not bake.run(["sample_target", "impl"])
    assert Path("custom_out/sample_target/impl/output/sample.v").exists()
    assert not Path("work/sample_target/impl").exists()


def test_check_post_failure_reported(bake, capfd, sample_with_check_step):
    """check_post() failure is reported when a step exits 0 but produces no outputs."""
    # Replace the flow script with one that exits 0 without creating the output file.
    Path("custom_step_dir/flow/run.sh.tpl").write_text("#!/bin/bash\n")
    Path("custom_step_dir/flow/run.sh.tpl").chmod(0o744)
    assert bake.run(["sample_target", "check"])
    assert_in_stderr(capfd, "did not produce all required files")
