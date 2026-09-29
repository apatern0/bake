
# Release Information

## Versioning

*bake* follows [Semantic Versioning 2.0.0](https://semver.org/). A version is MAJOR.MINOR.PATCH,
and what it promises is measured against *bake*'s public API:

- the manifest API: the functions a manifest calls (`block()`, `macro()`, `lib()`, `test()`,
  `env()`, `flow()`, `load()`, ...), their arguments, and the `config` sections and attributes;
- the Python API of custom steps: `Step`, `StepData` and its kinds, `DesignSpec`;
- what a flow receives: the `$BAKE_...` template variables and `bake_vars.json`, and the layout
  of `flow/` and `work/`;
- the command line;
- the built-in steps: their options, what they take and what they produce.

1. MAJOR is incremented for an incompatible change: an existing manifest, custom step or flow may
   have to change. The release notes say how.
2. MINOR is incremented for a backwards-compatible feature, a new step or flow option included.
3. PATCH is incremented for a backwards-compatible bug fix, in the built-in flows included.

The scripts of a built-in flow are not API. A copy made with `-p` and customised belongs to the
project; a change to the original is versioned by what it changes for projects running the flow
as shipped.

Flows shipped with *bake* but maintained in external repositories follow the tags used in those
repositories. For each *bake* release, each such flow must tag a commit `vX.Y.Z`. This tag is
either used directly, or a separate `vX.Y.Z-bake` tag marks a commit adding optional
compatibility patches rebased for each new release.

## How releases are made

Versions, tags and this changelog are made by
[release-please](https://github.com/googleapis/release-please) from the commit messages, which
follow [Conventional Commits](https://www.conventionalcommits.org/): a `fix:` makes a PATCH
release, a `feat:` a MINOR one, and a `!` after the type (`feat(manifest)!:`) or a
`BREAKING CHANGE:` footer a MAJOR one. release-please keeps a release pull request open on
`main` with the next version and its entry below; merging it tags `vX.Y.Z` and creates the GitHub
release.

Each commit's subject is its line in the changelog, and a `BREAKING CHANGE:` footer is quoted
under the breaking changes: it says what projects have to change.

## v2.0.0

**Breaking changes.** Manifests and custom steps may need these changes; the entries below say
more.

- `block()` no longer takes `netlist_files`, `netlist_incdirs`, `liberty_files`, `si_files` or
  `layout_info`: declare such a block with `macro()`.
- A custom step reading `rtl_files` or netlist fields should declare `consumes`; code
  constructing `StepData(rtl_files=...)` constructs `RtlData` or `LibData`.
- A `test()` defined twice for the same block, and an attribute a builtin step's config does
  not have, are errors.
- Python 3.9 is no longer supported.

**Data kinds.** What flows through a recipe now has a kind, and steps say which kinds they take.

- `StepData` is the base of the kinds `RtlData` (a design in RTL) and `LibData` (an implemented
  block: netlist and abstracts). An implemented sub-block included into RTL is kept whole in
  `RtlData.macros` instead of being flattened into the parent's netlist fields.
- Steps declare `consumes` (the kinds they take; any by default) and `produces` (the kind they
  give; the one they took by default). The recipe checks them before `check_pre()`: `impl-tmr`
  and `impl-impl` are refused before anything runs. `tmr` takes RTL, `impl` turns RTL into an
  implemented block, `vrf` takes either. A step that changes the kind builds its output with
  `StepData.convert()`.
- `macro()` declares an implemented block (a hard macro) by its netlist and abstracts — the
  arguments of `lib()`, plus `top` and `libs`. It is lib data from the start: a target that
  `vrf` simulates as a netlist, and integrated as a hard macro by the RTL blocks that include
  it. `lib()` is for cell libraries only: named in `libs=`, never included; each is refused
  in the other's place, with a message naming the right one. `vrf_libs` names either.
- `block()` declares RTL only: `netlist_files`, `netlist_incdirs`, `liberty_files`,
  `si_files` and `layout_info` are no longer `block()` arguments. **Manifests:** move a block
  declaring them to `macro()` and include it where it is instantiated; `impl` no longer takes
  a sub-block's abstracts declared on the parent.
- `DesignSpec` is the base of everything a recipe runs on; `block()` and `macro()` are two. A tool can add a
  kind of design — a spec and a `StepData` subclass, and a step that turns it into RTL in a
  manifest projects `load()` — as rdl2verilog does for SystemRDL register maps (`rdl()`).
- Every include is checked on load against the steps' signatures and what its block can
  include, and a wrong one names the recipe that would convert it.
- `bake` lists a block's kind when it is not RTL and each step's signature
  (`impl  (rtl -> lib)`).
- **Custom steps:** a step reading `rtl_files` or netlist fields should declare `consumes`;
  code constructing `StepData(rtl_files=...)` constructs `RtlData` or `LibData` instead.

**Up-to-date check** (`bake/step.py`)

- A step whose script failed after writing its outputs was reported up to date on the next
  run. A success stamp (`work/<block>/<recipe>/.bake_stamp.json`) is removed before the flow
  starts and written after it returns 0 and the outputs are verified. Work directories from
  1.0.0 have no stamp, so every step re-runs once after upgrading.
- Configuration changes re-run a step: the stamp records the bake version, the template
  variables, the source file list and the contents of the block's flow directory; the reason
  is logged, and `-n` shows it in brackets. `-v` and `-i` are not build inputs.
- Symlinked sources are followed; the "all inputs are symlinks" error is gone. Timestamps use
  mtime (ctime also changed on `chmod` and checkout).
- `-n` cannot be combined with `-c`, `-r` or `-p`; `--version` added.

**Manifest**

- `block(vcd_files=...)` no longer crashes; `vcd_files` and `saif_files` are corner
  dictionaries, and a plain list or a single file is the `"default"` corner.
- A `test()` defined twice for the same block, and an attribute a builtin step's config does
  not have (`config.vrf.simulater = ...`), are errors. Custom step configs get the same by
  deriving from `config.FixedSchemaAttributes`.
- Wherever a list of files is expected a single string or a `pathlib.Path` is accepted; a
  corner may map to a single file. `layout_info` may name several files, space-separated; a
  missing one is a warning.
- Manifest errors are reported as one line with their location
  (`manifest:22: block(): unknown argument 'rtl_file' (did you mean 'rtl_files'?)`); the
  traceback only with `-v`.
- `config.bake.default_libs` is back: a block that declares no `libs=` uses it, so shared
  RTL can be implemented in whatever libraries the including project sets.
- `target()` is deprecated: it still declares a block, logs a warning naming the manifest
  line, and will be removed in a future major release. Use `block()`. (The `target=` argument of `test()` and
  `env()` is unaffected.)
- The `dummy` step is no longer a builtin; `example/06_custom_step` is the template for a
  step of your own.

**Flows and templates**

- Steps run their flows from the flow's own directory: a run no longer copies the flow into
  `flow/<block>/<recipe>/`, so fixes to a flow and *bake* upgrades reach every block that has not
  customised it. `-p` makes the copy, on purpose: for the recipe's last step only (not its
  earlier steps, nor its dependencies), and it combines with no other mode (`-n`, `-i`, `-f`,
  `-c`, `-r`). A copy is used whenever it exists, so existing projects run as before.
  `-p` records where the copy came from in `.bake_flow.json` (the flow, a digest of its files,
  the *bake* version, the git commit and whether it was clean); when the flow changes, each run
  warns and says how to see the changes, and `-p` on the existing copy records it as up to date.
  Every run logs which flow it uses. **Projects:** a copy that was never customised can be
  deleted, and the step then runs the flow itself.
- Only `$BAKE_...` tokens are template placeholders; any other `$` (Tcl and shell variables)
  is copied as it is. `$$` still yields `$`, so existing templates render as before.
- Every run writes the template variables to `work/<block>/<recipe>/bake_vars.json`, lists
  kept as lists, and passes its path to the flow as `$BAKE_VARS`. Template values may be lists
  (space-joined in `.tpl` files). The builtin `run.py` scripts read the JSON.
- `impl`: the `<top>_<corner>.lib` abstracts are expected outputs; a library lacking Liberty
  for a corner another library provides is refused in `check_pre()`.
- `tmr`: two RTL files with the same basename are refused (their outputs would collide).
- A flow file that is not a template keeps its mode in the work directory, so a plain
  (non-`.tpl`) run script is executable.
- `vrf`: `vrf_pass_regex` / `vrf_fail_regex` on tests and envs, checked against the captured
  simulator output (`bake_sim.log`); a UVM log without the report summary fails; every run
  has a seed, logged and settable with `config.vrf.seed` / `-o vrf.seed=N`; the cocotb
  Makefile carries the cocotb 2.x variable names as well.
- `vrf`, Xcelium: plain SV and UVM tests are built (compiled and elaborated) once per build
  configuration, in `work/<block>/<recipe>/_build/`, and each test runs from the build with
  `xrun -R`: tests differing only in the UVM test, the seed or runtime options share it. A stamp
  of the build inputs skips the build check when nothing changed, so parallel tests do not wait
  for each other. New `vrf_runtime_options` (tests and envs) and `config.vrf.runtime_options` /
  `$BAKE_SIM_RUNTIME_OPTIONS` hold options for the simulation only (plusargs); the other
  simulators get them on the command line, Icarus on `vvp`'s, cocotb as `PLUSARGS`. `-c`/`-r`
  on a test also remove the shared builds; a test cannot be named `_build`. **Projects:**
  move plusargs from `vrf_options` (or `-o vrf.options=`) to `vrf_runtime_options` (or
  `-o vrf.runtime_options=`), and seeds to `-o vrf.seed=`, or each value makes a build of its own.
- `vrf`, UVM: 10000 or more `UVM_ERROR`s or `UVM_FATAL`s in the report summary passed the
  test. UVM prints the count as `%5d` right after the colon, so from five digits there is no
  space for the check to find; the counts are now matched with any spacing, and only in the
  summary.

**Other**

- The tab-completion cache is written atomically, honours `XDG_CACHE_HOME` and drops entries
  for directories that no longer exist.
- Python 3.9 is no longer supported. CI runs ruff and mypy next to pylint and enforces a
  coverage floor.

## v1.0.0

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
