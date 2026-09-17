# Command Line

```
bake [BLOCK RECIPE] [options]
```

With no positional arguments, `bake` loads the manifest in the current directory and lists the
blocks it found, the tests attached to each, the state of the dependencies their includes
require, and the available steps. With a block and a recipe it runs the recipe's steps in order
on that block, skipping steps whose outputs are already up to date. A block that includes
another block after a recipe (`includes={"sub": "impl"}`) depends on it: `sub impl` is run first
when its outputs are missing or older than its sources.

| Option | Effect |
|---|---|
| `-m PATH`, `--manifest-dir PATH` | Directory containing the `manifest` to load (default: `.`). |
| `-t NAME`, `--test NAME` | Select the test to run for a `vrf` step. Required when the block has more than one test; auto-selected when it has exactly one. |
| `-o SECTION.ATTR=VALUE`, `--options` | Override a `config` attribute for this run, e.g. `-o vrf.simulator=verilator`. Repeatable. The value takes the attribute's type: list attributes are appended to, booleans accept `true/false/1/0`, integers are converted, anything else is set as a string. Unknown sections and attributes are errors. |
| `-n`, `--dry-run` | Elaborate the recipe, dependencies included, and report per step whether it is up to date or would run — without executing anything. Exits `1` when a step refuses the block/recipe combination, with the reason. |
| `-f`, `--force` | Run every step of the requested recipe even if its outputs are up to date. Dependencies are not forced; they run only when stale. |
| `-c`, `--clean` | Remove the work directory of the block/recipe combination (`work/<block>/<recipe>`) and stop. The directories of the recipe's earlier steps belong to their own, shorter recipes (`tmr` for `tmr-impl`) and are left alone, as are dependencies. |
| `-r`, `--restart` | Remove that work directory, then run the recipe. |
| `-p`, `--populate-flow` | Copy the flow skeletons into `flow/` for the recipe and its dependencies without running any step. Useful to inspect or edit the scripts first, or when the tool a step needs is not installed. |
| `-l`, `--list-libs` | List the libraries (`lib()`) registered by the manifests, then exit. |
| `-i`, `--interactive` | Ask flows to run interactively where they can (e.g. open the simulator GUI). |
| `-v`, `--verbose` | Debug logging. Repeat for more. |
| `--version` | Print the bake version and exit. |

`-f`, `-c`, `-r` and `-p` are mutually exclusive; `-n` combines with `-f` only.

## When a step runs

A step is skipped when all of the following hold; otherwise it runs, and *bake* says why:

- every file in its `output_files` exists;
- its last run completed: the flow script returned 0 and the outputs were verified. *bake*
  records this in `work/<block>/<recipe>/.bake_stamp.json`, removed before the flow starts, so a
  step that fails after writing some outputs — or is interrupted — stays "would run";
- what it was built from has not changed: the bake version, the template variables the flow
  received (config, `-o` overrides, flow options, ...), the list of source files, and the contents
  of the block's flow directory (`flow/<block>/<recipe>/`). Which of these differs is reported;
- no source file is newer than the oldest output. Sources are compared by modification time,
  following symlinks, so editing a file behind a link is noticed.

A step that declares no `output_files` always runs. `-v` and `-i` are not build inputs and do not
cause a re-run. `-n` reports the reason for each step that would run, in brackets:

```
[bake] INFO     up to date:        block impl  (dependency of top2)
[bake] INFO     would run:         top2 vrf  [no output files declared]
```

## Exit status

`0` on success. `1` when a manifest cannot be loaded, a block/test/step is unknown, or a step's
script exits non-zero or fails to produce its declared outputs. `2` for a command-line error.

## Tab completion

`bake` completes block names, recipes and test names (via
[argcomplete](https://github.com/kislyuk/argcomplete)):

```
eval "$(register-python-argcomplete bake)"
```

Completion relies on a per-directory cache; see
[Installation](installation.md#command-auto-completion) for how it is refreshed and disabled.
