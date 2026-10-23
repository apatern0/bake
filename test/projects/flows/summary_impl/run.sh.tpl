#!/bin/bash
# Writes the outputs of an impl step and a summary.json from the proj
# section; fails when proj.fail is set. In a sweep, it keeps the sweep's
# report as it stood when the run started, in report_seen.md.
cp ../../../../report.md report_seen.md 2>/dev/null || true
sleep ${BAKE_PROJ_SLEEP}
mkdir -p output
touch output/${BAKE_TOP}.v output/${BAKE_TOP}.sdf output/${BAKE_TOP}_tc.lib
cat > summary.json <<SUMMARY
{"status": "completed", "stage": "route",
 "metrics": [{"name": "area", "label": "Area", "value": $((${BAKE_PROJ_WIDTH} * 10)), "unit": "um2"},
             {"name": "density", "label": "Density", "value": ${BAKE_PROJ_WIDTH}.5, "unit": "%"}],
 "notes": ["width ${BAKE_PROJ_WIDTH}"],
 "inspect": [{"what": "netlist", "command": "cat output/${BAKE_TOP}.v", "then": "read it"}]}
SUMMARY
if [ "${BAKE_PROJ_FAIL}" = "1" ]; then
    echo "ERROR: failing as asked" >&2
    exit 1
fi
