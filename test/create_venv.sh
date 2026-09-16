#!/bin/bash
# Copyright 2025 CERN
# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
#
# This file is a modified version of a file from tmake
# (https://gitlab.cern.ch/tmake/tmake), developed at CERN and
# distributed under the Apache License, Version 2.0.
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

# Creates a development virtualenv with bake and its test dependencies.
# Set BAKE_WITH_TMRG=1 to also install tmrg (needed by the tmr step and its tests).
set -e
python3 -m venv venv
. venv/bin/activate
pip install --upgrade pip
pip install -e ".[test]"

if [ "${BAKE_WITH_TMRG:-0}" = "1" ]; then
    mkdir -p utils && cd utils
    [ -d tmrg ] || git clone https://github.com/rlf-arlut/tmrg.git
    pip install -e tmrg
    cd ..
fi
