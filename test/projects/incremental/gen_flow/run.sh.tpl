#!/bin/bash
mkdir -p output
echo 'MODE=${BAKE_GEN_MODE}' > output/gen.txt
exit $${CHECK_EXIT:-0}
