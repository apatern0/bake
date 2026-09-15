# Custom Steps

*bake* is designed to be extended with project-specific pipeline steps. A custom step is a
Python class that subclasses `Step`, lives in a directory registered with `add_steps_dir()`,
and is discovered automatically on the next *bake* invocation.

## Step Anatomy

Every step is a Python class with the following structure:

```python
from bake.step import Step, StepData
from bake.manifest import FlowSpec

# 1. Optional config section — register before the class definition
class MyStepConfig:
    def __init__(self):
        self.flow         = ""
        self.flow_options = {}
        self.options      = []

config.register('mystep', MyStepConfig())

# 2. Step class
class MyStep(Step):
    name         = "mystep"    # must not contain hyphens
    default_flow = "my_flow"   # name of a registered FlowSpec
    require_test = False        # set True if the step needs a test (like vrf)

    @property
    def source_files(self):
        """Return a list of absolute paths that serve as inputs to this step.
        bake uses this list for timestamp-based dependency tracking."""
        return list(self.data.rtl_files)

    @property
    def output_files(self):
        """Return a list of absolute paths that this step is expected to produce.
        bake reports an error if any of these files are missing after the step runs."""
        return [str(self.outputdir / "report.txt")]

    def build_tpl_dict(self):
        """Return a dict of $BAKE_XYZ variables to substitute in .tpl files.
        Always call super() first to inherit the base variables."""
        tpl = super().build_tpl_dict()
        tpl["BAKE_RTL_FILES"] = " ".join(self.data.rtl_files)
        return tpl

    @property
    def output_data(self):
        """Optionally propagate modified state to the next step in the chain.
        Call super() to get a copy of self.data with recipe_path updated,
        then mutate it before returning."""
        data = super().output_data
        # Example: tell downstream steps about an artifact produced here
        # data.netlist_files = [str(self.outputdir / "netlist.v")]
        return data


# 3. Register the flow used by this step
FlowSpec(
    name    = "my_flow",
    run_cmd = "run.sh",
    # dir defaults to Path.cwd() / "flow" — override if the flow lives elsewhere
    # dir   = str(Path(__file__).parent / "flow"),
)
```

Key rules:
- `name` must be a non-empty string with no hyphens (hyphens are the recipe separator).
- `source_files` and `output_files` are abstract — you must implement both.
- `build_tpl_dict()` and `output_data` are optional overrides; call `super()` in both.
- The `config` variable is available in the step file scope at load time (injected by the manifest executor), so `config.register()` can be called at module level.
- Steps **must not** access `context` registries (`context.libs`, `context.blocks`, etc.) at
  runtime. Read everything from `self.data` and `self.config` only.

## Registering the Step Directory

Place your step file anywhere in your project, then register its directory in the manifest:

```python
from bake import block, test, add_steps_dir

add_steps_dir("steps/")   # relative to this manifest file

block(...)
test(...)
```

*bake* scans every `.py` file in the registered directory and imports any `Step` subclass it
finds. The step is then available under its `name` in recipes.

## Full Example: A Linting Step

This example adds a `lint` step that runs a Verilog linter on the RTL files of a block and
produces a report. It can be used standalone (`bake myblock lint`) or prepended to a chain
(`bake myblock lint-vrf`).

### Project layout

```
my_project/
├── manifest
├── rtl/
│   └── my_block.v
├── steps/
│   └── lint_step.py
└── flows/
    └── lint_flow/
        └── run.sh.tpl
```

### `steps/lint_step.py`

