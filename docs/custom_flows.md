# Custom Flows

A *flow* is a directory of scripts and template files that implement a particular step. Built-in
flows are provided for the `vrf`, `impl`, and `tmr` steps and are loaded automatically. Custom
flows let you replace or extend any of these, or supply scripts for a custom step.

## What a Flow Contains

A flow directory typically contains:
- A main entry-point script (e.g. `run.py` or `run.sh`) — the file that *bake* executes.
- Template variants of scripts with a `.tpl` extension (e.g. `run.py.tpl`) — *bake* expands
  `$BAKE_XYZ` tokens in these files before executing.
- Any additional helper scripts, config files, or data needed by the flow.

On first invocation of a block/step combination, *bake* copies the entire flow directory into
a per-block `flow/` directory in the project. The user may then edit those files freely.
Subsequent invocations re-expand any `.tpl` files but do not overwrite non-template files.

## Registering a Flow

Register a flow by constructing a `FlowSpec` object in a manifest. The `flow()` function in the
public API is an alias for `FlowSpec`:

```python
from bake import flow

flow(
    name    = "my_sim_flow",
    desc    = "Wrapper around a custom simulator script",
    run_cmd = "run.sh",          # entry point inside the flow directory
    dir     = "flows/my_sim",    # path to the flow directory (relative to manifest)
    simulators = [
        ("icarus",  "Icarus Verilog"),
        ("xcelium", "Cadence Xcelium"),
    ],
)
```

`FlowSpec` fields:

| Field | Description |
|-------|-------------|
| `name` | Unique flow identifier. Used to select the flow from `config.<step>.flow`. |
| `desc` | Human-readable description (optional). |
| `dir` | Path to the flow directory. Defaults to `<manifest_dir>/flow` if omitted. |
| `run_cmd` | Entry-point script name inside the flow directory. Default: `"run.py"`. |
| `simulators` | List of `(name, description)` tuples declaring supported simulators. Used by the `vrf` step. |
| `corners` | List of `(name, description)` tuples declaring supported process corners. Used by the `impl` step. |
| `simulation_frameworks` | List of `(name, description)` tuples for supported verification frameworks. |
| `tpl_defaults` | Default values for the flow options the flow's scripts reference (see below). |

## Connecting a Flow to a Step

Each built-in step has a `default_flow` that it uses automatically. To replace the default flow
for a built-in step, set `config.<step>.flow` in the manifest:

```python
config.vrf.flow = "my_sim_flow"
```

For a custom step, set `default_flow` as a class attribute:

```python
class MyStep(Step):
    name         = "mystep"
    default_flow = "my_flow"
```

The user can always override the flow from the manifest:

```python
config.mystep.flow = "another_flow"
```

## Template Expansion

Any file in the flow directory with a `.tpl` extension is treated as a template. *bake* reads the
`.tpl` source, substitutes all `$BAKE_XYZ` and `${BAKE_XYZ}` tokens, and writes the result to a
file of the same name without the `.tpl` extension in the step work directory.

Only `$BAKE_...` tokens (upper case, digits and underscores) are placeholders. Every other `$` —
a Tcl or shell variable, `${x}`, `$1` — is copied as it is, so scripts need no escaping. `$$`
still yields a single `$`, for templates written against earlier versions. Use the braced form
when a placeholder is followed by a letter, digit or underscore: `${BAKE_TOP}_tb`. A `$BAKE_`
token nobody defines is an error naming the file and the variable.

See [Configuration](configuration.md) for the full list of built-in template variables.

## Full Example: Custom Simulation Flow

This example replaces the built-in `vrf` flow with a custom shell script wrapper that runs
Icarus Verilog and post-processes the output.

### Project layout

```
my_project/
├── manifest
├── rtl/
│   └── my_block.v
├── vrf/
│   └── my_test.v
└── flows/
    └── icarus_custom/
        ├── run.sh.tpl
        └── post_process.py
```

### `flows/icarus_custom/run.sh.tpl`

