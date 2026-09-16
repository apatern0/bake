#!/bin/bash
mkdir -p output
touch output/${BAKE_TOP}.v
touch output/${BAKE_TOP}.sdf
touch output/${BAKE_TOP}_tc.lib
echo ${BAKE_CUSTOM_VAR} > output/custom_var.txt