```python
"""Linting step — runs verilator --lint-only on RTL files."""

import os
from pathlib import Path

from bake.step import Step, StepData
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
        return list(self.data.rtl_files) + list(self.data.rtl_incdirs)

    @property
    def output_files(self):
        return [str(self.outputdir / "lint.log")]

    def build_tpl_dict(self):
        tpl = super().build_tpl_dict()
        tpl["BAKE_LINT_FILES"]   = " ".join(self.data.rtl_files)
        tpl["BAKE_LINT_INCDIRS"] = " ".join(
            f"-I{d}" for d in self.data.rtl_incdirs
        )
        tpl["BAKE_LINT_OPTIONS"] = " ".join(self.config.options)
        return tpl


FlowSpec(
    name    = "lint_flow",
    run_cmd = "run.sh",
    dir     = str(Path(__file__).parent.parent / "flows" / "lint_flow"),
)
```

### `flows/lint_flow/run.sh.tpl`

```bash
#!/bin/bash
set -e
mkdir -p output

verilator --lint-only $BAKE_LINT_INCDIRS $BAKE_LINT_OPTIONS $BAKE_LINT_FILES \
    2>&1 | tee output/lint.log

echo "Lint finished."
```

### `manifest`

```python
from bake import block, test, add_steps_dir

add_steps_dir("steps/")

block(
    name="my_block",
    top="my_block",
    rtl_files=["rtl/my_block.v"],
)

test(
    name="my_test",
    target="my_block",
    vrf_files=["vrf/my_test.v"],
    default_sim="icarus",
)
```

### Usage

```
$ bake my_block lint           # lint only
$ bake my_block lint-vrf       # lint, then simulate
$ bake my_block lint -o lint.options=--Wall   # pass extra linter flags
```

## Propagating Results to Downstream Steps

When a step transforms files (e.g. generates a netlist, renames the top module, or adds defines),
it should update `output_data` so that later steps in the chain see the correct inputs:

```python
@property
def output_data(self):
    data = super().output_data      # copy with recipe_path updated
    # Replace RTL files with the generated netlist
    data.netlist_files = [str(self.outputdir / f"{self.data.top}_processed.v")]
    data.rtl_files     = []
    # Expose a define for downstream simulators
    data.vrf_defines.append("PROCESSED")
    return data
```

The built-in `TmrStep` follows this exact pattern: it replaces `rtl_files` with the triplicated
output, renames `top` to `<top>TMR`, and appends `"TMR"` to `vrf_defines`.

## StepData Field Reference

All fields are available on `self.data` and can be read by any step. Only modify fields that
your step is logically responsible for.

| Field | Type | Populated by |
|-------|------|-------------|
| `target` | `BlockSpec` | Manifest, read-only |
| `test` | `EnvSpec \| None` | Manifest, read-only |
| `top` | `str` | Manifest `block()`, modified by `tmr` |
| `rtl_files` | `list[str]` | Manifest `block()`, modified by `tmr` |
| `rtl_incdirs` | `list[str]` | Manifest `block()` |
| `libs` | `list[LibSpec]` | Manifest `block()` |
| `netlist_files` | `list[str]` | Manifest or `impl` output |
| `netlist_incdirs` | `list[str]` | Manifest or `impl` output |
| `liberty_files` | `dict[str, list[str]]` | Manifest or `impl` output |
| `layout_info` | `str` | Manifest or `impl` output |
| `sdc_files` | `list[str]` | Manifest `block()` |
| `sdf_files` | `dict[str, str]` | `impl` output |
| `vrf_top` | `str` | Manifest `test()` / `env()` |
| `vrf_files` | `list[str]` | Manifest `test()` / `env()` |
| `vrf_incdirs` | `list[str]` | Manifest `test()` / `env()` |
| `vrf_libs` | `list[LibSpec]` | Manifest `test()` / `env()` |
| `vrf_defines` | `list[str]` | Manifest, modified by `tmr` |
| `vrf_options` | `dict[str, list[str]]` | Manifest `test()` / `env()` |
| `vrf_framework` | `str` | Manifest `test()` / `env()` |
| `vrf_framework_top` | `str` | Manifest `test()` / `env()` |
| `default_sim` | `str` | Manifest `test()` / `env()` |
| `recipe_path` | `RecipePath` | Orchestrator (append-only) |
| `is_last` | `bool` | Orchestrator |
