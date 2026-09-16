# bake

**Recipe-driven build and verification system for ASIC designs.**

`bake` turns a plain-Python `manifest` describing your design — RTL files, cell libraries,
test benches, hierarchy — into reproducible simulation, TMR insertion, synthesis and
place-and-route runs. You pick a *block* and a *recipe*, and `bake` runs the *steps* in
order, re-running only what changed:

```
bake counter vrf            # simulate the counter block
bake counter impl           # synthesise and place-and-route it
bake counter tmr-impl-vrf   # triplicate, implement, then gate-level simulate
```

Every step executes a *flow* — a directory of scripts that `bake` copies into your project
on first use and fills from `$BAKE_*` template variables. Because the scripts end up in your
tree, everything is customisable and version-controlled; because the file lists come from the
manifest, RTL, implementation and verification never disagree about what the design is.

## Installation

```
pip install bake-eda
```

Tools are discovered on `PATH`. Out of the box the built-in steps drive:

| Step   | What it does                          | Open-source tools                          | Commercial |
|--------|---------------------------------------|--------------------------------------------|-----------|
| `vrf`  | compile and run a test                | Icarus Verilog, Verilator, cocotb          | Xcelium, Questa, VCS (incl. UVM) |
| `impl` | synthesis + place-and-route           | Yosys + OpenROAD, with the PDK libraries your manifest registers | — |
| `tmr`  | triple-modular-redundancy insertion   | [tmrg](https://github.com/rlf-arlut/tmrg)  | — |

bake has **no PDK dependency** and ships no PDK-specific code. The `impl` step consumes whatever
standard-cell libraries a manifest registers with `lib()`. The reference for doing that is
[`example/pdk/sky130/manifest`](example/pdk/sky130/manifest), which registers the open-source
SkyWater sky130 PDK from `PDK_ROOT` — used by the test suite and examples 03/05 purely so that
synthesis and place-and-route can be exercised end to end on an open PDK
(`test/pdk/fetch_sky130.sh` fetches one with `ciel`). Copy that manifest to adapt bake to your
own kit; see [Installation](docs/installation.md). To enable tab-completion for the lifetime of a
shell:

```
eval "$(register-python-argcomplete bake)"
```

## A minimal manifest

```python
from bake import block, test

block(
    name="counter",
    top="counter",
    rtl_files=["rtl/counter.v"],
)

test(
    name="counter_test",
    target="counter",
    vrf_files=["vrf/counter_tb.v"],
    default_sim="icarus",
)
```

Running `bake` with no arguments lists the blocks, tests and steps it found; `bake counter vrf`
runs the test. The [Quick Start](docs/quickstart.md) walks through this and on to TMR.

## Examples

The [`example/`](example/) directory contains runnable designs, each with a `manifest` and a
header comment explaining what it shows and which tools it needs. Start with
`example/01_counter_sim`.

## Documentation

- [Introduction](docs/introduction.md) — scope and theory of operation
- [Quick Start](docs/quickstart.md) — tutorial
- [Glossary](docs/glossary.md) — block, recipe, step, flow, and friends
- [Design Modeling](docs/manifest_design_model.md) · [Verification Modeling](docs/manifest_verif_model.md)
- [Configuration](docs/configuration.md) — `config` sections and template variables
- [Custom Steps](docs/custom_steps.md) · [Custom Flows](docs/custom_flows.md) — extending bake
- [Releases](docs/releases.md)

## Development

```
git clone https://github.com/apatern0/bake.git && cd bake
python3 -m venv venv && source venv/bin/activate
pip install -e ".[test,docs]"
pytest
mkdocs serve
```

## History

`bake` is a modified derivative of [**tmake**](https://gitlab.cern.ch/tmake/tmake), a build
system for fault-tolerant ASICs developed at CERN (Copyright 2025 CERN, Apache-2.0) by Stefan
Biereigel, Szymon Kulis and others. It forked from tmake commit `5c13314a` in May 2023 and was
substantially reworked since. See [NOTICE](NOTICE).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
