#!/bin/bash
mkdir -p output
touch output/${BAKE_TOP}.v
touch output/${BAKE_TOP}.sdf
touch output/${BAKE_TOP}_tc.lib
echo "WIDTH=${BAKE_PROJ_WIDTH} MODE=${BAKE_PROJ_MODE} FAST=${BAKE_PROJ_FAST} TAGS=${BAKE_PROJ_TAGS} RATIO=${BAKE_PROJ_RATIO} SEEN=${BAKE_SEEN_WIDTH}" > output/vars.txt
