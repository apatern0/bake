# Verification Modeling
This section focuses on modeling verification-related aspects using *bake*.

## Environments
Verification environments are defined using the `env()` function. The full syntax is:

```python
env(name, desc, includes, target, vrf_top, vrf_files, vrf_incdirs, vrf_libs,
    vrf_options, vrf_defines, vrf_framework, vrf_framework_top, default_sim,
    vrf_pass_regex, vrf_fail_regex)
```

Arguments:

  * `name` — name used to reference this environment from other manifest entries
  * `desc` — human-readable description (optional, documentation only)
  * `includes` — list of other environments to inherit from — optional
  * `target` — name of the block that serves as the DUT for this environment
  * `vrf_top` — name of the verification top-level entity (test bench, fixture, ...)
  * `vrf_files` — list of verification files (Verilog, SystemVerilog, Python, depending on the framework)
  * `vrf_incdirs` — list of include directory paths (relative or absolute) — optional
  * `vrf_libs` — list of *bake* library or block names whose Verilog models are included for simulation — optional
  * `vrf_options` — dictionary of simulator-specific option lists — optional
  * `vrf_defines` — list of preprocessor defines passed in a simulator-independent manner — optional
  * `vrf_framework` — verification framework: one of `""` (plain V/SV), `"uvm"`, or `"cocotb"`
  * `vrf_framework_top` — top-level entity or module required by the verification framework (e.g. cocotb test module name) — optional
  * `default_sim` — default simulator to use when running tests
  * `vrf_pass_regex`, `vrf_fail_regex` — pass/fail criteria on the simulator output, see
    [Pass/fail criteria](#passfail-criteria) — optional

The same file reference and inheritance rules from the design modeling section apply here.
Environments can be derived from other environments via `includes`, enabling flexible composition
of harnesses and test cases (e.g. generating multiple tests with different `vrf_defines` from a
shared base environment).

## Tests
Tests in *bake* are a special case of `env` definitions. They represent leaf nodes in the
environment inheritance tree and are the only type that can be executed. A test must have at least
a `target` and a `default_sim` set (either directly or inherited from an included environment).
Any defined test can be run using the `vrf` step. When only one test exists, it is selected
automatically; with multiple tests, specify the desired test with the `-t` flag:

```
bake mybock vrf            # executes the one test defined for myblock
bake myblock vrf -t mytest # executes the test named mytest for myblock
```

## Libraries
Libraries (defined via `lib()`) model non-RTL design components such as macro blocks or standard
cell libraries. The `netlist_files` field provides a behavioral or gate-level Verilog model used
during simulation. When a library is included in a block, this model is passed to the simulator
for pre-implementation simulations.

## Simulator Support
*bake* ships with built-in support for the following simulators via the `builtin_vrf_flow`:

  * Icarus Verilog — `icarus` (free and open source)
  * Cadence Xcelium — `xcelium`
  * Cadence Incisive — `ius`
  * Synopsys VCS — `vcs`
  * Siemens Questa — `questa`
  * Verilator — `verilator`

No special manifest configuration is required to access these simulators. The default simulator
is set via `default_sim` in the test or environment definition, and can be overridden at the
command line:

```
bake myblock vrf -o vrf.simulator=xcelium
```

Support matrix for verification frameworks:

|                 | Plain V/SV | UVM | cocotb |
|-----------------|------------|-----|--------|
| Icarus Verilog  | y          | n   | y      |
| Cadence Xcelium | y          | y   | y      |
| Cadence Incisive| y          | y   | y      |
| Synopsys VCS    | y          | y   | y      |
| Siemens Questa  | y          | y   | y      |
| Verilator       | n          | n   | y      |

## Pass/fail criteria

A test passes when the simulator exits 0 **and** its output meets the test's criteria. The exit
code alone is a weak criterion for plain Verilog testbenches: Icarus, for one, exits 0 after
`$error`. So a test (or an environment it includes) can declare regular expressions that the
built-in flow checks line by line against everything the simulator printed (kept in
`bake_sim.log` in the work directory):

```python
test(name="counter_test", target="counter", includes=["counter_env"],
     vrf_fail_regex=r"^(ERROR|FATAL)\b",     # any matching line fails the test
     vrf_pass_regex=r"TEST PASSED")          # and one must match this
```

For UVM the flow also requires the `UVM Report Summary` in the log — a test that never reaches
the end is a failure, not a pass — and fails on a non-zero `UVM_ERROR`/`UVM_FATAL` count. For
cocotb, `results.xml` decides. The regexes apply on top of both.

## Seeds

Every run has a seed, reported as `Simulation seed: N` in the output and passed to the simulator
in its own way (`-svseed` for Xcelium/Incisive, `+ntb_random_seed=` for VCS, `-sv_seed` for
Questa, `+verilator+seed+` for Verilator, `RANDOM_SEED`/`COCOTB_RANDOM_SEED` for cocotb). It is
random unless `config.vrf.seed` is set; to repeat a failing run:

```
bake counter vrf -o vrf.seed=1234567
```

## UVM Support
Basic UVM tests use the following `env`/`test` options:

```python
env(
    vrf_framework="uvm",
    vrf_framework_top="my_uvm_test_name",
)
```

The value of `vrf_framework_top` is passed as the `UVM_TESTNAME` plusarg to the simulator.
Simulators use their bundled default UVM version by default. To select a specific version, provide
the appropriate simulator-specific option via `vrf_options`.

Default UVM versions and how to override them:

|                 | Default UVM | Change using             |
|-----------------|-------------|--------------------------|
| Cadence Xcelium | uvm-1.1d    | `-uvmhome CDNS-X.X`      |
| Synopsys VCS    | uvm-1.1     | `-ntb_opts uvm-X.X`      |
| Siemens Questa  | uvm-1.1d    | `-uvm -uvmhome uvm-X.X`  |

For Synopsys VCS, the default *bake* flow supplies an additional `-ntb_opts uvm` argument; VCS
ignores this when a user-provided version override is present.

## cocotb Support
Basic cocotb tests use the following `env`/`test` options:

```python
env(
    vrf_files=["harness.v", "test.py"],
    vrf_framework="cocotb",
    vrf_framework_top="test",
)
```

The `vrf_files` list must include both any required Verilog files and the Python test module(s).
`vrf_framework_top` specifies the top-level Python module executed by cocotb. Individual tests
within that module can be selected via cocotb environment variables, e.g.:

```
TESTCASE=my_test bake my_block vrf
```

## Examples

### A Simple Test

```python
from bake import block, env, test

block(
    name="my_block",
    top="my_block",
    rtl_files=["rtl/my_block.v"],
)

test(
    name="my_test",
    target="my_block",
    vrf_files=["vrf/my_test.v"],
    default_sim="xcelium",
)
```

Running `bake my_block vrf` or `bake my_block vrf -t my_test` invokes Xcelium with both the
RTL and verification files.

### More Than One Test
Factor out common settings into a base environment to avoid repetition:

```python
env(
    name="base_env",
    target="my_block",
    vrf_files=["vrf/harness.v"],
    vrf_options={"xcelium": ["-ignore_all_warnings"]},
    default_sim="xcelium",
)

test(
    name="my_test1",
    includes=["base_env"],
    vrf_files=["vrf/my_test1.v"],
)

test(
    name="my_test2",
    includes=["base_env"],
    vrf_files=["vrf/my_test2.v"],
)
```

Both tests inherit the harness file, Xcelium options and default simulator from `base_env`.

### Test Variations
Python loops in the manifest allow generating families of tests that vary a parameter:

```python
env(
    name="base_env",
    target="my_block",
    vrf_files=["vrf/harness.v", "vrf/my_test.v"],
    default_sim="xcelium",
)

for data_width in range(1, 5):
    test(
        name=f"my_test_d{8*data_width}",
        includes=["base_env"],
        vrf_defines=[f"DATA_WIDTH={data_width*8}"],
    )
```

This creates four tests with data widths of 8, 16, 24 and 32 bit. *bake* lists them as:

```
[bake] INFO     Available blocks and associated tests:
[bake] INFO     - my_block
[bake] INFO         - my_test_d8
[bake] INFO         - my_test_d16
[bake] INFO         - my_test_d24
[bake] INFO         - my_test_d32
```

### cocotb Test with Plain Verilog Wrapper

```python
from bake import block, env, test

block(
    name="counter",
    top="counter",
    rtl_files=["rtl/counter.v"],
)

env(
    name="counter_base_env",
    target="counter",
    vrf_files=["vrf/counterWrapper.v"],
)

test(
    name="counter_cocotb_test",
    includes=["counter_base_env"],
    vrf_top="counterWrapper",
    vrf_files=["vrf/counter_test.py"],
    vrf_framework="cocotb",
    vrf_framework_top="counter_test",
    default_sim="icarus",
)
```
