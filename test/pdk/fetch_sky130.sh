#!/bin/sh
# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
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

# Fetch the open_pdks build of the SkyWater sky130 PDK that the test suite and
# example/03_counter_impl use to exercise the impl step. bake itself has no
# PDK dependency; this is a test fixture.
#
# Usage:  PDK_ROOT=/some/dir test/pdk/fetch_sky130.sh
#
# Installs `ciel` into the current Python environment and enables the pinned
# PDK version under $PDK_ROOT (default: ~/.ciel). Only the sky130_fd_sc_hd
# library is downloaded (~340 MB unpacked). Afterwards export PDK_ROOT and the
# built-in `sky130` flow registers itself.
set -eu

: "${PDK_ROOT:=$HOME/.ciel}"
: "${SKY130_VERSION:=1689ac3f2dc763876eaf967227c7dfe831b031ae}"

python -m pip install --quiet "ciel>=2.6"
python -m ciel enable --pdk sky130 --pdk-root "$PDK_ROOT" -l sky130_fd_sc_hd "$SKY130_VERSION"

echo "sky130 PDK enabled under $PDK_ROOT"
echo "export PDK_ROOT=$PDK_ROOT"
