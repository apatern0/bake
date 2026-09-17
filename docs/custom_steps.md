# Custom Steps

*bake* is designed to be extended with project-specific pipeline steps. A custom step is a
Python class that subclasses `Step`, defined in manifest code: a step registers itself when its
class body runs, so it can live in the project manifest or, more usefully, in a manifest of
its own that the project `load()`s. The built-in steps are written the same way — look at
`bake/builtin/vrf/manifest` for a complete one.

## Step Anatomy

Every step is a Python class with the following structure:

```python
from bake.step import Step, StepData
from bake.manifest import FlowSpec
from bake.exceptions import BakeRuntimeError

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
        bake re-runs the step when one is newer than the outputs (symlinks
        are followed) or when the list itself changes."""
        return list(self.data.rtl_files)

    @property
    def output_files(self):
        """Return a list of absolute paths that this step is expected to produce.
        bake reports an error if any of these files are missing after the step
        runs, and again on later runs if one disappears. A step declaring no
        outputs always runs."""
        return [str(self.outputdir / "report.txt")]

    def check_pre(self):
        """Optionally refuse to run on data this step cannot consume.
        Called during elaboration, before anything runs; raise a
        BakeRuntimeError whose message says what is missing or unsupported."""
        if not self.data.rtl_files:
            raise BakeRuntimeError(f"Step mystep needs RTL files; block '{self.data.block}' has none.")

    def build_tpl_dict(self):
        """Return a dict of $BAKE_XYZ variables to substitute in .tpl files.
        Always call super() first: it provides $BAKE_TOP, $BAKE_BLOCK,
        $BAKE_RECIPE, the flow options and the user's tpl_dict entries."""
        tpl = super().build_tpl_dict()
        tpl["BAKE_RTL_FILES"] = " ".join(self.data.rtl_files)
        return tpl

    @property
    def output_data(self):
        """Optionally propagate modified state to the next step in the chain.
        Call super() to get an independent copy of self.data with
        recipe_prefix updated, then mutate it before returning."""
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
- Everything `build_tpl_dict()` returns is part of what the step was built from: a change in
  any variable re-runs the step (see [When a step runs](cli.md#when-a-step-runs)).
- `config` is available in every manifest's scope, so `config.register()` can be called at module level.
- Steps **must not** access `context` registries (`context.libs`, `context.blocks`, etc.) at
  runtime. Read everything from `self.data` and `self.config` only.

## Where a Step Lives

Give each step its own directory in the project, with the manifest that defines it next to a
`flow/` directory holding its scripts — the layout of the built-in steps:

```
steps/lint/
├── manifest          # LintConfig, config.register(), class LintStep, flow(name=..., run_cmd=...)
└── flow/
    └── run.sh.tpl
```

Then bring it in from the project manifest like any other manifest:

```python
from bake import load, block, test

load("steps/lint")        # relative to this manifest file

block(...)
test(...)
```

Because the step manifest runs with its own directory as the working directory, `flow()` finds
`flow/` next to it without a `dir=` argument, and paths in the step manifest are relative to
the step directory. The step is then available under its `name` in recipes, listed by `bake`
next to the built-in ones. A step directory can be shared between projects by `load()`ing it
from wherever it is checked out.

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
└── steps/
    └── lint/
        ├── manifest
        └── flow/
            └── run.sh.tpl
```

### `steps/lint/manifest`

```python
"""Linting step — runs verilator --lint-only on RTL files."""

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
    run_cmd = "run.sh",      # found in flow/ next to this manifest
)
```

### `steps/lint/flow/run.sh.tpl`

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
from bake import load, block, test

load("steps/lint")

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
    data = super().output_data      # independent copy with recipe_prefix updated
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
your step is logically responsible for. `StepData` holds no manifest object: the block's and
test's declarations are copied into it when the recipe is elaborated, so nothing a step does can
alter the registered manifest.

| Field | Type | Populated by |
|-------|------|-------------|
| `block` | `str` | Block name (directory layout, `$BAKE_BLOCK`) |
| `block_dir` | `str` | Directory of the manifest that defined the block |
| `test` | `str` | Name of the selected test, `""` when the recipe needs none |
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
| `recipe_prefix` | `RecipePath` | Orchestrator: the steps executed before this one (`self.recipe_path` adds the step's own name) |
| `is_last` | `bool` | Orchestrator: `True` for the last step of the recipe |
