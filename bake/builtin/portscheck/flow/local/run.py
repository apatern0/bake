#!/usr/bin/env python3
# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The built-in portscheck flow: compares the ports of the block's views
with bake.ports and writes portscheck.md and portscheck.json. It runs under
bake's interpreter (its first line leaves the interpreter to PATH).

$BAKE_PORTSCHECK_VIEWS lists [view, label, files] for each view; it exits 1
on an error $BAKE_PORTSCHECK_WAIVE does not waive, and on a warning too with
$BAKE_PORTSCHECK_STRICT."""

import dataclasses
import json
import logging
import os
import sys

from bake import ports

logging.basicConfig(level=logging.INFO, format="[portscheck] %(levelname)s\t %(message)s", force=True)


def main() -> int:
    with open(os.environ["BAKE_VARS"], encoding="utf-8") as f:
        bake_vars = json.load(f)
    top = bake_vars["BAKE_TOP"]
    views = []
    for view, label, paths in bake_vars["BAKE_PORTSCHECK_VIEWS"]:
        interface = ports.read(view, paths, top)
        interface.name = label
        views.append(interface)
    findings = ports.waive(ports.compare(views), bake_vars["BAKE_PORTSCHECK_WAIVE"])

    outdir = bake_vars["BAKE_PORTSCHECK_OUTDIR"]
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "portscheck.md"), "w", encoding="utf-8") as f:
        f.write(ports.report(views, findings))
    with open(os.path.join(outdir, "portscheck.json"), "w", encoding="utf-8") as f:
        json.dump({"cell": top,
                   "views": [{"name": v.label, "view": v.view, "source": v.source, "ports": len(v.ports),
                              "notes": v.notes}
                             for v in views],
                   "findings": [dataclasses.asdict(x) for x in findings]}, f, indent=2)

    failing = ("error", "warning") if bake_vars["BAKE_PORTSCHECK_STRICT"] else ("error",)
    for x in findings:
        log = logging.error if x.severity in failing and not x.waived else logging.warning
        log("%s: %s%s", x.port, x.message, f" (waived: {x.waived})" if x.waived else "")
    failed = [x for x in findings if x.severity in failing and not x.waived]
    if failed:
        logging.error("%d finding(s) on the ports of %s: see %s", len(failed), top,
                      os.path.join(outdir, "portscheck.md"))
        return 1
    logging.info("The %d views of %s agree on its ports (%d finding(s) waived or warnings)",
                 len(views), top, len(findings))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ports.PortsError as e:
        logging.error("%s", e)
        sys.exit(1)
