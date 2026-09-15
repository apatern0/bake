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

The built-in `impl` step uses the open-source SkyWater sky130 PDK, which is a ~400 MB git
submodule and is **not** fetched by default. Populate it only if you want to run implementation:

```
cd bake/
git submodule update --init bake/builtin/impl/skywater-pdk
```

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
