# Agent skills

`bake/` is a [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills) for
projects that use *bake*. `SKILL.md` covers running *bake* and reading its runs; it is what an
agent loads, so it stays short. `manifests.md` covers manifests, flows and steps, with pointers into
`docs/`, and is read only when a task writes one of them.
It describes the *bake* of the checkout it is in, so a project that pins *bake* as a submodule
links it from there and gets the skill that matches its *bake*:

```sh
mkdir -p .claude/skills
ln -s ../../tools/bake/skills/bake .claude/skills/bake   # bake checked out at tools/bake
```
