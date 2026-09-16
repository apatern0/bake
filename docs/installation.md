# Installation

*bake* is released as a Python package. After installation it provides the `bake` executable.
Use of a virtual environment is recommended.

```
python3 -m venv venv
source venv/bin/activate
pip install bake-eda
```

To work on *bake* itself, or to pin a project to a specific commit as a git submodule, install
it in editable mode from a checkout:

```
git clone https://github.com/apatern0/bake.git
pip install -e bake/
```

*bake* has no PDK dependency and ships no PDK-specific code. The built-in `impl` step runs a
Yosys + OpenROAD flow on whatever standard-cell libraries a manifest registers with `lib()`.
The reference for registering a PDK is `example/pdk/sky130/manifest`, which picks up the
open-source SkyWater sky130 PDK from an [open_pdks](https://github.com/RTimothyEdwards/open_pdks)
build located through `PDK_ROOT` — the layout shared by
[ciel](https://github.com/fossi-foundation/ciel) and OpenLane. The test suite and examples 03/05
load it. To obtain the PDK (about 340 MB for the `sky130_fd_sc_hd` library):

```
PDK_ROOT=$HOME/.ciel test/pdk/fetch_sky130.sh   # wraps: pip install ciel && ciel enable --pdk sky130 ...
export PDK_ROOT=$HOME/.ciel                      # optional: export PDK=sky130B for the other variant
cd example/03_counter_impl && bake -l            # lists sky130_fd_sc_hd
```

For your own PDK, copy that manifest, point it at your kit's Liberty, LEF and simulation-model
files, fill in the place-and-route settings the built-in flow needs (placement site, pin
layers, clock buffer, tie cells — see the [flow options](configuration.md#configimpl)), and
`load()` it from your project manifest. A different implementation flow is a
[custom flow](custom_flows.md).

Yosys, OpenROAD and Icarus Verilog are all available from conda, which is how the test suite
gets them: `conda create -n eda -c litex-hub -c conda-forge openroad yosys iverilog "fmt=8"`.

The `tmr` step invokes [tmrg](https://github.com/rlf-arlut/tmrg) for TMR insertion; install it
into the same virtual environment if you need triplication. Implementation tools and simulators
(Yosys, OpenROAD, Icarus Verilog, Verilator, cocotb, or a commercial simulator) must be on `PATH`
for *bake* to invoke them.

## Command Auto-completion

*bake* supports tab-completion for targets, recipes, tests, configuration options and
command-line flags. To enable it for the current shell session:

```
eval "$(register-python-argcomplete bake)"
```

To make this persistent across sessions, append the command to the venv activation script:

```
echo "eval \"\$(register-python-argcomplete bake)\"" >> venv/bin/activate
```

Behind the scenes, tab-completion relies on a cache of available targets, tests, and steps for
each directory from which *bake* is invoked. This cache is updated automatically on every
invocation. The cache is stored at `~/.cache/bake/`. If the full set of completions is not
available immediately after adding new items to a manifest, run `bake` once without arguments
to refresh the cache.

If the cache causes problems (for example, race conditions in regression setups), it can be
disabled entirely by setting the environment variable `BAKE_NO_CACHE`:

```
export BAKE_NO_CACHE=1
```
