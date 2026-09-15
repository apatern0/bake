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

"""cocotb test for the counter, driven through counterWrapper."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer


class CounterTestbench:
    def __init__(self, dut):
        self.dut = dut

    async def reset(self):
        self.dut.rst.value = 1
        await Timer(1, "ns")
        await FallingEdge(self.dut.clk)
        self.dut.rst.value = 0

    async def check_count(self, cycles):
        width = len(self.dut.q)
        for i in range(cycles):
            await FallingEdge(self.dut.clk)
            expected = i % (1 << width)
            actual = int(self.dut.q.value)
            assert actual == expected, f"cycle {i}: expected {expected}, got {actual}"


@cocotb.test()
async def counter_cocotb_test(dut):
    """Reset the counter and check that it counts up from zero."""
    tb = CounterTestbench(dut)
    cocotb.start_soon(Clock(dut.clk, 25, "ns").start())

    await tb.reset()
    await tb.check_count(2 ** 12)
