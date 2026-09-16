# Test projects

Each directory is a small, self-contained bake project that one or more tests in
`test_bake.py` run. The `project` fixture in `conftest.py` copies this whole tree (and
`example/`, which `sky130/` refers to) into a temporary directory and changes into the named
project, so tests never touch the checkout.

They are ordinary projects: `cd` into one and run `bake` to see what a test sees. `flows/`
holds the stand-in flows every project loads, `rtl/` the shared Verilog, `steps/` custom
steps laid out like built-in ones (`check` records what reaches a step, `dummy` does nothing
and is combined with the real steps in the recipe tests). Projects whose name says so (`hier_cycle`,
`unknown_field`, ...) are meant to be rejected.
