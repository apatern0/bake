# bake - User and Developer Guide

*bake* streamlines the design, implementation and verification of fault-tolerant ASICs. It
integrates tool-assisted redundancy insertion, simulation, and block/chip-level physical
implementation into a flexible process entirely driven by `manifest` files — plain Python files
that declare design intent, configuration, and flow selection.

One key aim is to unify and centralize file list handling and dependency management, guaranteeing
reproducible implementation and simulation results across all steps of the design flow.

## Contents

- [Introduction](introduction.md) — scope, theory of operation, step and flow discovery
- [Quick Start](quickstart.md) — step-by-step tutorial for new users
- [Installation](installation.md) — detailed installation and tab-completion setup
- [Command Line](cli.md) — every `bake` option
- [Configuration](configuration.md) — all `config` sections and template variables
- [Design Modeling](manifest_design_model.md) — `block()`, `lib()`, inheritance, hierarchical designs
- [Verification Modeling](manifest_verif_model.md) — `env()`, `test()`, simulator and framework support
- [Custom Steps](custom_steps.md) — writing and registering your own pipeline steps
- [Custom Flows](custom_flows.md) — defining custom flow directories and connecting them to steps
- [Glossary](glossary.md) — terminology reference
- [Releases](releases.md) — version history and migration notes

## Attribution

*bake* and this documentation are a modified derivative of
[tmake](https://gitlab.cern.ch/tmake/tmake), developed at CERN (Copyright 2025 CERN) and
distributed under the Apache License, Version 2.0. Modifications are Copyright 2026 Andrea
Paterno'. See `LICENSE` and `NOTICE` in the repository.
