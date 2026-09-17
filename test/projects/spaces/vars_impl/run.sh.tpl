#!/bin/bash
mkdir -p output
touch output/${BAKE_TOP}.v output/${BAKE_TOP}.sdf
python3 - <<'PY'
import json, os
v = json.load(open(os.environ["BAKE_VARS"]))
files = v["BAKE_DESIGN_VERILOG_FILES"]
with open("output/files.txt", "w") as f:
    f.write("\n".join(files) + "\n")
PY
