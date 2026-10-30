---
name: bake
description: Running and writing for bake, the manifest-driven ASIC build and verification tool. Use for `bake <block> <recipe>` commands (-t, -o, -n, -f/-c/-r/-p, --list-options), reading a run's work directory, and writing manifests — block(), macro(), lib(), env(), test(), regression(), sweep(), project()/option(), load(), flow(), config sections — as well as custom flows ($BAKE_* variables, bake_vars.json, summary.json) and custom steps. Describes the bake of the checkout it ships in.
---

# bake

You **bake** a **block** with a **recipe**; a recipe is a series of **steps** joined by hyphens
(`impl`, `tmr-impl-vrf`); each step runs a **flow**, a directory of scripts and `.tpl` templates.
Blocks, tests and the rest are declared in files named `manifest`: plain Python that bake
`exec`s.

## Which bake

This skill ships inside bake (`skills/bake/`) and describes the bake of that checkout. A project
usually pins bake as a submodule (e.g. `tools/bake`) and links the skill from there, so the two
match. The full documentation is `docs/` of the same checkout:

```sh
python -c "import bake, pathlib; print(pathlib.Path(bake.__file__).parents[1] / 'docs')"
bake --version
```

When the project runs another bake than the one this skill sits in (an older pin, a different
venv), trust `bake -h` and that checkout's `docs/`. Options this skill names may not exist there
yet (`--list-options`, `sweep()` and `project()` options are recent).

## Commands

```sh
bake                                # list the top project's blocks, tests, dependencies and steps
bake -a                             # ... of every project the manifests load
bake <block> <recipe>               # run; up-to-date steps are skipped, stale dependencies built first
bake <block> vrf -t <test>          # -t needed when the block has more than one test
bake <block> <recipe> -n            # dry run: what would run, and why
bake <block> <recipe> -f            # force the requested recipe (dependencies only when stale)
bake <block> <recipe> -c | -r       # clean the work directory | clean then run
bake <block> <recipe> -p            # copy the last step's flow to flow/<block>/<recipe>/ to customise; runs nothing
bake <block> <recipe> -i            # interactive (simulator GUI), where the flow supports it
bake -o section.attr=value ...      # override a config attribute (repeatable)
bake -o option=value ...            # set an option of the top project
bake --list-options [-o ...]        # every option and attribute: value, origin, kind, choices, description
bake -l                             # libraries and macros
bake -m <dir> ...                   # manifest in another directory
```

- The target is a **block** (or a regression or sweep, which are blocks of their own kind),
  never a test: `bake <test> vrf` fails with "No such block".
- `-f`, `-c`, `-r`, `-p` exclude each other; `-p` combines with neither `-n` nor `-i`; `-n`
  combines with `-f` only.
- Exit status: 0 success, 1 manifest/step/run failure or interrupt, 2 command-line error.
  `-v` adds debug output and tracebacks.

## Reading a run

| Where | What |
|---|---|
| `work/<block>/<recipe>/` | a step's work directory (`config.bake.output_dir` moves `work/`); vrf adds `/<test>` |
| `.../bake_vars.json` | every `$BAKE_*` variable the flow got, lists as lists |
| `.../.bake_stamp.json` | written when the step completed; missing = the step will run again |
| `.../summary.json` | how the run went, if its flow writes one (status, stage, error, metrics, notes, inspect) |
| `work/<block>/<recipe>/_build/` | simulation builds shared by a block's tests |
| `work/<regression>/regression/` | `runs/<block>/<test>/<n>/run.log`, `results.csv` |
| `work/<sweep>/sweep/` | `runs/<variant>/`, `report.md`, `results.csv`, `sweep.pid` |
| `flow/<block>/<recipe>/` | a flow copy made by `-p`, with `.bake_flow.json` |

A step is skipped only when its outputs exist, its last run completed, its inputs (bake version,
template variables, file list, flow contents) are unchanged and no source is newer than the
oldest output. `-n` prints the reason for each step that would run.

## Manifests

```python
from bake import project, option, load, block, macro, lib, env, test, regression, sweep

project("chip", pitch=option(100, "Pixel pitch in um", choices=[100, 120]))  # first thing
load("ip")                              # the directory of another manifest; may start its own project

block(name="core", top="core", rtl_files=["rtl/core.sv"], rtl_incdirs=["rtl"],
      includes=["common"],              # RTL merged in; {"sub": "impl"} = sub's implemented output
      libs=["stdcells"])                # or config.bake.default_libs for every block
macro(name="fe", top="fe", netlist_files=["fe.v"], liberty_files={"TT": "fe_tt.lib"},
      layout_info="fe.lef")             # an implemented block (hard macro); included, never in libs=
lib(name="stdcells", liberty_files={"TT": "tt.lib"}, layout_info="cells.lef",
    cells={"site": "core", "filler": ["FILL4", "FILL1"], "tie_hi": ("TIEH", "Z")})  # roles: cells flows insert
env(name="core_env", target="core", vrf_top="tb", vrf_files=["tb.sv"], default_sim="icarus")
test(name="core_smoke", includes=["core_env"],
     vrf_runtime_options={"icarus": ["+HITS=10"]})   # simulation-only options share one build
regression(name="core_nightly", target="core", tests={"core_smoke": 20, "core_wrap": [11, 42]})
sweep(name="core_pitch", target="core", recipe="impl",
      variants={"p100": ["pitch=100"], "p120": ["pitch=120"]})

config.vrf.simulator = "icarus"         # sections: bake, vrf, impl, tmr, regression, sweep, ...
if config.proj.pitch == 120: ...        # a manifest sees the command line's options while loading
```

