#!/bin/bash
mkdir -p output
echo 'BLOCK=${BAKE_BLOCK} TOP=${BAKE_TOP} IS_LAST=${BAKE_CHECK_IS_LAST}' > output/check_result.txt
