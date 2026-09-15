
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

### v4.0.0

First public release of **bake**. bake is a modified derivative of
[tmake](https://gitlab.cern.ch/tmake/tmake) (Copyright 2025 CERN, Apache-2.0), forked at tmake
commit `5c13314a` (2023-05-15); see `NOTICE`. Version numbers start at 4.0.0 so that they never
collide with tmake's own releases or with the internal iterations that preceded this one.

Relative to tmake at the fork point, **all manifests and flow skeletons must be updated:**

**Vocabulary.** What tmake calls a *rule* is a **step** (`vrf`, `impl`, `tmr`, `dummy`); a
hyphen-joined series of steps is a **recipe** (`impl`, `dummy-impl`, `tmr-impl-vrf`). A
*target* is a **block**.

**Manifest API:**
  * `from tmake import ...` becomes `from bake import ...`; the command is `bake`; the PyPI
    distribution is `bake-eda`.
  * `use()` is removed. Built-in steps and their flows are loaded automatically on every
    invocation. Remove all `use("sim")`, `use("tmrg")`, and similar calls.
  * `target()` is renamed to `block()`. `target` is kept as an alias, but new manifests should
    use `block()`.
  * `block(includes=...)` accepts either a list (short form, equivalent to `{"name": "rtl"}`)
    or a dict mapping block names to recipe strings (`{"sub_block": "impl"}`), so a block can
    depend on the post-step output of another block.
  * Custom steps subclass `Step` (in `bake.step`) and are registered with `add_steps_dir()`;
    pipeline state is carried by `StepData`.

**Configuration:**
  * `manifest.ini` is removed. Configuration is set on the `config` object, always available in
    manifest scope: `config.vrf.simulator = "xcelium"`, `config.bake.output_dir = "..."`.
  * Command-line overrides use `-o section.attribute=value`
    (e.g. `bake counter vrf -o vrf.simulator=xcelium`). The `-s` / `--sim` flag is gone.
  * `--populate-flow` (`-p`) populates flow directories without running anything.

**Templates and layout:**
  * Template variables are prefixed `BAKE_` instead of `TMAKE_`; `$TMAKE_RULE` becomes
    `$BAKE_RECIPE` and `$TMAKE_TARGET` becomes `$BAKE_BLOCK`.
  * Flow skeletons live in `flow/<block>/<recipe>/`, work output in `work/<block>/<recipe>/`
    with results under `output/`.
  * The completion cache lives in `~/.cache/bake/`; the kill switch is `BAKE_NO_CACHE`.

**Architecture:**
  * `StepData` is the single source of truth for pipeline state. Steps read `self.data` and
    write `self.output_data`; accessing `context` registries at step runtime is not permitted.
  * The built-in steps ship inside the package, so a non-editable install
    (`pip install bake-eda`) works.
  * The `impl` step targets the open-source SkyWater sky130 PDK with Yosys and OpenROAD and
    caches generated Liberty files under `~/.cache/bake/`. Foundry-specific flow kits are not
    shipped; provide them as custom flows.
  * The `tmr` step's cell-library simplification is configured through `config.tmr`
    (`cell_lib_dirs`, `ff_cell_patterns`, `skip_cell_patterns`, `seu_reset_pin`, `seu_set_pin`)
    instead of being hard-wired to one foundry's cell naming.
  * The examples are built on open-source tools only; see `example/README.md`.
