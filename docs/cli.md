# Command Line

```
bake [BLOCK RECIPE] [options]
```

With no positional arguments, `bake` loads the manifest in the current directory and lists the
blocks it found, the tests attached to each, and the available steps. With a block and a
recipe it runs the recipe's steps in order on that block, skipping steps whose outputs are
already up to date.

| Option | Effect |
|---|---|
| `-m PATH`, `--manifest-dir PATH` | Directory containing the `manifest` to load (default: `.`). |
| `-t NAME`, `--test NAME` | Select the test to run for a `vrf` step. Required when the block has more than one test; auto-selected when it has exactly one. |
| `-o SECTION.ATTR=VALUE`, `--options` | Override a `config` attribute for this run, e.g. `-o vrf.simulator=verilator`. Repeatable. List-valued attributes are appended to. |
| `-f`, `--force` | Run every step of the recipe even if its outputs are up to date. |
| `-c`, `--clean` | Remove the work directory of the block/recipe combination and stop. |
| `-r`, `--restart` | Remove the work directory, then run the recipe. |
| `-p`, `--populate-flow` | Copy the flow skeletons into `flow/` for the recipe without running any step. Useful to inspect or edit the scripts first, or when the tool a step needs is not installed. |
| `-l`, `--list-libs` | List the libraries (`lib()`) registered by the manifests, then exit. |
| `-i`, `--interactive` | Ask flows to run interactively where they can (e.g. open the simulator GUI). |
| `-v`, `--verbose` | Debug logging. Repeat for more. |

`-f`, `-c`, `-r` and `-p` are mutually exclusive.

## Exit status

`0` on success. `1` when a manifest cannot be loaded, a block/test/step is unknown, or a step's
script exits non-zero or fails to produce its declared outputs. `2` for a command-line error.

## Tab completion

`bake` completes block names, recipes and test names (via
[argcomplete](https://github.com/kislyuk/argcomplete)):

```
eval "$(register-python-argcomplete bake)"
```

Completion data is cached per directory in `~/.cache/bake/`; set `BAKE_NO_CACHE=1` to disable
the cache. See [Installation](installation.md#command-auto-completion).
