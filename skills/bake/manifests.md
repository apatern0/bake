# bake: writing manifests, flows and steps

Read with the bake skill's SKILL.md (commands, work directories). The `docs/` named here are
those of the same bake checkout.

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
macro(name="adc", top="adc", layout_info="adc.lef")   # a LEF only: include it as {"adc": "blackbox"},
                                        # which writes its Verilog and Liberty (config.blackbox)
# bake <block> [<recipe>-]portscheck checks that a block's LEF, Liberty, netlist and LVS netlist
# agree on its ports (config.portscheck.waive accepts findings)
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
  load, built on demand before the block's own steps. `{"sub": "release"}` uses the release of
  `sub` that `config.release.use` selects (`-o release.use.sub=<version>`, searched in
  `config.release.path`), building nothing of `sub`; without a selection it is
  `{"sub": "impl"}` (`config.release.recipe`, or the block's `release_recipe=`). `external()`
  declares a block that only exists as releases (docs/manifest_design_model.md#releases,
  docs/release_format.md). `bake <block> impl-publish -o publish.root=<dir>` makes a release;
  `external(source="adc.ini")` names the INI file listing a block's views, and `bake adc publish` makes a release of them (docs/release_format.md#source-files).
  `variant("top", "r1", release={"sub": "<version>"})` declares `top@r1`: top with those
  releases and its own work directory; flows see `$BAKE_BLOCK=top`, `$BAKE_VARIANT=r1`. Each step takes some data kinds (RTL, an
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
  so manifests don't see them. One key of a dict attribute is set the same way, after loading:
  `-o impl.flow_options.pixel_pitch=120`; the dict as a whole cannot be set with `-o`.
- Unknown names, values of the wrong kind and values outside the choices stop bake before
  anything runs, with a suggestion. `bake --list-options -o ...` shows the effect.

## Tasks

| To | Do | Docs |
|---|---|---|
| repeat a failing simulation | `bake <block> vrf -t <test> -o vrf.seed=<N>` (the seed is logged as `Simulation seed: N`) | `manifest_verif_model.md#seeds` |
| pass plusargs without rebuilding | `vrf_runtime_options` / `-o vrf.runtime_options=+X=1`; `vrf_options`, defines and files make a build of their own | `#building-once-for-many-tests` |
| hand a test's dump to a later step, and skip the simulation while it is up to date | `vrf_outputs=["activity.vcd"]`; the next step reads `self.data.sim_outputs` | `manifest_verif_model.md#files-a-test-writes` |
| make a plain testbench fail on errors | `vrf_fail_regex` / `vrf_pass_regex` (UVM: report summary and counts are checked already) | `#passfail-criteria` |
| run tests many times | `regression()`, `bake <regression> regression`; build earlier steps and dependencies first | `#regressions` |
| compare settings | `sweep()` over project options or attributes, `bake <sweep> sweep`; `report.md` pastes into a pull request | `manifest_design_model.md#sweeps` |
| change a flow for one block | `-p`, edit the copy, commit it with `.bake_flow.json`; after "Flow ... has changed": `--update-flow` merges it (git base; conflicts get markers), or merge by hand then `-p` to record it | `custom_flows.md#customising-a-flow-for-one-block` |
| generate source text (loops over flattened netlist names, per-test variants) | name the source `*.tpl`: Jinja rendered with the step's `$BAKE_*` variables; `${expr}`, `//% stmt` lines, `//#` comments | `manifest_design_model.md#source-templates` |
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

- A custom step reads only `self.data` and `self.config`, never `context` at run time; validity
  that depends on the recipe goes in `check_pre()`.
- See also the running pitfalls in SKILL.md.
