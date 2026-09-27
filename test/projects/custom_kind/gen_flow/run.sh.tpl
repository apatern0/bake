#!/bin/bash
# Turns the tables into a module named after the block.
mkdir -p output
echo "// from: $BAKE_GEN_TABLES" > output/${BAKE_TOP}.v
echo "module ${BAKE_TOP}; endmodule" >> output/${BAKE_TOP}.v
