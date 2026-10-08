# Verification Modeling
This section focuses on modeling verification-related aspects using *bake*.

## Environments
Verification environments are defined using the `env()` function. The full syntax is:

```python
env(name, desc, includes, target, vrf_top, vrf_files, vrf_incdirs, vrf_libs,
    vrf_options, vrf_runtime_options, vrf_defines, vrf_framework, vrf_framework_top, default_sim,
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
  * `vrf_runtime_options` — dictionary of simulator-specific option lists for running the
    simulation only, such as plusargs; tests differing only in these share one build, see
    [Building once for many tests](#building-once-for-many-tests) — optional
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

## Libraries and Macros
Cell libraries (defined via `lib()`) and implemented blocks (defined via `macro()`) are
simulated through their `netlist_files`: a behavioral or gate-level Verilog model. A block's
libraries (`libs=`) and the macros it includes are passed to the simulator with its RTL, so
pre-implementation simulations use their models. A testbench adds libraries or macros of its
own with `vrf_libs=`. A macro is also a target: `bake <macro> vrf` simulates its netlist with the
tests that target it.

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

### Building once for many tests

With Xcelium, for plain SV and UVM tests, the built-in flow builds (compiles and elaborates) the
design and testbench once, and runs every test that needs the same build from it. The builds
live in `work/<block>/<recipe>/_build/`, next to the tests' work directories, one directory per
build configuration: tests whose build commands are identical share one. What each test gives
only the simulation stays out of the build: the UVM test name (`vrf_framework_top`), the seed
and the runtime options (`vrf_runtime_options`, `config.vrf.runtime_options`). Anything else
that differs — `vrf_defines`, `vrf_options`, files, include directories, `-i` — makes a build of
its own. So options a test gives the simulation only belong in `vrf_runtime_options`:

```python
test(name="t", target="core", vrf_framework="uvm", vrf_framework_top="t", default_sim="xcelium",
     vrf_options={"xcelium": ["-64bit"]},                                # both phases
     vrf_runtime_options={"xcelium": ["+HITS_FILE=hits.txt"]})           # simulation only
```

Before each test, the flow checks whether the build is current: when neither the build command
nor any source file, nor an HDL file under the include directories (recursively) or next to a
source file, changed since the last build, the build is reused as it is. Otherwise Xcelium's
incremental build brings it up to date, recompiling what changed. Files the check cannot see —
an `include` outside those directories, a `-f` file list given in `vrf_options` — are still
picked up by Xcelium the next time something else triggers the incremental build; `-r` on any of
the block's tests removes the shared builds and starts over.

Tests may run in parallel: builds take turns, and Xcelium keeps a build from being rebuilt while
simulations run from it. The build's output is in `_build/<id>/elab.log`, and in the output of
the test that built it. Gate-level simulations with SDF back-annotation still build and run
in one step in the test's work directory: the annotated build is not shared.

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

## Regressions

A regression runs tests many times: each a number of times with random seeds, or once per
given seed. It is declared with `regression()`, a block of its own kind, and run by the
`regression` step:

```python
from bake import regression

regression(name="counter_smoke", target="counter",
           tests={"counter_test": 4,                  # four runs, random seeds
                  "counter_wrap_test": [11, 42]})     # one run per seed
regression(name="counter_nightly", target="counter",
           tests={"counter_random_test": 50},
           includes=["counter_smoke"],                  # its runs as well
           options=["vrf.runtime_options=+VERBOSE"])    # an -o for every run
```

```
bake counter_nightly regression
```

| Argument | Description |
|----------|-------------|
| `target` | The block whose tests run |
| `tests` | `{test: runs}`, with random seeds, or `{test: [seeds]}`; a test name or a list of names runs once each |
| `recipe` | What each run executes, ending with `vrf` (default `"vrf"`; `"tmr-vrf"`, say) |
| `options` | `-o` overrides for every run, `section.attribute=value` |
| `includes` | Other regressions, whose runs are added, with this regression's `options` after their own |

Every run is a *bake* invocation of its recipe on its test — `bake <target> <recipe> -t <test>`
with the run's seed and the options — in a directory of its own (`config.vrf.run_dir`): the
runs of a regression never share a work directory, while they share the simulation builds in
`work/<block>/<recipe>/_build/` (see [Building once for many tests](#building-once-for-many-tests)).
The `-o` options of the regression's own command line reach every run too, after the
regression's: `bake counter_nightly regression -o vrf.simulator=icarus`. Tests, blocks and
steps are checked when the regression runs, so they may be declared in manifests loaded after
it.

Earlier steps of the recipe (`tmr` for `tmr-vrf`) and the block's dependencies are built by the
runs that need them: bring them up to date before a regression starts many runs at once
(`bake counter tmr`).

The step hands its flow the runs ready to start, one command each, so the flow is only the
engine that starts them. The built-in flow starts them on this machine; to run regressions on
another engine (a batch system, a regression manager), a project registers a flow of its own
(see [Writing a Regression Flow](custom_flows.md#writing-a-regression-flow)).

### On this machine

The default flow, `builtin_regression_flow`, runs the regression on the machine *bake* runs on,
each run in `work/<regression>/regression/runs/<block>/<test>/<n>/` with its output in
`run.log`. It writes `results.csv` (block, test, run, seed, status, duration, directory), lists
the runs that did not pass with the command that repeats each, and fails the step if there is
one. Flow options:

| Option | Default | Description |
|--------|---------|-------------|
| `jobs` | `0` | Runs at a time; `0`: one per CPU |
| `timeout` | `0` | Seconds a run may take before it is stopped; `0`: no limit |

```python
config.regression.flow_options["jobs"] = 8
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
