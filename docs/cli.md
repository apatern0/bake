# Command Line

```
bake [BLOCK RECIPE] [options]
```

With no positional arguments, `bake` loads the manifest in the current directory and lists the
blocks it found (with their [kind](custom_steps.md#data-kinds) when it is not RTL), the tests
attached to each, the state of the dependencies their includes require, and the available
steps with the kinds they take and give (`impl  (rtl -> lib)`). With a block and a recipe it runs the recipe's steps in order
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
| `-c`, `--clean` | Remove the work directory of the block/recipe combination (`work/<block>/<recipe>`, for `vrf` the test's, plus the simulation builds the block's tests share) and stop. The directories of the recipe's earlier steps belong to their own, shorter recipes (`tmr` for `tmr-impl`) and are left alone, as are dependencies. |
| `-r`, `--restart` | Remove that work directory, then run the recipe. |
| `-p`, `--populate-flow` | Copy the flow of the recipe's last step into `flow/<block>/<recipe>/` (plus the test for `vrf`) to customise it, and run nothing. That step runs the copy from then on; the recipe's earlier steps and its dependencies keep running their flows. On an existing copy, the copy is left as it is and recorded as based on the flow as it is now. See [Custom Flows](custom_flows.md#customising-a-flow-for-one-block). |
| `-l`, `--list-libs` | List the libraries (`lib()`) and macros (`macro()`) registered by the manifests, then exit. |
| `-i`, `--interactive` | Ask flows to run interactively where they can (e.g. open the simulator GUI). |
| `-v`, `--verbose` | Debug logging. Repeat for more. |
| `--version` | Print the bake version and exit. |

`-f`, `-c`, `-r` and `-p` are mutually exclusive, and `-p` combines with neither `-n` nor `-i`;
`-n` combines with `-f` only.

## When a step runs

A step is skipped when all of the following hold; otherwise it runs, and *bake* says why:

- every file in its `output_files` exists;
- its last run completed: the flow script returned 0 and the outputs were verified. *bake*
  records this in `work/<block>/<recipe>/.bake_stamp.json`, removed before the flow starts, so a
  step that fails after writing some outputs — or is interrupted — stays "would run";
- what it was built from has not changed: the bake version, the template variables the flow
  received (config, `-o` overrides, flow options, ...), the list of source files, and the contents
  of the flow the step runs (the flow's own directory, or the block's copy). Which of these differs
  is reported; populating an untouched copy changes nothing;
- no source file is newer than the oldest output. Sources are compared by modification time,
  following symlinks, so editing a file behind a link is noticed.

A step that declares no `output_files` always runs. `-v` and `-i` are not build inputs and do not
cause a re-run. `-n` reports the reason for each step that would run, in brackets:

```
[bake] INFO     up to date:        block impl  (dependency of top2)
[bake] INFO     would run:         top2 vrf  [no output files declared]
```

## Interrupting bake

A step owns every process its flow starts, including those that leave the flow's process group
or session (a simulator's GUI) and those that daemonize (a GUI's server):

- an interrupt of *bake* (`SIGINT`: Ctrl-C, `SIGTERM`, or `SIGHUP`: the terminal closed) is
  passed on to every process of the running step, and the step fails, whatever its script
  returns;
- a second interrupt kills them all (`SIGKILL`);
- the processes still running when the step's script exits are ended, `SIGTERM` first and
  `SIGKILL` after `config.bake.kill_grace` seconds; *bake* lists them, as a warning when the
  step was not interrupted. A process meant to outlive the step (a server shared by many runs)
  is started outside *bake*.

How *bake* knows a step's processes is said once per run, with why a better way is not
available:

```
[bake] INFO     Flow processes are tracked as bake's children (subreaper), as cgroups are unavailable: /sys/fs/cgroup is mounted read-only; no systemd user manager (...). A bake killed with SIGKILL can still leave them running.
```

| `config.bake.process_tracking` | How |
|-------------------------------|-----|
| `auto` (default) | The first of `cgroup` and `subreaper` that works here |
| `cgroup` | Each step runs in a cgroup v2 of its own: below *bake*'s own cgroup when that is writable (a delegated subtree), otherwise a systemd user scope (`systemd-run --user --scope`). Nothing leaves a cgroup, and the processes of a *bake* that was killed with `SIGKILL` are killed by the next *bake* that makes its cgroups there. An error where *bake* cannot make cgroups (a container with `/sys/fs/cgroup` mounted read-only and no systemd). |
| `subreaper` | *bake* is the child subreaper of the step's processes (Linux), so that those that daemonize are re-parented to *bake* rather than to init. A *bake* killed with `SIGKILL` leaves them running. |
| `group` | The step's process group only: what leaves it is out of reach, and what the script leaves is not ended (how *bake* tracked them before) |

`-o bake.process_tracking=subreaper` chooses one for a run.

## Exit status

`0` on success. `1` when a manifest cannot be loaded, a block/test/step is unknown, a step's
script exits non-zero or fails to produce its declared outputs, or a step is interrupted. `2`
for a command-line error.

A manifest error is reported as one line per problem with where it happened:

```
[bake] ERROR    manifest:22: block(): unknown argument 'rtl_file' (did you mean 'rtl_files'?)
```

Python errors in the manifest's own code (a misspelt function name, a syntax error) are reported
the same way. The traceback is shown with `-v`, or always when the error comes from inside bake.

## Tab completion

`bake` completes block names, recipes and test names (via
[argcomplete](https://github.com/kislyuk/argcomplete)):

```
eval "$(register-python-argcomplete bake)"
```

Completion relies on a per-directory cache; see
[Installation](installation.md#command-auto-completion) for how it is refreshed and disabled.
