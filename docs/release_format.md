# Release Format

A **release** is an implemented block saved so that other blocks can use it without building
it: its netlist and abstracts (what a parent needs of a hard macro), a description of where they
come from and how they fared in their checks, and the checksums of every file. A release never
changes once it is written.

This page describes the format, which *bake* writes and reads, and the
[source file](#source-files) of a block made outside the project (an analog block, say), from
which *bake* makes its releases.

## Where releases live

Releases are kept under one or more **release roots**, one directory per project, block and
version:

```
<root>/<project>/<block>/<version>/
  release.json
  SHA256SUMS
  netlist/  lef/  liberty/<corner>/  si/<corner>/  sdf/<corner>/  def/  sdc/  spef/<corner>/
  stream/  lvs/  reports/
  macros/<block>/...
```

- `<project>` is the name the top manifest gives `project()`; `_` for an unnamed project.
- `<version>` takes letters, digits and `. _ -`, and does not start with `.` or `-`. A directory
  whose name starts with `.` is a release being written, and is not read.
- A view's files are in the directory named after the view (the LEF of `physical_lef` goes in
  `lef/`), in a subdirectory per corner for the views that have corners. The hard macros the
  block places are under `macros/<block>/`, laid out the same way.
- Every file and directory of a release is read-only.

When a version is found under several roots, the first root's is used, with a warning if its
`SHA256SUMS` differs from the others'.

## Views

A **view** is one kind of file of a release. Each one is a field of the implemented block's
data (`LibData`), the fields that `impl` fills and that `macro()` declares:

| View | Field | Shape | Content |
|---|---|---|---|
| `netlist` | `netlist_files` | files | Verilog to simulate (gate-level, or a model) |
| `lef` | `layout_info` | files | the abstract |
| `liberty` | `liberty_files` | files per corner | timing and power |
| `si` | `si_files` | files per corner | signal-integrity models |
| `sdf` | `sdf_files` | a file per corner | annotated delays |
| `def` | `def_file` | a file | the placed and routed design |
| `physical_lef` | `physical_lef` | a file | every LEF the DEF refers to |
| `sdc` | `sdc_file` | a file | the constraints |
| `spef` | `parasitics_files` | a file per corner | extracted parasitics |
| `stream` | `stream_files` | files | the layout (GDS, OASIS) |
| `lvs` | `lvs_files` | files | netlists for LVS (CDL, SPICE) |

A release need not have every view: one made for an early floorplan may hold only its LEF.

## `release.json`

```json
{
  "format": 1,
  "block": "core",
  "top": "core",
  "version": "20261118-edef189",
  "label": "routing in progress",
  "created": "2026-11-18T10:12:00+01:00",
  "project": {"name": "chip", "options": {"pixel_pitch": 100}},
  "recipe": "impl",
  "producer": {"kind": "publish", "bake_version": "1.5.0",
               "git": {"commit": "edef189…", "dirty": false}},
  "data": {
    "netlist_files": ["netlist/core.v"],
    "netlist_incdirs": [],
    "layout_info": "lef/core.lef",
    "liberty_files": {"SS": ["liberty/SS/core_SS.lib"], "TT": ["liberty/TT/core_TT.lib"]},
    "si_files": {},
    "sdf_files": {"default": "sdf/default/core.sdf"},
    "def_file": "def/core.def.gz",
    "physical_lef": "lef/core.libs.lef",
    "sdc_file": "sdc/core.sdc",
    "parasitics_files": {"SS": "spef/SS/core.SS.spef.gz"},
    "stream_files": ["stream/core.gds"],
    "lvs_files": ["lvs/core.cdl"],
    "libs": ["stdcells"],
    "vrf_defines": ["NETLIST"],
    "macros": [{"block": "frontend", "top": "frontend", "dir": "macros/frontend", "…": "…"}]
  },
  "placeholders": ["liberty_files.TT"],
  "checks": {
    "integrity": {"status": "pass", "details": []},
    "quality": {
      "drc": {"status": "fail", "value": 12, "report": "reports/drc.rpt"},
      "timing": {"status": "pass", "value": {"SS": 0.12}}
    }
  },
  "sources": {"root": "project", "files": {"rtl/core.v": "<sha256>"}}
}
```

