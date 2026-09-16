
# Release Information

*bake* loosely follows [semantic versioning](https://semver.org/) conventions. Since it lives on
the boundary between a user tool and a library with a user-facing API, there are minor deviations
from this model.

The following conventions are followed for the MAJOR.MINOR.PATCH version number.

1. The MAJOR version is incremented when incompatible API changes are made. API here refers to
   changes in the manifest format (e.g. the definition of targets, flows, etc.) and any breaking
   changes in the templating process (e.g. change of the contents or order of elements in template
   variables). For every major version change, used flows MUST be carefully re-evaluated for
   correct functioning. While some backwards-compatibility testing MAY be performed, no guarantees
   are provided for correct operation with older flow versions. User-defined flows may stop working
   and will need to be re-qualified.
2. The MINOR version is incremented when backwards-compatible API changes or new features are
   added. This also applies to the addition of new flows, but not the removal of existing flows.
   For updates to flows delivered with *bake*, whether MINOR or PATCH is incremented depends on
   the version increment of the particular sub-flow. When multiple flows are updated, the most
   significant increment is propagated. Older flow versions (up to the last MAJOR release) are
   expected to continue working without regressions, including flows maintained downstream of
   *bake*, though caution is nonetheless advised.
3. The PATCH version is incremented when backwards-compatible bug fixes are made, including bug
   fixes in any of the flows delivered with *bake*.

Release notes are provided for each release, covering changes in a) the *bake* core and b) each
affected flow. Instructions are provided when flows need to be updated, with references to
downstream issues for context.

Flows shipped with *bake* but maintained in external repositories follow the tags used in those
repositories. For each *bake* release, each such flow must tag a commit `vX.Y.Z`. This tag is
either used directly, or a separate `vX.Y.Z-bake` tag marks a commit adding optional
compatibility patches rebased for each new release.

## Changelog

### v1.0.0

First public release of **bake**. bake is a modified derivative of
[tmake](https://gitlab.cern.ch/tmake/tmake) (Copyright 2025 CERN, Apache-2.0), forked at tmake
commit `5c13314a` (2023-05-15); see `NOTICE`.

Relative to tmake at the fork point, **all manifests and flow skeletons must be updated.**

**Vocabulary.** What tmake calls a *rule* is a **step** (`vrf`, `impl`, `tmr`, `dummy`); a
hyphen-joined series of steps is a **recipe** (`impl`, `dummy-impl`, `tmr-impl-vrf`). A
*target* is a **block**.

**Manifest API**

- `from tmake import ...` becomes `from bake import ...`; the command is `bake`; the PyPI
  distribution is `bake-eda`.
- `use()` is removed. Built-in steps and their flows are loaded automatically on every
  invocation. Remove all `use("sim")`, `use("tmrg")`, and similar calls.
- `target()` is renamed to `block()`. `target` is kept as an alias, but new manifests should
  use `block()`.
- `block(includes=...)` accepts either a list (short form, equivalent to `{"name": "rtl"}`)
  or a dict mapping block names to recipe strings (`{"sub_block": "impl"}`), so a block can
  depend on the post-step output of another block. Such dependencies are resolved when a
  recipe runs and built on demand; `bake` lists their state and `-n` reports a plan without
  running anything. Each step takes what it needs from an implemented sub-block: `vrf` its
  netlist and SDF, `impl` its abstracts (hard macro), passing the netlist on.
- Unknown arguments to `block()`, `test()`, `env()`, `lib()` and `flow()` are errors.
- `flow(dir=...)` is resolved relative to the manifest registering the flow and must exist.
- `flow(tpl_defaults=...)` declares flow options; `config.<step>.flow_options` overrides them
  and both reach templates as `$BAKE_FLOW_OPT_<NAME>`.
- Custom steps subclass `Step` (in `bake.step`) in a manifest of their own that the project
  `load()`s, laid out like the built-in steps; pipeline state is carried by `StepData`.

**Configuration**

- `manifest.ini` is removed. Configuration is set on the `config` object, always available in
  manifest scope: `config.vrf.simulator = "xcelium"`, `config.bake.output_dir = "..."`.
- Command-line overrides use `-o section.attribute=value`
  (e.g. `bake counter vrf -o vrf.simulator=xcelium`). The `-s` / `--sim` flag is gone.
- `--populate-flow` (`-p`) populates flow directories without running anything.

**Templates and layout**

- Template variables are prefixed `BAKE_` instead of `TMAKE_`; `$TMAKE_RULE` becomes
  `$BAKE_RECIPE` and `$TMAKE_TARGET` becomes `$BAKE_BLOCK`.
- Flow skeletons live in `flow/<block>/<recipe>/`, work output in `work/<block>/<recipe>/`
  with results under `output/`.
- The completion cache moved to `~/.cache/bake/`.

**Built-in flows**

- The `impl` step's built-in flow is `yosys-openroad`: Yosys synthesis and OpenROAD
  place-and-route on whatever standard-cell libraries the manifest registers with `lib()`
  (Liberty per TT/FF/SS corner, LEF, simulation models). bake ships no PDK-specific code and
  no foundry flow kits; registering a PDK is the job of a manifest, and a block that runs
  `impl` names its libraries in `libs=[...]`. `example/pdk/sky130/manifest` is the reference,
  locating an [open_pdks](https://github.com/RTimothyEdwards/open_pdks) build of the SkyWater
  sky130 PDK through `PDK_ROOT` (optionally `PDK`, default `sky130A`); examples 03 and 05 and
  the test suite `load()` it, and `test/pdk/fetch_sky130.sh` fetches it with `ciel`.
- That flow is verified end to end on sky130 (`example/03`, `test_sky130_impl_run`).
  Synthesis maps fully to the library; P&R defines one STA corner per Liberty corner, reads
  the block's `sdc_files`, synthesises the clock tree when a clock is defined, routes, and
  writes a netlist, a DEF and one SDF per corner. The technology-specific settings (site, pin
  layers, clock buffer, tie cells, RC layers) are flow options a PDK manifest provides.
- It writes the block's abstracts (LEF, Liberty per corner) and integrates included
  implemented blocks as hard macros from theirs (`example/05`).
- `impl-vrf` hands the SDF to the simulation, which annotates it (Icarus gets `-gspecify`
  automatically).
- The `tmr` step's cell-library simplification is configured through `config.tmr`
  (`cell_lib_dirs`, `ff_cell_patterns`, `skip_cell_patterns`, `seu_reset_pin`, `seu_set_pin`)
  instead of being hard-wired to one foundry's cell naming.

**Architecture**

- `StepData` is the single source of truth for pipeline state. Steps read `self.data` and
  write `self.output_data`; accessing `context` registries at step runtime is not permitted.
- The built-in steps ship inside the package, so a non-editable install
  (`pip install bake-eda`) works.
- The examples are built on open-source tools only; see `example/README.md`.
