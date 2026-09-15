# Configuration

*bake* is configured directly in the `manifest` file using the `config` object, which is always
available in manifest scope without any import. Configuration is plain Python — sections are
attributes, and settings are attribute assignments:

```python
config.vrf.simulator = "xcelium"
config.bake.file_copy_method = "symlink"
```

Settings take effect before any step is executed. Configuration can also be overridden at the
command line with the `-o` flag:

```
bake counter vrf -o vrf.simulator=xcelium
```

## Configuration Sections

### `config.bake`
Global *bake* settings.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `tpl_dict` | `{}` | Extra template variables injected into all `.tpl` files. Keys must start with `BAKE_` and contain only uppercase letters, digits, and underscores. Example: `config.bake.tpl_dict["BAKE_PDK_DIR"] = "/opt/pdk/sky130A"`. |
| `vrf_simulator` | `"auto"` | Fallback simulator when no `default_sim` is set in the test. Use the simulator short name (e.g. `"icarus"`, `"xcelium"`). |
| `file_copy_method` | `"copy"` | How flow skeleton files are placed in the work directory. `"copy"` duplicates files; `"symlink"` creates symbolic links (useful for shared, read-only flow installations). |
| `steps_dirs` | `[]` | List of additional directories to scan for custom step definitions. Equivalent to calling `add_steps_dir()` in the manifest. |
| `output_dir` | `None` | Override the root output directory for all steps. When unset, each step writes results relative to the manifest directory. |

### `config.vrf`
Settings for the verification (simulation) step.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `simulator` | `""` | Simulator to use. Overrides `default_sim` from the test. Recognized values depend on the flow; the built-in flow supports `icarus`, `xcelium`, `ius`, `vcs`, `questa`, `verilator`. |
| `flow` | `None` | Name of the flow to use. When empty, the built-in simulation flow (`builtin_vrf_flow`) is used. Set to a custom flow name to replace the default. |
| `options` | `[]` | Extra command-line options forwarded to the simulator invocation (available as `$BAKE_RUN_OPTIONS` in `.tpl` files). |
| `defines` | `[]` | Additional Verilog preprocessor defines passed to the simulator (appended to defines from the test). |
| `delays` | `[]` | Delay corner(s) to use for gate-level simulation (available as `$BAKE_SIM_DELAY_CORNER`). Defaults to `"typ"`. |
| `flow_options` | `{}` | Simulator-keyed dictionary of extra options, passed to the flow script. Format: `{"xcelium": ["-opt1"]}`. |
| `tpl_dict` | `{}` | Extra template variables injected into `vrf`-step `.tpl` files only. Same key constraints as `config.bake.tpl_dict`. |

### `config.impl`
Settings for the implementation (synthesis and place-and-route) step.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `flow` | `""` | Name of the implementation flow to use. Must be set to a registered flow name before running the `impl` step. |
| `options` | `[]` | Extra options forwarded to the implementation tool. |
| `flow_options` | `{}` | Tool-keyed dictionary of additional options forwarded to the flow script. |
| `ldb_dir` | `""` | Path to the Liberty DB directory used by the implementation tool (flow-specific). |
| `default_libs` | `[]` | Fallback list of library names used when the target block defines no `libs`. |
| `tpl_dict` | `{}` | Extra template variables injected into `impl`-step `.tpl` files only. |

### `config.tmr`
Settings for the triplication (TMR) step.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `flow` | `""` | Name of the TMR flow to use. When empty, the built-in TMR flow (`builtin_tmr_flow`) is used. |
| `options` | `[]` | Extra command-line options forwarded to the triplication tool (e.g. *tmrg*). |
| `flow_options` | `{}` | Tool-keyed dictionary of additional options forwarded to the flow script. |
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
`$BAKE_XYZ` using Python `string.Template`. All template variable names must be uppercase and
start with the `BAKE_` prefix.

### Built-in variables (all steps)

| Variable | Description |
|----------|-------------|
| `$BAKE_TOP` | Top-level module name of the current block |
| `$BAKE_BLOCK` | Name of the current block |
| `$BAKE_RECIPE` | Hyphen-separated recipe executed so far (e.g. `tmr-impl`) |

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
| `$BAKE_SIM_OPTIONS` | Simulator-specific options from `vrf_options` |
| `$BAKE_RUN_OPTIONS` | Extra options from `config.vrf.options` |
| `$BAKE_INTERACTIVE` | `"1"` when *bake* is invoked with `-i`, `"0"` otherwise |

The complete set of variables for a given flow is documented by the `.tpl` files in that flow's
directory.

### Adding custom template variables

Add extra variables via `config.bake.tpl_dict` (available in all steps) or the step-specific
`tpl_dict` (e.g. `config.vrf.tpl_dict`):

```python
config.bake.tpl_dict["BAKE_PDK_VERSION"] = "1.2.3"
config.vrf.tpl_dict["BAKE_REGRESSION_TAG"] = "nightly"
```

Custom steps can expose additional variables by overriding `build_tpl_dict()`. See
[Custom Steps](custom_steps.md) for details.

## Disabling the Completion Cache

*bake* maintains a completion cache at `~/.cache/bake/completion_cache.json` to speed up
tab-completion. This cache is updated on every invocation of *bake*. If the cache causes
problems (e.g. race conditions in regression setups), it can be disabled by setting the
environment variable:

```
export BAKE_NO_CACHE=1
```
