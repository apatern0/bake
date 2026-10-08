# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What bake is

bake is a Python-based ASIC build and verification framework. It automates design flows (TMR insertion, simulation, synthesis, place-and-route) driven by `manifest` files — plain Python files that declare design intent and configuration. The CLI entry point is `bake`.

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
# Optional: for argcomplete support
eval "$(register-python-argcomplete bake)"
```

## Common commands

```bash
# Run tests
pytest

# Run a single test
pytest test/test_bake.py::test_function_name

# Reproduce what a test sees by hand
cd test/projects/hier && bake top2 vrf

# Invoke bake in a project directory containing a manifest
bake                          # list available blocks, tests and steps
bake <block> <recipe>         # e.g. bake counter vrf, bake counter tmr-impl
bake <block> <recipe> -t <test>  # specify test explicitly
bake <block> <recipe> -f     # force re-run even if outputs are up-to-date
bake <block> <recipe> -c     # clean output directory for the step
bake <block> <recipe> -r     # clean then re-run (restart)
bake <block> <recipe> -p     # copy the last step's flow into flow/ to customise it; runs nothing
bake <block> <recipe> -n     # dry run: report what would run, dependencies included
bake -l                      # list all known libraries
bake -v                      # verbose / debug output
bake -o step.attr=value     # override a config attribute from the CLI
```

## Architecture

### Core concepts

- **`manifest`** — a Python file (always named literally `manifest`, no extension) that is `exec`'d by bake. It calls `block()`, `macro()`, `test()`, `env()`, `regression()`, `lib()`, `flow()` and `load()` to register design objects into the global `context`; a `Step` subclass defined in it registers itself.
- **Block** (`BlockSpec`) — a design unit with RTL files, a top module, and optional timing/netlist libraries.
- **Test** (`TestSpec`) / **Env** (`EnvSpec`) — a simulation environment associated with a block. Tests carry verification files; envs are reusable base environments that tests include via `includes=`.
- **Flow** (`FlowSpec`) — a directory of scripts (`.tpl` templated) that one step executes. Steps use flows; a flow is not a recipe.
- **Regression** (`RegressionSpec`) — tests of a block run many times (random seeds or given ones), plus the runs of the regressions it includes; a design spec of kind `regression` (`RegressionData.runs`), run by the `regression` step, which invokes bake once per run with `vrf.seed` and `vrf.run_dir`.
- **Step** — one unit of the pipeline (e.g. `vrf`, `impl`, `tmr`, `regression`). Steps are Python classes subclassing `Step` in `bake/step.py`. Built-in steps live in `bake/builtin/`.
- **Recipe** — an ordered series of steps, written as a hyphen-joined string (`impl`, `tmr-impl`, `tmr-impl-vrf`). Elaborated by `Recipe.elaborate()` into a list of `Step` instances.
- **`StepData`** — a dataclass threaded through the pipeline. Initialized from `BlockSpec`/`EnvSpec` by `StepData.create()`, then freely mutated by each step. It holds no manifest object: `block`, `block_dir` and `test` are plain names; all working state (`top`, `rtl_files`, `vrf_files`, etc.) is a copy. Steps **must not** access `context` registries at runtime — only `self.data` and `self.config`.
- **Data kinds** — `StepData` is the base (identity, `top`, test state, bookkeeping); each subclass is one form of the design: `RtlData` (RTL, with included implemented sub-blocks kept whole in `macros`), `LibData` (an implemented block: netlist + abstracts) and `RegressionData` (the runs of a `regression()`). A `block()` (RTL only) starts as `RtlData`, a `macro()` (an implemented block: netlist + abstracts, the same fields as a cell-library `lib()`, shared through `AbstractsSpec`) as `LibData`; a `lib()` is not a design and is named in `libs=`, never included. A step declares `consumes` (kinds it takes; default any) and `produces` (default: the kind taken); `Recipe.elaborate()` calls `check_kind()` before `check_pre()`, and a step changing the kind builds its output with `data.convert(Kind, ...)`. Includes merge by kind (`StepData.accepts`, `absorb()`): rtl ← rtl merges the fields, rtl ← lib appends to `macros`.
- **Design specs** — `DesignSpec` (in `manifest.py`) is the base of everything registered in `context.blocks`: name, desc, includes, tests, registration, plus `data_type`, `to_data()` and the `_resolve()` hook. `BlockSpec` (`block()`) is one; a tool adds its own kind (spec + StepData subclass in an importable module, step/config/flow in a manifest projects `load()`), e.g. rdl2verilog's `rdl()`. `context.validate()` checks each include's kind statically with `step.include_kind()` from the steps' declared signatures. Error messages name a spec's manifest function via its `manifest_function` class attribute (`manifest.spec_class()`).
- **Dependency** — a recipe-form include (`includes={"sub": "impl"}`). Declared in the manifest, checked statically by `context.validate()` once all manifests are loaded (existence, step names, cycles), resolved when a recipe is elaborated, and built on demand before the requesting block's steps (`cli.run`). A step refuses data it cannot consume in `check_pre()`.

### Module layout

| Module | Role |
|--------|------|
| `bake/manifest.py` | Pydantic specs (`FlowSpec`, `LibSpec`, `DesignSpec`/`BlockSpec`/`MacroSpec`/`RegressionSpec`, `EnvSpec`, `TestSpec`) registered into `context` at parse time |
| `bake/context.py` | Singleton `Context` (registries: `flows`, `libs`, `blocks`, `envs`, `tests`, `steps`) and `Config` (per-step config sections, `BakeConfig`) |
| `bake/loader.py` | `exec`s manifest files; changes `cwd` to the manifest directory during loading so relative paths resolve correctly; deduplicates via a global `loaded` list |
| `bake/step.py` | `StepData` and its kinds (`RtlData`, `LibData`, `RegressionData`), `Step` ABC, `Recipe`, timestamp-based `run_required()`, template expansion (`copy_and_template`), flow selection and `-p` copies (`flowdir`, `populate`, `report_flow`) |
| `bake/cli.py` | Argument parsing, builtin manifest loading, dispatch to `run()` in cli itself |
| `bake/exceptions.py` | Seven custom exception classes (`BakeRuntimeError`, `BakeManifestError`, `BakeConfigError`, etc.) |
| `bake/file_utils.py` | Path resolution and file existence utilities |
| `bake/completion_cache.py` | JSON-backed tab-completion cache in `~/.cache/bake/` |
| `bake/builtin/` | Built-in steps (`vrf`, `impl`, `tmr`, `regression`), each in its own subdirectory with a `manifest` |

### Data flow

1. CLI calls `loader.load()` on the user's manifest directory (and all builtins first).
2. `exec`'ing each manifest populates `context` with `BlockSpec`, `TestSpec`, `FlowSpec`, etc.
3. CLI `run()` builds `step.Recipe(block, recipe)` and calls `elaborate()`.
4. `Recipe.elaborate()` creates a `StepData` from the block/test (elaborating dependency recipes for recipe-form includes and recording them in `recipe.dependencies`), instantiates each `Step` in chain order, runs `check_pre()`, and threads `output_data` forward.
5. For each step: `report_flow()` (which flow runs: the block's copy in `flow/<block>/<recipe>/` when `-p` made one, the flow's own directory otherwise; warns when a copy's flow changed since, per its `.bake_flow.json`), then `run()` which checks timestamps, calls `copy_and_template()` to expand `.tpl` files, then `execute_flow_step()` (subprocess). `-p` calls `populate()` on the recipe's last step only and runs nothing.

### Template variables

Flow scripts are `.tpl` files using Python `string.Template` (`$BAKE_XYZ` substitution). All template variables must be prefixed `BAKE_`. Each step's `build_tpl_dict()` populates the variables it exposes (e.g. `BAKE_TOP`, `BAKE_SIM_FILES`, `BAKE_SIM_SIMULATOR`). Custom template variables can be added in manifests via `config.bake.tpl_dict["BAKE_MY_VAR"] = "value"`.

### Writing a custom step

Subclass `Step`, set `name`, implement `source_files` and `output_files` (and `check_pre`/`build_tpl_dict`/`output_data` as needed) in a manifest laid out like a built-in step (`steps/<name>/manifest` + `steps/<name>/flow/`), and `load("steps/<name>")` it from the project manifest. The class registers itself via `Step.__init_subclass__`.

### Config sections

Each step registers its own config section via `config.register('stepname', StepCfg())` at module load time. Users set config in manifests via `config.vrf.simulator = "xcelium"` etc. The `BakeConfig` section (`config.bake`) controls global bake behavior.

## Logging conventions

bake uses the standard Python `logging` module with `coloredlogs` for console output. The format is `[bake] LEVEL<tab>message`. The `-v` flag enables `DEBUG` level; the default is `INFO`.

| Level | When to use |
|-------|-------------|
| `DEBUG` | Internal state transitions that are useful when diagnosing an unexpected behavior: manifest loading, step/flow/block registration, config section creation, template expansion details, recipe elaboration steps. |
| `INFO` | User-visible progress and decisions: which step is running, why a step is skipped or re-run, populating/cleaning directories, auto-selected test, heartbeat during long runs. |
| `WARNING` | Recoverable situations the user should know about: all-symlink output files, missing optional resources. |
| `ERROR` | Unrecoverable failures surfaced before `sys.exit(1)`: bad manifest, missing files, step execution failure. |

Key invariant: `logging.info()` messages must make sense to a user who does not know Python internals. `logging.debug()` messages can reference internal module names, file paths, and counts.

## Error handling

- `BakeManifestError` — semantic errors in the manifest (redefined block, missing library, bad include).
- `BakeConfigError` — invalid config attribute access or write.
- `BakeRuntimeError` — base for all bake exceptions; caught by CLI for clean exit.
- `BakeStepExecutionError` — non-zero return code from a flow script; caught separately to suppress the traceback.
- `BakeIncludeError` — an include names a block or env that does not exist.
- `BakeFileError` — missing file or directory, raised by `file_utils`.