```bash
#!/bin/bash
set -e
mkdir -p output

# Compile
iverilog \
    -o output/sim.out \
    -DSIM $BAKE_SIM_DEFINES \
    $BAKE_SIM_FILES

# Simulate
vvp output/sim.out 2>&1 | tee output/sim.log

# Post-process
python3 "$(dirname "$0")/post_process.py" output/sim.log
```

The `.tpl` suffix is stripped after expansion — *bake* executes `run.sh` (not `run.sh.tpl`).

### `manifest`

```python
from bake import block, test, flow

# Register the custom flow
flow(
    name    = "icarus_custom_flow",
    desc    = "Custom Icarus Verilog flow with post-processing",
    run_cmd = "run.sh",
    dir     = "flows/icarus_custom",
    simulators = [("icarus", "Icarus Verilog")],
)

# Tell the vrf step to use this flow instead of the default
config.vrf.flow = "icarus_custom_flow"

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
$ bake my_block vrf
[bake] INFO     Populating flow directory for 'vrf' from '/path/to/my_sim_flow' → /path/to/project/flow/my_block/vrf/my_test
[bake] INFO     Running vrf on block my_block
...
```

The custom `run.sh` is copied to the block's `flow/` directory on first run and executed from the
step work directory on subsequent invocations.

## Flow-Specific Options

A flow's scripts often need knobs that are neither design data nor step configuration: a
utilisation target, the metal layers to place pins on, a linter's rule set. Each such option is
a template variable `$BAKE_FLOW_OPT_<NAME>`. The flow declares its defaults in `tpl_defaults`
and a project overrides them per step in `config.<step>.flow_options`; the name is upper-cased
for the template and list values are space-joined:

```python
# flow manifest
flow(
    name="my_pnr",
    run_cmd="run.sh",
    tpl_defaults={"core_utilization": 30, "pin_layers": ["met2", "met3"]},
)

# project manifest
config.impl.flow_options = {"core_utilization": 45}
```

```sh
# run.sh.tpl
openroad -exit pnr.tcl -util $BAKE_FLOW_OPT_CORE_UTILIZATION -pins "$BAKE_FLOW_OPT_PIN_LAYERS"
```

A dict option expands to one variable per key — `tie_cells={"HI": ("conb_1", "HI")}` gives
`$BAKE_FLOW_OPT_TIE_CELLS_HI` — and a project's dict merges into the flow's default dict key by
key, so keys the project leaves out keep their defaults.

An option that has neither a default nor a project value is undefined, and a template that
references it fails at expansion, so give every option the flow references a default.
Simulator-specific options for a test belong in the test's `vrf_options` (they reach the
built-in flow as `$BAKE_SIM_OPTIONS`), not in `flow_options`.

## Sharing Flows Across Projects

Flows can live in a shared location and be referenced by an absolute path or an environment
variable:

```python
import os

flow(
    name = "shared_sim_flow",
    dir  = os.environ["SHARED_FLOWS_DIR"] + "/sim_flow",
)
```

Setting `config.bake.file_copy_method = "symlink"` makes *bake* symlink the flow skeleton
instead of copying it, which is useful for read-only shared flow installations where the user
should always run the latest version without a local copy.

## Writing a Python Flow Script

For complex flows, a Python entry point has full access to the *bake* environment variables
injected via the template. A minimal `run.py.tpl` pattern:

```python
#!/usr/bin/env python3
import subprocess
import sys
import os

RTL_FILES = "$BAKE_SIM_FILES".split()
SIMULATOR  = "$BAKE_SIM_SIMULATOR"
DEFINES    = "$BAKE_SIM_DEFINES".split()

cmd = [SIMULATOR] + [f"+define+{d}" for d in DEFINES] + RTL_FILES
result = subprocess.run(cmd)
sys.exit(result.returncode)
```

All `$BAKE_XYZ` tokens are literal Python string values after template expansion — no subprocess
environment variable lookup is needed.