- Paths are relative to the manifest's directory. A `test()` is a leaf `env()`; envs are
  inherited through `includes`.
- An include in recipe form (`{"sub": "impl"}`) is a **dependency**: checked once all manifests
  load, built on demand before the block's own steps. Each step takes some data kinds (RTL, an
  implemented block, a register map...) and refuses others before anything runs.
- A tool (a generator, a vendor flow) comes in as a manifest the project `load()`s: its step,
  config section and `flow()`. There is no plugin mechanism and no `use()`.
- Settings a user chooses on the command line are **project options** (`project()`/`option()`,
  read as `config.proj.<x>` and `$BAKE_PROJ_<X>`), not `config.user` (`-o user.x=` is
  deprecated).

### How `-o` lands

- A project option holds from `project()` on, a section attribute from the moment its section
  is registered: manifests read the command line's value, and a manifest assigning it keeps the
  command line's value.
- Items of a list attribute (`-o vrf.options=-x`) are appended after every manifest has loaded,
  so manifests don't see them. A dict attribute (`flow_options`) cannot be set with `-o`.
- Unknown names, values of the wrong kind and values outside the choices stop bake before
  anything runs, with a suggestion. `bake --list-options -o ...` shows the effect.

## Tasks

| To | Do | Docs |
|---|---|---|
| repeat a failing simulation | `bake <block> vrf -t <test> -o vrf.seed=<N>` (the seed is logged as `Simulation seed: N`) | `manifest_verif_model.md#seeds` |
| pass plusargs without rebuilding | `vrf_runtime_options` / `-o vrf.runtime_options=+X=1`; `vrf_options`, defines and files make a build of their own | `#building-once-for-many-tests` |
| make a plain testbench fail on errors | `vrf_fail_regex` / `vrf_pass_regex` (UVM: report summary and counts are checked already) | `#passfail-criteria` |
| run tests many times | `regression()`, `bake <regression> regression`; build earlier steps and dependencies first | `#regressions` |
| compare settings | `sweep()` over project options or attributes, `bake <sweep> sweep`; `report.md` pastes into a pull request | `manifest_design_model.md#sweeps` |
| change a flow for one block | `-p`, edit the copy, commit it with `.bake_flow.json`; after "Flow ... has changed", merge, then `-p` again to record it | `custom_flows.md#customising-a-flow-for-one-block` |
| give a flow a knob | `tpl_defaults` in `flow()`, `config.<step>.flow_options[...]` in the project, `$BAKE_FLOW_OPT_<NAME>` in the template | `custom_flows.md#flow-specific-options` |
| tell flows which cells to insert (fillers, ties, clock tree, pad ring) | `lib(cells={role: cells})`; flows read `$BAKE_CELLS_<ROLE>` / `$BAKE_CELL_DATA` | `manifest_design_model.md#cell-roles` |
| read variables from a Python flow | `json.load(open(os.environ["BAKE_VARS"]))` rather than pasting `$BAKE_*` into strings | `#reading-the-variables-from-a-script-bake_varsjson` |
| report results from a flow | write `summary.json` in the work directory as the run goes | `#reporting-a-run-summaryjson` |
| run regressions or sweeps elsewhere | a flow of your own: start each `command` of `BAKE_REGRESSION_RUNS` / `BAKE_SWEEP_RUNS` in its own directory, exit nonzero on a failure | `#writing-a-regression-flow` |
| add a step | `Step` subclass + config section + `flow()` in `steps/<name>/manifest`, `load()`ed | `custom_steps.md` |
| add a kind of design | `DesignSpec` + `StepData` subclass in an importable module | `custom_steps.md#defining-a-kind-of-design` |

All configuration attributes and template variables: `configuration.md`. Command line,
up-to-date rules and interrupts: `cli.md`.

## Pitfalls

- The built-in vrf flow starts the simulator through a shell: a define or option whose value has
  quotes or spaces loses them. Pass strings as plusargs and read them with `$value$plusargs`.
- A step owns its processes: Ctrl-C reaches all of them, and what its script leaves running is
  ended when it exits. A server meant to outlive a run is started outside bake.
- Tests of a block share builds: `-r` on one of them removes the shared builds, and a build waits
  for the simulations running from it.
- A regression's runs build what they need themselves: many runs starting on a stale dependency
  all wait for it. Run `bake <block> <earlier recipe>` first.
- A custom step reads only `self.data` and `self.config`, never `context` at run time; validity
  that depends on the recipe goes in `check_pre()`.
- `-p` copies only the last step's flow; an untouched copy is better deleted than kept.
