# Examples

Each directory is a self-contained project: `cd` into it and run the commands from the
comment at the top of its `manifest`. Examples 01–07 build on one another in order.
The shared counter design lives in [`counter/`](counter/).

| Example | Shows | Needs |
|---|---|---|
| [`01_counter_sim`](01_counter_sim/manifest) | `block()` + `test()`, the recipe `vrf` | Icarus Verilog |
| [`02_counter_cocotb`](02_counter_cocotb/manifest) | `env()` reuse across tests; cocotb; choosing a simulator | Icarus Verilog, cocotb, Verilator |
| [`03_counter_impl`](03_counter_impl/manifest) | synthesis + P&R on sky130, the single-step recipe `impl` | Yosys, OpenROAD, `PDK_ROOT` → sky130 |
| [`04_counter_tmr`](04_counter_tmr/manifest) | TMR insertion; recipes `tmr` and `tmr-vrf` | tmrg, Icarus Verilog |
| [`05_hierarchical`](05_hierarchical/manifest) | blocks including other blocks, as RTL or as an implemented macro | Icarus Verilog; Yosys, OpenROAD for `impl` |
| [`06_custom_step`](06_custom_step/manifest) | `add_steps_dir()`, a `lint` step and its flow; recipe `lint-vrf` | Verilator, Icarus Verilog |
| [`07_parametrized`](07_parametrized/manifest) | generating tests in a loop — manifests are Python | Icarus Verilog |

All of them work with open-source tools only. `bake <block> <recipe> -p` populates the
`flow/` directory without running anything, which is a useful way to look at the scripts a
step would execute even when the tool it needs is not installed.
