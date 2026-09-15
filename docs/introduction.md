# Introduction
ASICs for radiation environments — space, high-energy physics, medical and nuclear instrumentation —
need radiation-hardened circuit implementations. *bake* was conceived as a tool to partially automate
the design flow of digital circuits utilizing triple-modular redundancy (TMR) as a means of radiation
hardening, and has grown into a general build system for RTL-to-GDS and verification flows.

## Scope, Motivation and Features
*bake* is intended to automate many aspects of the ASIC design process from RTL code to physical
implementation. It supports both unhardened and hardened designs, which facilitates evaluating the
penalties (power, area, speed, ...) associated with triplication. The triplication process itself
is delegated to an external tool (such as *tmrg*), which is fully integrated into the *bake*
workflow. Simulations are possible at every step of the design flow: using RTL code, triplicated
RTL code, post-synthesis and post-place-and-route netlists. Support for multiple simulators (from
open source tools for small simulations up to commercial simulators with UVM support) allows optimal
use of available resources (licenses, CPU), and makes *bake* well suited for automated regression
testing.

## Theory of Operation
*bake* is built on a small set of fundamental concepts that allow users to quickly simulate their
first designs while scaling smoothly to larger projects.

*bake* follows instructions provided in `manifest` files. These are plain Python files that
communicate both design intent (files, hierarchies, interactions between components, test cases)
and flow configuration (simulator selection, synthesis scripts, custom template variables). A
manifest calls functions such as `block()`, `test()`, `env()`, `lib()`, and `flow()` to register
design objects into the *bake* registry, and sets configuration via the `config` object that is
always available in manifest scope.

*bake* operates on user-provided target and recipe combinations. A target represents any
design component (from a sub-block to a full chip), while a recipe specifies which actions to
execute and in what order. Recipes such as `tmr`, `impl`, `vrf`, `tmr-impl`, `tmr-impl-vrf`
are parsed dynamically — no predefined list of valid chains is required.

![bake recipes](img/bake_recipes.svg)

*bake* performs timestamp-based dependency tracking, similar to GNU Make: whenever a step has
unmet dependencies, the required upstream steps are executed first. If a source file for a target
changes, only the affected downstream steps are re-executed. *bake* also tracks expected output
artifacts from each step and reports any step that fails to produce its required outputs.

On first invocation of a target/recipe pair, a `flow` directory is populated with a
skeleton of the flow scripts. This directory can be placed under version control, and the skeleton
files can be edited to customize any part of the flow. On subsequent invocations, *bake* reads
this directory and fills any template files (files with a `.tpl` extension). During templating,
special tokens of the form `$BAKE_XYZ` are substituted with values derived from the manifest.
Results are placed in an `output` directory corresponding to the target/step pair.

This approach guarantees that every part of the flow remains fully customizable (including
place-and-route scripts) while keeping design information (file names, include directories)
centralized in `manifest` files — where they can be shared between RTL development, implementation
and verification tasks.

## Step and Flow Discovery
*bake* discovers available steps automatically. Built-in steps (`vrf`, `impl`, `tmr`, `dummy`) are
located in the `bake/builtin/` directory of the package and are loaded on every invocation
without any action required from the user.

Additional step directories can be registered in manifests using `add_steps_dir()`, allowing
projects to define their own pipeline steps alongside the built-in ones:

```python
add_steps_dir("steps/")  # relative to the manifest file
```

Any `.py` file in the registered directory that defines a `Step` subclass is auto-discovered and
registered.

Flows are registered by constructing a `FlowSpec` object in any manifest file. Built-in flows (one
per built-in step) are registered automatically when the built-in manifests are loaded. Custom
flows are registered by calling `flow()` in a user manifest:

```python
flow(
    name="my_sim_flow",
    simulators=[("icarus", "Icarus Verilog"), ("xcelium", "Cadence Xcelium")],
    dir="flows/my_sim_flow",
)
```

Each step has a default flow it uses when no explicit override is configured. Users can override
the flow for any step via the `config` object:

```python
config.vrf.flow = "my_sim_flow"
```

See [Custom Steps](custom_steps.md) and [Custom Flows](custom_flows.md) for complete guides.
