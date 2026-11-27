---
name: bake
description: Running bake, the manifest-driven ASIC build and verification tool, and reading its runs: `bake <block> <recipe>` and its options (-t, -o, -n, -f/-c/-r/-p, --list-options), work directories, summary.json. Its manifests.md covers writing manifests (block(), test(), regression(), sweep(), project()/option(), flow(), ...), custom flows and steps.
---

# bake

You **bake** a **block** with a **recipe**; a recipe is a series of **steps** joined by hyphens
(`impl`, `tmr-impl-vrf`); each step runs a **flow**, a directory of scripts and `.tpl` templates.
Blocks, tests and the rest are declared in files named `manifest`: plain Python that bake
`exec`s.

## Which bake

This skill ships inside bake (`skills/bake/`) and describes the bake of that checkout. A project
usually pins bake as a submodule (e.g. `tools/bake`) and links the skill from there, so the two
match. The full documentation is `docs/` of the same checkout:

```sh
python -c "import bake, pathlib; print(pathlib.Path(bake.__file__).parents[1] / 'docs')"
bake --version
```

When the project runs another bake than the one this skill sits in (an older pin, a different
venv), trust `bake -h` and that checkout's `docs/`. Options this skill names may not exist there
yet (`--list-options`, `sweep()` and `project()` options are recent).

## Commands

```sh
bake                                # list the top project's blocks, tests, dependencies and steps
bake -a                             # ... of every project the manifests load
bake <block> <recipe>               # run; up-to-date steps are skipped, stale dependencies built first
bake <block> vrf -t <test>          # -t needed when the block has more than one test
bake <block> <recipe> -n            # dry run: what would run, and why
bake <block> <recipe> -f            # force the requested recipe (dependencies only when stale)
bake <block> <recipe> -c | -r       # clean the work directory | clean then run
bake <block> <recipe> -p            # copy the last step's flow to flow/<block>/<recipe>/ to customise; runs nothing
bake <block> <recipe> -i            # interactive (simulator GUI), where the flow supports it
bake -o section.attr=value ...      # override a config attribute (repeatable)
bake -o section.attr.key=value ...  # set one key of a dictionary attribute
bake -o option=value ...            # set an option of the top project
bake --list-options [-o ...]        # every option and attribute: value, origin, kind, choices, description
bake -l                             # libraries and macros
bake -m <dir> ...                   # manifest in another directory
```

- The target is a **block** (or a regression or sweep, which are blocks of their own kind),
  never a test: `bake <test> vrf` fails with "No such block".
- `-f`, `-c`, `-r`, `-p` exclude each other; `-p` combines with neither `-n` nor `-i`; `-n`
  combines with `-f` only.
- Exit status: 0 success, 1 manifest/step/run failure or interrupt, 2 command-line error.
  `-v` adds debug output and tracebacks.
- `-o` sets a section attribute or project option before manifests read it, except list items
  (`-o vrf.options=-x`) and single dict keys (`-o impl.flow_options.k=v`), which land after
  loading. A failing simulation repeats with `-o vrf.seed=<N>` (logged as `Simulation seed: N`);
  plusargs (`-o vrf.runtime_options=+X=1`) reuse the build, defines and options do not.

## Reading a run

| Where | What |
|---|---|
| `work/<block>/<recipe>/` | a step's work directory (`config.bake.output_dir` moves `work/`); vrf adds `/<test>` |
| `work/<name>/` | a directory a flow claimed with `scratch_dir(name)` (a cache shared by the blocks); no block may have its name |
| `.../bake_vars.json` | every `$BAKE_*` variable the flow got, lists as lists |
| `.../.bake_stamp.json` | written when the step completed; missing = the step will run again |
| `.../summary.json` | how the run went, if its flow writes one (status, stage, error, metrics, notes, inspect) |
| `work/<block>/<recipe>/_build/` | simulation builds shared by a block's tests |
| `work/<regression>/regression/` | `runs/<block>/<test>/<n>/run.log`, `results.csv` |
| `work/<sweep>/sweep/` | `runs/<variant>/`, `report.md`, `results.csv`, `sweep.pid` |
| `flow/<block>/<recipe>/` | a flow copy made by `-p`, with `.bake_flow.json` |

A step is skipped only when its outputs exist, its last run completed, its inputs (bake version,
template variables, file list, flow contents) are unchanged and no source is newer than the
oldest output. `-n` prints the reason for each step that would run.

## Writing manifests, flows and steps

Before writing or changing a manifest, a flow or a step, read `manifests.md` next to this file:
the declarations, how `-o` lands, and a table of tasks with the sections of `docs/` they need.

## Pitfalls

- The built-in vrf flow starts the simulator through a shell: a define or option whose value has
  quotes or spaces loses them. Pass strings as plusargs and read them with `$value$plusargs`.
- A step owns its processes: Ctrl-C reaches all of them, and what its script leaves running is
  ended when it exits. A server meant to outlive a run is started outside bake.
- Tests of a block share builds: `-r` on one of them removes the shared builds, and a build waits
  for the simulations running from it.
- A regression's runs build what they need themselves: many runs starting on a stale dependency
  all wait for it. Run `bake <block> <earlier recipe>` first.
- `-p` copies only the last step's flow; an untouched copy is better deleted than kept.
