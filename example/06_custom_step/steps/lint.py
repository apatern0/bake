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

"""A custom `lint` step: runs verilator --lint-only on a block's RTL.

Loaded by add_steps_dir("steps/") in the manifest. Like a manifest, this file
runs with `config` injected, so it can register its own config section.
"""

from pathlib import Path

from bake.step import Step
from bake.manifest import FlowSpec


class LintConfig:
    def __init__(self):
        self.flow         = ""
        self.flow_options = {}
        self.options      = []   # extra flags forwarded to the linter


config.register('lint', LintConfig())


class LintStep(Step):
    name         = "lint"
    default_flow = "lint_flow"

    @property
    def source_files(self):
        # Timestamp tracking: re-run when any of these is newer than the outputs.
        return list(self.data.rtl_files) + list(self.data.rtl_incdirs)

    @property
    def output_files(self):
        return [str(self.outputdir / "lint.log")]

    def build_tpl_dict(self):
        tpl = super().build_tpl_dict()
        tpl["BAKE_LINT_FILES"]   = " ".join(self.data.rtl_files)
        tpl["BAKE_LINT_INCDIRS"] = " ".join(f"-I{d}" for d in self.data.rtl_incdirs)
        tpl["BAKE_LINT_OPTIONS"] = " ".join(self.config.options)
        return tpl


FlowSpec(
    name    = "lint_flow",
    run_cmd = "run.sh",
    dir     = str(Path(__file__).parent.parent / "flows" / "lint"),
)
