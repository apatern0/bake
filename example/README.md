# Examples

Each directory is a self-contained project: `cd` into it and run the commands from the
comment at the top of its `manifest`. Examples 01–07 build on one another in order.
The shared counter design lives in [`counter/`](counter/). [`pdk/sky130/`](pdk/sky130/manifest) is the
reference PDK manifest: how a project registers a PDK's standard-cell libraries for the `impl`
step (03 and 05 load it; it needs `PDK_ROOT`, see [`test/pdk/fetch_sky130.sh`](../test/pdk/fetch_sky130.sh)).

| Example | Shows | Needs |
|---|---|---|
| [`01_counter_sim`](01_counter_sim/manifest) | `block()` + `test()`, the recipe `vrf` | Icarus Verilog |
| [`02_counter_cocotb`](02_counter_cocotb/manifest) | `env()` reuse across tests; cocotb; choosing a simulator | Icarus Verilog, cocotb, Verilator |
| [`03_counter_impl`](03_counter_impl/manifest) | synthesis + P&R on sky130 (`impl`), then gate-level simulation with SDF (`impl-vrf`) | Yosys, OpenROAD, Icarus Verilog, `pdk/sky130` + `PDK_ROOT` |
| [`04_counter_tmr`](04_counter_tmr/manifest) | TMR insertion; recipes `tmr` and `tmr-vrf` | tmrg, Icarus Verilog |
| [`05_hierarchical`](05_hierarchical/manifest) | blocks including other blocks, as RTL or after `impl` (hard macro); dependencies built on demand | Icarus Verilog; Yosys, OpenROAD, `PDK_ROOT` for the implemented adder |
| [`06_custom_step`](06_custom_step/manifest) | a project-defined `lint` step and its flow, loaded like any manifest; recipe `lint-vrf` | Verilator, Icarus Verilog |
| [`07_parametrized`](07_parametrized/manifest) | generating tests in a loop — manifests are Python | Icarus Verilog |

All of them work with open-source tools only. Steps run their flows from *bake*'s installation;
`bake <block> <recipe> -p` copies the flow of that recipe's last step into `flow/`, without
running anything, for the block to customise (the step runs the copy from then on).
