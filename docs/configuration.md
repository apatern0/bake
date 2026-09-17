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

Settings take effect before any step is executed. Configuration can also be overridden at the
command line with the `-o` flag:

```
bake counter vrf -o vrf.simulator=xcelium
```

`-o` is applied after every manifest has loaded, so the command line wins over the manifest. The
manifest code itself runs before that and sees the manifest's own values: do not branch on
`config` inside a manifest expecting to see an override. Put anything that depends on a setting
in the flow (through the template variables) or in a step's `build_tpl_dict()`, which both see
the final value.

## Configuration Sections

### `config.bake`
Global *bake* settings.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `tpl_dict` | `{}` | Extra template variables injected into all `.tpl` files. Keys must start with `BAKE_` and contain only uppercase letters, digits, and underscores. Example: `config.bake.tpl_dict["BAKE_PDK_DIR"] = "/opt/pdk/sky130A"`. |
| `file_copy_method` | `"copy"` | How flow skeleton files are placed in the work directory. `"copy"` duplicates files; `"symlink"` creates symbolic links (useful for shared, read-only flow installations). |
| `output_dir` | `None` | Override the root output directory for all steps. When unset, each step writes results relative to the manifest directory. |

### `config.vrf`
Settings for the verification (simulation) step.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `simulator` | `""` | Simulator to use. Overrides `default_sim` from the test. Recognized values depend on the flow; the built-in flow supports `icarus`, `xcelium`, `ius`, `vcs`, `questa`, `verilator`. |
| `flow` | `None` | Name of the flow to use. When empty, the built-in simulation flow (`builtin_vrf_flow`) is used. Set to a custom flow name to replace the default. |
| `options` | `[]` | Extra command-line options forwarded to the simulator invocation (available as `$BAKE_RUN_OPTIONS` in `.tpl` files). |
| `defines` | `[]` | Additional Verilog preprocessor defines passed to the simulator (appended to defines from the test). |
| `delays` | `""` | Delay corner for SDF back-annotation in gate-level simulation, `"typ"`, `"min"` or `"max"` (available as `$BAKE_SIM_DELAY_CORNER`; empty means `"typ"`). |
| `flow_options` | `{}` | Flow options, exposed to the flow's templates as `$BAKE_FLOW_OPT_<NAME>`; see [Custom Flows](custom_flows.md#flow-specific-options). |
| `tpl_dict` | `{}` | Extra template variables injected into `vrf`-step `.tpl` files only. Same key constraints as `config.bake.tpl_dict`. |

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
`StepData` (`layout_info`, `liberty_files`), so a block that includes this one after `impl`
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
A free-form section for user-defined attributes. There is no fixed schema — you may add any
attribute you like and read it back from within manifest code or from custom step implementations:

```python
config.user.my_project_name = "sensor_readout"
config.user.pdk_root = "/opt/pdk/sky130A"
```

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

| `$BAKE_DESIGN_VERILOG_FILES` | RTL and netlist files of the design under test |
| `$BAKE_LIB_VERILOG_FILES` | Simulation models of the cell libraries (`lib()` netlists) |
| `$BAKE_INCLUDE_DIRS` | Include directories from the block, the test and the libraries |

### Built-in variables (impl step)

| Variable | Description |
|----------|-------------|
| `$BAKE_DESIGN_VERILOG_FILES` | RTL files to synthesise |
| `$BAKE_INCLUDE_DIRS` | RTL include directories |
| `$BAKE_INCLUDE_FLAGS` | The same directories as `-I<dir>` flags |
| `$BAKE_LIB_LIBERTY_FILES_<CORNER>` | Liberty files of the block's libraries for each corner the flow declares (`TT`, `FF`, `SS` in the built-in flow) |
| `$BAKE_LIB_SI_FILES_<CORNER>` | Signal-integrity files per corner |
| `$BAKE_LIB_PHYSICAL` | LEF files (`layout_info` of the libraries) |
| `$BAKE_MACRO_PHYSICAL` | LEF files of hard macros: implemented sub-blocks included after `impl`, or `layout_info` declared on the block |
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
