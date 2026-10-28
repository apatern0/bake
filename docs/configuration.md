# Configuration

*bake* is configured directly in the `manifest` file using the `config` object, which is always
available in manifest scope without any import. Configuration is plain Python — sections are
attributes, and settings are attribute assignments:

```python
config.vrf.simulator = "xcelium"
config.bake.file_copy_method = "symlink"
```

Assigning an attribute a section does not have is an error that names the known attributes, so
a typo cannot pass unnoticed (`config.user` is the exception: it is free-form, see below).
Attributes declared with a description and a kind, as [project options](#project-options) are,
are checked as well: assigning one a value of another kind, or one outside its choices, is an
error at that line of the manifest.

Settings take effect before any step is executed. Configuration can also be overridden at the
command line with the `-o` flag: `-o section.attribute=value` for a section's attribute, and
`-o option=value`, without a section, for an option of the project:

```
bake counter vrf -o vrf.simulator=xcelium
bake counter impl -o width=16
```

## Project options

A project declares the settings its user chooses — a data width, a variant, the abstract of a
macro — with `project()`, first thing in its top manifest. It names the project and declares
every option at once, with its default, a description and, optionally, the values it may take:

```python
from bake import load, option, project

project(
    "demo",
    width=option(8, "Data width in bits", choices=[8, 16]),
    fast=option(False, "Build the fast variant"),
    tags=option([], "Tags of the build"),
)

load("rtl")   # its manifests read config.proj.width
```

A plain value (`fast=False`) declares an option without a description. The name is a letter
followed by letters, digits, `_` and `-`; `bake` lists the project's blocks under it. A top
manifest that calls no `project()` has a project without a name and without options, where
`-o option=value` is an error. Then:

- **Command line.** `-o` without a section sets an option: `bake counter impl -o width=16 -o
  fast=true`. A list option gets one item per `-o`, after its default. The command line's value
  holds from `project()` on: every manifest reads it, and a manifest assigning the option keeps
  the command line's value.
- **Manifests.** `config.proj` is the options in the project's manifests, so a manifest can
  decide on them while it loads, e.g. choose the files of a block with
  `if config.proj.width == 16:`.
- **Flows.** Every flow of the project's blocks sees the options as `$BAKE_PROJ_<OPTION>` —
  `$BAKE_PROJ_WIDTH` above — booleans as `1` or `0`, lists space-joined, dictionaries left out.
  Being template variables, they are part of what a step was built from: changing one reruns the
  steps that see it.
- **Kind.** The default's kind — `bool`, `int`, `float`, `str`, `list` or `dict` — is the
  option's: `-o` converts its text to it (`true/false/yes/no/1/0` for a boolean), and a manifest
  assigning another kind is an error (an integer where a number is expected, a tuple where a list
  is, are fine). A default of `None` says nothing about the kind: pass `kind=str` (or a tuple of
  kinds) to `option()`. A dictionary cannot be set with `-o`.
- **Choices.** With `choices=`, any other value is an error, from `-o` or from a manifest.
- **First thing.** `project()` comes before the manifest loads other manifests, declares blocks
  or reads `config.proj`, since all of them belong to the project, and once per manifest.

An option that does not exist, a value that does not convert to the option's kind and a value
outside its choices all stop *bake* before anything runs, with a message that says what the
option takes:

```
[bake] ERROR    Option '-o width=12': config.proj.width takes one of 8, 16, not 12. config.proj.width: Data width in bits.
[bake] ERROR    Option '-o simulator=x': project demo has no option 'simulator' (did you mean vrf.simulator?). Its options: fast, tags, width (`bake --list-options` describes them).
```

`bake --list-options` lists the project's options, then every section with its attributes:
their values, where the values come from (a manifest, `-o`, `load()` or the command line's
flags), the kinds and values they take and their descriptions.

### Projects that load projects

A project can load another: a library of blocks with options of its own, say, that also runs on
its own. A manifest belongs to the project of the manifest that loads it, until one calls
`project()`: that manifest starts a project of its own, for itself and for the manifests it
loads.

```python
# ip/manifest: the same whether ip runs on its own or is loaded
project("ip", tech=option("lf11", "Technology of the cells", choices=["lf11", "tsmc65"]))
if config.proj.tech == "lf11":
    ...

# the manifest of the project that loads it
project("chip", width=option(8, "Data width in bits"))
load("ip", tech="lf11")
```

- **Each project has its own options.** `config.proj` in `ip`'s manifests is `ip`'s options,
  never `chip`'s, and the flows of `ip`'s blocks see `ip`'s as `$BAKE_PROJ_*`.
- **Who sets them.** The command line sets the options of the top project, the project of the
  manifest *bake* runs. `load()` sets those of the project it loads, with keyword arguments; the
  others keep their defaults. For the command line to choose one of `ip`'s options, give `chip` an
  option of its own and pass it on: `load("ip", tech=config.proj.tech)`. Run on its own, `ip` is
  the top project, and `-o tech=tsmc65` sets its option.
- **One project per manifest.** *bake* executes a manifest once: a project loaded twice must be
  given the same options, and a manifest without `project()` must be loaded by one project only,
  since its blocks belong to the project that loads it.
- **Sections are shared.** `config.bake`, `config.vrf` and the other sections are the same for
  every project: a loaded project that sets one sets it for all of them.

`bake` lists the blocks of the top project and counts the others'; `bake --all` lists every
project's (see [Command-Line Interface](cli.md)).

## When an override takes effect

An override of a section's attribute holds from the moment the attribute exists. *bake* reads
the `-o` options before any manifest runs and applies each one as soon as its section is
registered: the sections of `bake` and of the built-in steps exist before the project's
manifests run, and the section of a step the project loads exists once its manifest registers
it. From then on:

- every manifest reads the command line's value, so a manifest can decide on it, e.g. with
  `if config.vrf.simulator == "xcelium":`;
- a manifest assigning the attribute keeps the command line's value: the command line wins, as
  the final value of a run always has. A manifest that derives a value from the attribute, say
  `config.bake.output_dir = os.path.join(config.bake.output_dir, "fast")`, does not apply
  either: the command line's value is the one the run uses.

Two kinds of attribute keep the old timing:

- items of a **list** attribute (`-o vrf.options=-a`) are appended once every manifest has
  loaded, after the manifests' own items, so their order does not change; a manifest reading
  the list while it loads does not see them;
- **`config.user`** attributes, which have no schema to check against, are set once every
  manifest has loaded, and only if a manifest assigned them (deprecated, see below).

A **dictionary** attribute (`flow_options`, ...) cannot be set with `-o`: set its keys in a
manifest. An override of a section or attribute that never appears, a value that does not
convert to the attribute's kind and a value outside its choices all stop *bake* before
anything runs, as for the project's options:

```
[bake] ERROR    Option '-o vrf.simulater=x': config.vrf has no attribute 'simulater' (did you mean 'simulator'?). Its attributes: ...
```

## Configuration Sections

### `config.bake`
Global *bake* settings.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `tpl_dict` | `{}` | Extra template variables injected into all `.tpl` files. Keys must start with `BAKE_` and contain only uppercase letters, digits, and underscores. Example: `config.bake.tpl_dict["BAKE_PDK_DIR"] = "/opt/pdk/sky130A"`. |
| `default_libs` | `[]` | Library names (`lib()`) for every block that declares no `libs=`. A project usually implements everything in one set of libraries: set it once here and leave `libs=` off the blocks; a block with its own `libs=[...]` uses exactly those (to add to the defaults, write `libs=[*config.bake.default_libs, "io_cells"]`). `-o bake.default_libs=name` appends for one run. |
| `file_copy_method` | `"copy"` | How flow skeleton files are placed in the work directory. `"copy"` duplicates files; `"symlink"` creates symbolic links (useful for shared, read-only flow installations). |
| `output_dir` | `None` | Override the root output directory for all steps. When unset, each step writes results relative to the manifest directory. |
| `process_tracking` | `"auto"` | How *bake* knows the processes a step starts, so that an interrupt reaches all of them and none outlives the step: `"auto"`, `"cgroup"`, `"subreaper"` or `"group"`; see [Interrupting bake](cli.md#interrupting-bake). |
| `kill_grace` | `10` | Seconds a process left by a step's script has, after `SIGTERM`, before `SIGKILL`. |

### `config.vrf`
Settings for the verification (simulation) step.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `simulator` | `""` | Simulator to use. Overrides `default_sim` from the test. Recognized values depend on the flow; the built-in flow supports `icarus`, `xcelium`, `ius`, `vcs`, `questa`, `verilator`. |
| `flow` | `None` | Name of the flow to use. When empty, the built-in simulation flow (`builtin_vrf_flow`) is used. Set to a custom flow name to replace the default. |
| `options` | `[]` | Extra command-line options forwarded to the simulator invocation (available as `$BAKE_RUN_OPTIONS` in `.tpl` files). |
| `runtime_options` | `[]` | Extra options for running the simulation only, e.g. plusargs, after the test's `vrf_runtime_options` (available as `$BAKE_SIM_RUNTIME_OPTIONS`). Unlike `options`, they do not change what is built; see [Building once for many tests](manifest_verif_model.md#building-once-for-many-tests). |
| `defines` | `[]` | Additional Verilog preprocessor defines passed to the simulator (appended to defines from the test). |
| `delays` | `""` | Delay corner for SDF back-annotation in gate-level simulation, `"typ"`, `"min"` or `"max"` (available as `$BAKE_SIM_DELAY_CORNER`; empty means `"typ"`). |
| `seed` | `""` | Simulation seed, passed to the simulator in its own form; empty picks a random one. The seed used is always logged (see [Seeds](manifest_verif_model.md#seeds)). |
| `run_dir` | `""` | The directory the test runs in, instead of `work/<block>/<recipe>/<test>`; the simulation builds the tests share stay in `work/<block>/<recipe>/_build`. A relative path is relative to the directory *bake* is started in. The runs of the [regression](manifest_verif_model.md#regressions) step have `.`, the directory each starts in. |
| `flow_options` | `{}` | Flow options, exposed to the flow's templates as `$BAKE_FLOW_OPT_<NAME>`; see [Custom Flows](custom_flows.md#flow-specific-options). |
| `tpl_dict` | `{}` | Extra template variables injected into `vrf`-step `.tpl` files only. Same key constraints as `config.bake.tpl_dict`. |

### `config.regression`
Settings for the [regression](manifest_verif_model.md#regressions) step.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `flow` | `None` | Name of the flow to use. When empty, the built-in flow (`builtin_regression_flow`) runs the regression on this machine; a project's own flow runs it on another engine (see [Writing a Regression Flow](custom_flows.md#writing-a-regression-flow)). |
| `flow_options` | `{}` | Flow options, exposed to the flow's templates as `$BAKE_FLOW_OPT_<NAME>`: `jobs` and `timeout` for the built-in flow (see [Regressions](manifest_verif_model.md#regressions)). |
| `tpl_dict` | `{}` | Extra template variables injected into `regression`-step `.tpl` files only. Same key constraints as `config.bake.tpl_dict`. |

### `config.sweep`
Settings for the [sweep](manifest_design_model.md#sweeps) step.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `flow` | `None` | Name of the flow to use. When empty, the built-in flow (`builtin_sweep_flow`) runs the sweep on this machine and reports it; a project's own flow runs it on another engine (see [Writing a Sweep Flow](custom_flows.md#writing-a-sweep-flow)). |
| `flow_options` | `{}` | Flow options, exposed to the flow's templates as `$BAKE_FLOW_OPT_<NAME>`: `jobs` and `timeout` for the built-in flow (see [Sweeps](manifest_design_model.md#sweeps)). |
| `tpl_dict` | `{}` | Extra template variables injected into `sweep`-step `.tpl` files only. Same key constraints as `config.bake.tpl_dict`. |

### `config.impl`
Settings for the implementation (synthesis and place-and-route) step.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `flow` | `""` | Name of the implementation flow to use. Must be set to a registered flow name before running the `impl` step. |
| `options` | `[]` | Extra options forwarded to the implementation tool. |
| `flow_options` | `{}` | Flow options, exposed to the flow's templates as `$BAKE_FLOW_OPT_<NAME>`; see [Custom Flows](custom_flows.md#flow-specific-options) and the table below for the built-in flow. |
| `ldb_dir | `""` | Path to the Liberty DB directory used by the implementation tool (flow-specific). |
| `tpl_dict` | `{}` | Extra template variables injected into `impl`-step `.tpl` files only. |

The built-in `yosys-openroad` flow takes these options (`config.impl.flow_options`). The
first group has technology-neutral defaults; the second is technology-specific and empty by
default — a PDK manifest provides them, as `example/pdk/sky130/manifest` does for sky130:

| Option | Default | Description |
|--------|---------|-------------|
| `core_utilization` | `30` | Core utilisation in percent for `initialize_floorplan` |
| `aspect_ratio` | `1.0` | Core aspect ratio |
| `core_margin` | `2` | Distance between core and die boundary, in microns |
| `place_density` | `0.6` | Target density for global placement |
| `macro_halo` | `"2 2"` | Space kept free around hard macros, in microns (x y) |
| `macro_channel` | `"4 4"` | Space kept between hard macros, in microns (x y) |
| `site` | — | Placement site from the technology LEF (sky130: `unithd`) |
| `pin_hor_layers`, `pin_ver_layers` | — | Metal layers for horizontal and vertical I/O pins (sky130: `met3`, `met2`) |
| `cts_buffers` | — | Clock buffer cell(s) for clock tree synthesis (sky130: `sky130_fd_sc_hd__clkbuf_4`) |
| `tie_cells` | `{"HI": "", "LO": ""}` | Tie-high and tie-low cells as `(cell, output pin)` (sky130: `{"HI": ("sky130_fd_sc_hd__conb_1", "HI"), "LO": ("sky130_fd_sc_hd__conb_1", "LO")}`); without them constants stay as plain assignments |
| `signal_layer`, `clock_layer` | — | Layers for wire RC estimation (`set_wire_rc`); when set, the SDF includes estimated interconnect delays |

Clock tree synthesis needs a clock: declare an SDC with `create_clock` in the block's
`sdc_files`. Without one the flow warns and skips CTS.

When the libraries provide LEF, the flow also writes the block's abstracts — `<top>.lef` and
`<top>_<corner>.lib` for every corner the libraries have Liberty for — and publishes them on
the `LibData` it produces (`layout_info`, `liberty_files`), so a block that includes this one after `impl`
integrates it as a hard macro. They are expected outputs: a run that does not produce them fails. Implemented sub-blocks
reach the flow through the `$BAKE_MACRO_*` variables below.

### `config.tmr`
Settings for the triplication (TMR) step.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `flow` | `""` | Name of the TMR flow to use. When empty, the built-in TMR flow (`builtin_tmr_flow`) is used. |
| `options` | `[]` | Extra command-line options forwarded to the triplication tool (e.g. *tmrg*). |
| `flow_options` | `{}` | Flow options, exposed to the flow's templates as `$BAKE_FLOW_OPT_<NAME>`; see [Custom Flows](custom_flows.md#flow-specific-options). |
| `cell_lib_dirs` | `[]` | Path prefixes of standard-cell Verilog libraries. Library files under one of these are reduced to their port declarations before being handed to *tmrg*, which cannot digest full behavioural cell models. |
| `ff_cell_patterns` | `[]` | Regular expressions matched against cell module names. Matching cells are flip-flops: they are annotated with `seu_reset_pin` / `seu_set_pin` so *tmrg* can inject SEUs on them. |
| `skip_cell_patterns` | `[]` | Regular expressions for cell modules to drop from the simplified library entirely. |
| `seu_reset_pin` / `seu_set_pin` | `""` | Names of the asynchronous reset and set pins of the flip-flop cells (technology-specific). |

The four cell-library attributes are empty by default; set them for your technology, for example:

```python
config.tmr.cell_lib_dirs    = ["/opt/pdk/mytech/verilog"]
config.tmr.ff_cell_patterns = [r"^DFF", r"^SDFF"]
config.tmr.seu_reset_pin    = "RN"
config.tmr.seu_set_pin      = "SN"
```

### `config.user`
A free-form section for values a project shares between its manifests and its own steps. There
is no fixed schema — you may add any attribute you like and read it back from within manifest
code or from custom step implementations:

```python
config.user.my_project_name = "sensor_readout"
config.user.pdk_root = "/opt/pdk/sky130A"
```

Each manifest runs in a namespace of its own, so `config` is the only object they share: a value
one manifest computes and another reads belongs here. A setting meant to be chosen from the
command line is a [project option](#project-options), which documents it, checks it and lets
the manifests see the command line's value. `-o user.<attribute>=value` still sets an attribute
a manifest assigned, but is deprecated and will stop working in a future major release.

## Template Variables

When *bake* processes `.tpl` files in a flow directory, it substitutes tokens of the form
`$BAKE_XYZ` and `${BAKE_XYZ}`. All template variable names must be uppercase and start with the
`BAKE_` prefix; any other `$` is left alone (see [Template Expansion](custom_flows.md#template-expansion)).
The same variables are written to `bake_vars.json` in the work directory, with list values kept
as lists, for scripts that prefer to read them (see
[`bake_vars.json`](custom_flows.md#reading-the-variables-from-a-script-bake_varsjson)). In the
tables below, "list" values are space-joined in `.tpl` files.

### Built-in variables (all steps)

Provided by the `Step` base class, so custom steps get them without overriding
`build_tpl_dict()`:

| Variable | Description |
|----------|-------------|
| `$BAKE_TOP` | Top-level module name of the current block |
| `$BAKE_BLOCK` | Name of the current block |
| `$BAKE_RECIPE` | Hyphen-separated recipe executed so far (e.g. `tmr-impl`) |
| `$BAKE_INTERACTIVE` | `1` when *bake* is invoked with `-i`, `0` otherwise |
| `$BAKE_VERBOSITY` | Number of `-v` flags given |
| `$BAKE_FLOW_OPT_<NAME>` | One per flow option: the flow's `tpl_defaults` overridden by `config.<step>.flow_options` |
| `$BAKE_PROJ_<OPTION>` | One per option of the block's project, but for dictionaries (see [Project options](#project-options)) |

### Built-in variables (vrf step)

| Variable | Description |
|----------|-------------|
| `$BAKE_SIM_TOP` | Verification top-level entity name |
| `$BAKE_SIM_FILES` | Space-separated list of all simulation source files |
| `$BAKE_SIM_SIMULATOR` | Active simulator name |
| `$BAKE_SIM_FRAMEWORK` | Verification framework (`""`, `"uvm"`, `"cocotb"`) |
| `$BAKE_SIM_FRAMEWORK_TOP` | Framework top entity (UVM test name / cocotb module) |
| `$BAKE_SIM_DEFINES` | Space-separated preprocessor defines for this run |
| `$BAKE_SIM_DELAY_CORNER` | Delay corner for SDF back-annotation |
| `$BAKE_SIM_SDF_FILES` | SDF files produced by an `impl` step earlier in the recipe, or brought in by an implemented include |
| `$BAKE_SIM_OPTIONS` | Simulator-specific options from `vrf_options` |
| `$BAKE_RUN_OPTIONS` | Extra options from `config.vrf.options` |
| `$BAKE_SIM_RUNTIME_OPTIONS` | Options for running the simulation only: `vrf_runtime_options` for the simulator, then `config.vrf.runtime_options` |
| `$BAKE_SIM_BUILD_DIR` | Directory shared by the tests of the block/recipe (`work/<block>/<recipe>/_build`), where a flow can keep builds several tests use; `-c`/`-r` remove it |
| `$BAKE_SIM_SEED` | `config.vrf.seed`; empty means the flow picks a random seed |
| `$BAKE_SIM_PASS_REGEX`, `$BAKE_SIM_FAIL_REGEX` | The test's pass/fail criteria (`vrf_pass_regex`, `vrf_fail_regex`) |

| `$BAKE_DESIGN_VERILOG_FILES` | RTL and netlist files of the design under test |
| `$BAKE_LIB_VERILOG_FILES` | Simulation models of the cell libraries (`lib()` netlists) |
| `$BAKE_INCLUDE_DIRS` | Include directories from the block, the test and the libraries |

### Built-in variables (regression step)

| Variable | Description |
|----------|-------------|
| `$BAKE_REGRESSION_RUNS` | One entry per run of the regression: `block`, `test`, `recipe`, `run` (numbered from 1 within its test), `name` (`<block>/<test>/<run>`, unique in the regression), `seed` (`null`: *bake* draws one), `options` (the run's `-o` overrides: its seed, the regression's options, then the command line's) and `command`, the run ready to start in a directory of its own (the *bake* invocation of the test with `options` and `vrf.run_dir=.`). A list of objects: read it from `bake_vars.json`. See [Writing a Regression Flow](custom_flows.md#writing-a-regression-flow). |

### Built-in variables (sweep step)

| Variable | Description |
|----------|-------------|
| `$BAKE_SWEEP_RUNS` | One entry per variant: `name`, `block`, `recipe`, `options` (the run's `-o` overrides: the sweep's, the variant's, then the command line's), `variant_options` (the variant's own) and `command`, the run ready to start in a directory of its own (the *bake* invocation of the recipe with `options` and `bake.output_dir=.`). A list of objects: read it from `bake_vars.json`. See [Writing a Sweep Flow](custom_flows.md#writing-a-sweep-flow). |
| `$BAKE_SWEEP_DESC` | The sweep's `desc`: the question it answers |
| `$BAKE_SWEEP_OPTIONS` | The sweep's `options`, common to every variant |
| `$BAKE_SWEEP_PROJECT` | The project's manifest directory |

### Built-in variables (impl step)

| Variable | Description |
|----------|-------------|
| `$BAKE_DESIGN_VERILOG_FILES` | RTL files to synthesise |
| `$BAKE_INCLUDE_DIRS` | RTL include directories |
| `$BAKE_INCLUDE_FLAGS` | The same directories as `-I<dir>` flags |
| `$BAKE_LIB_LIBERTY_FILES_<CORNER>` | Liberty files of the block's libraries for each corner the flow declares (`TT`, `FF`, `SS` in the built-in flow) |
| `$BAKE_LIB_SI_FILES_<CORNER>` | Signal-integrity files per corner |
| `$BAKE_LIB_PHYSICAL` | LEF files (`layout_info` of the libraries) |
| `$BAKE_MACRO_PHYSICAL` | LEF files of hard macros: implemented sub-blocks included after `impl`, and included `macro()`s |
| `$BAKE_MACRO_LIBERTY_FILES_<CORNER>` | Liberty files of the hard macros per corner |
| `$BAKE_MACRO_NETLIST_FILES` | Netlists of the hard macros (passed on to simulation, not implemented again) |
| `$BAKE_SDC_FILES` | Constraint files declared on the block (`sdc_files`) |
| `$BAKE_RUN_OPTIONS` | Extra options from `config.impl.options` |
| `$BAKE_LDB_DIR` | `config.impl.ldb_dir`, or `<workdir>/ldbs` |

### Built-in variables (tmr step)

| Variable | Description |
|----------|-------------|
| `$BAKE_DESIGN_VERILOG_FILES` | RTL files to triplicate |
| `$BAKE_LIB_VERILOG_FILES` | Cell-library models (reduced to port declarations when under `config.tmr.cell_lib_dirs`) |
| `$BAKE_INCLUDE_DIRS` | Include directories |
| `$BAKE_TMR_OUTPUT_DIR` | Where tmrg writes the triplicated RTL |
| `$BAKE_RUN_OPTIONS` | Extra options from `config.tmr.options` |
| `$BAKE_TMR_CELL_LIB_DIRS`, `$BAKE_TMR_FF_CELL_PATTERNS`, `$BAKE_TMR_SKIP_CELL_PATTERNS`, `$BAKE_TMR_SEU_RESET_PIN`, `$BAKE_TMR_SEU_SET_PIN` | The corresponding `config.tmr` attributes, space-joined |

The `.tpl` files in a flow's directory are the reference for what that flow actually reads.

### Adding custom template variables

Add extra variables via `config.bake.tpl_dict` (available in all steps) or the step-specific
`tpl_dict` (e.g. `config.vrf.tpl_dict`):

```python
config.bake.tpl_dict["BAKE_PDK_VERSION"] = "1.2.3"
config.vrf.tpl_dict["BAKE_REGRESSION_TAG"] = "nightly"
config.vrf.tpl_dict["BAKE_EXTRA_FILES"] = ["a.v", "b.v"]   # "a.v b.v" in .tpl, a list in bake_vars.json
```

Custom steps can expose additional variables by overriding `build_tpl_dict()`. See
[Custom Steps](custom_steps.md) for details.
