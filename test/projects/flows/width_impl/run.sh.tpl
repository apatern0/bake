#!/bin/bash
mkdir -p output
touch output/${BAKE_TOP}.v
touch output/${BAKE_TOP}.sdf
touch output/${BAKE_TOP}_tc.lib
echo "${BAKE_BLOCK} WIDTH=${BAKE_PROJ_WIDTH}" > output/vars.txt
