#!/bin/bash
mkdir -p output
echo "module ${BAKE_TOP}(); endmodule" > output/${BAKE_TOP}.v
touch output/${BAKE_TOP}.sdf
touch output/${BAKE_TOP}_tc.lib
