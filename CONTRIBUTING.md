# Contributing to bake

Thanks for taking the time. Bug reports, examples, flow improvements and documentation fixes
are all welcome.

## Setting up

```
git clone https://github.com/apatern0/bake.git && cd bake
python3 -m venv venv && source venv/bin/activate
pip install -e ".[test,docs]"
pytest
```

The test suite runs without any EDA tool installed: tests that need `tmrg`, `yosys`,
`openroad` or the sky130 submodule skip themselves. Install what you have and they run.

## Making changes

- One logical change per pull request. Explain *why* in the description.
- Add or update a test for behaviour changes. `test/test_bake.py` drives the CLI in-process;
  fixtures build throwaway manifests and flows under a temporary directory.
- Keep the vocabulary consistent: a **block** is baked with a **recipe**, a recipe is a series
  of **steps**, a step runs a **flow**. See `docs/glossary.md`.
- Steps must not read `context` registries at run time — only `self.data` and `self.config`.
- Log messages at `INFO` must make sense to someone who does not know the code.
- User-facing changes get a line in `docs/releases.md` under the upcoming version.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
`feat(vrf): ...`, `fix(impl): ...`, `docs: ...`, with a `!` or `BREAKING CHANGE:` footer when
manifests or flow skeletons have to change.

## Adding a built-in step or flow

Built-in steps live in `bake/builtin/<name>/manifest` with their flow skeleton in
`bake/builtin/<name>/flow/`. They ship inside the wheel, so keep them free of anything
technology- or site-specific: no foundry cell names, no local paths. Configurable behaviour
goes into the step's config section.

## Licence

By contributing you agree that your contributions are licensed under the Apache License 2.0,
like the rest of the project. Add `# SPDX-License-Identifier: Apache-2.0` to new source files.