| Key | Meaning |
|---|---|
| `format` | The format's version; *bake* refuses one it does not know |
| `block`, `top`, `version` | What the release is: the block, its top unit, the version |
| `label` | A note for people (`bake` shows it), with no effect |
| `created` | When it was written (ISO 8601) |
| `project` | The project it was built in and the values of its options: a build that uses the release must have the same |
| `recipe` | The recipe that built it (`impl`); empty for a release made outside *bake* |
| `producer` | Who made it: the *bake* version and the git state of the project (`kind` `publish`), or, for an [external block](#source-files) (`kind` `external`), its source file, when each of its files was last modified and the source file's `[provenance]` (`notes`) |
| `data` | The views, with paths relative to the release directory; `libs`, the cell libraries the netlist is mapped to, by name; `vrf_defines`, what a simulation of its netlist defines; `macros`, the hard macros it places, each with the same keys and its `dir` |
| `placeholders` | Views (`<field>` or `<field>.<corner>`) holding stand-ins, not the real thing |
| `checks` | `integrity`: whether the views agree with each other; `quality`: one entry per check (`status` `pass`, `fail` or `skipped`, an optional `value` and `report`) |
| `sources` | The digest of every source file it was built from, by path relative to the top project's directory (`root` `project`), to tell when the release is older than the sources; for an external block, the digest of each file its source file names, by absolute path (`root` `external`) |

A build that uses a release resolves `libs` against the libraries the project declares, and
refuses a release mapped to a library it does not have.

## `SHA256SUMS`

The SHA-256 of every file of the release but itself, one per line, as `sha256sum` writes them
(`<digest>  <path>`), sorted by path.

## Integrity

A release is refused, by `publish`, when it fails its integrity checks,
the checks that tell whether it can be used at all:

- it has at least one view, and each placeholder names a file of it;
- every view that declares the top unit's ports declares the same ones: the netlist's module,
  the LEF macro, the Liberty cell and the LVS subcircuit; bus bits (`a[3]`, `a<3>`) count as
  their bus, and power pins (a LEF pin with `USE POWER` or `GROUND`, a Liberty `pg_pin`, a pin
  the profile names) are left out;
- a port has the same direction in every view that gives one;
- with a profile, its Liberty corners are the profile's.

## Profiles

A **profile** says what a project needs of a release, for each use it makes of it. It is a TOML
file the project keeps; `config.publish.profile` names the one a release is checked
against when it is published:

```toml
[profile]
name = "hard_macro"
corners = ["TT", "SS", "FF"]       # the Liberty corners a release may have
power_pins = ["VDD", "VSS"]        # left out of the port comparison

[uses.vrf]
needs = ["netlist"]
[uses.floorplan]
needs = ["lef"]
[uses.impl]
needs = ["lef", "liberty", "netlist"]
[uses.signoff]
needs = ["stream", "lvs"]

[checks]                           # handed as it is to a checks directory
max_layer = "M4"
```

A use is `ok` when the release has every view it needs, `placeholder` when one of them is a
stand-in, `missing` otherwise. A release that is missing a view is still usable for the uses
it serves: an early release with only its LEF serves a floorplan.

## Checks directories

What a release must satisfy that depends on the technology (the layers its abstract uses, where
its pins are) is checked by a **checks directory**: a directory with a `run.py`, which
the publish step runs (`config.publish.checks`) with the Python
*bake* runs in, in an empty directory, with

| Variable | Content |
|---|---|
| `BAKE_RELEASE_DIR` | the release's directory |
| `BAKE_CHECKS_OPTIONS` | a JSON file holding the profile's `[checks]` table |
| `BAKE_CHECKS_OUT` | where to write the results: `{check: {"status": "pass" \| "fail" \| "skipped", "value": ..., "report": ...}}` |

A script that exits non-zero or writes no results is an error; a failing check is not.

## Source files

A block made outside the project, an analog block say, is declared with
`external(name=..., source="<file>.ini")` (see
[External blocks](manifest_design_model.md#external-blocks)). Its source file is an INI file its
makers fill in once, saying where its views are; they need not know *bake*. Each hand-over,
`bake <block> publish` makes a release of the files it names, as they are then.

```ini
[block]
name = adc                  ; as the project's external() names it
top = adc_top               ; its top cell
placeholders = liberty.SS   ; views holding a stand-in, not the real thing (optional)

[views]
netlist = export/adc.v
lef = export/adc.lef
stream = export/adc.gds
lvs = export/adc.cdl

[liberty]                   ; one key per corner
TT = export/adc_tt.lib
SS = export/adc_ss.lib

[provenance]                ; anything worth keeping about where it comes from
library = ADC_LIB
```

| Section | Keys |
|---|---|
| `[block]` | `name`, `top` (required); `placeholders`, as `VIEW[.CORNER]` |
| `[views]` | `netlist`, `lef`, `def`, `physical_lef`, `sdc`, `stream` (GDS, OASIS), `lvs` (CDL, SPICE), `libs` (cell libraries the netlist is mapped to, which a project must declare); see [Views](#views) |
| `[liberty]`, `[si]`, `[sdf]`, `[spef]` | One key per corner: `CORNER = FILE ...` (one file for `sdf` and `spef`) |
| `[provenance]` | Any keys, kept in `release.json` as the producer's `notes` |

Paths are relative to the source file, and may use `~` and `$VARIABLES`. A key that takes
several files takes them separated by spaces or new lines (quote a path with spaces). An
unknown section or key, a missing file, and a `name` or `top` other than the project's are
refused. The source file is kept in the release's `reports/`.

What changes from one hand-over to the next is not in the file: the version, the label and the
release root are the project's (`config.publish`), and so are the values of its options, which
the release records like any other.
