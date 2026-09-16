// Copyright 2026 Andrea Paterno'
// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

`timescale 1ns/1ps
module accumulator_tb;
  parameter N = 16;

  reg          clk = 0;
  reg          rst = 1;
  reg          en  = 0;
  reg  [N-1:0] din = 0;
  wire [N-1:0] acc;

  accumulator DUT (.clk(clk), .rst(rst), .en(en), .din(din), .acc(acc));

  always #5 clk = ~clk;

  integer i, expected;
  initial begin
    expected = 0;
    @(negedge clk) rst = 0;
    for (i = 1; i <= 100; i = i + 1) begin
      din = i; en = 1;
      @(negedge clk);
      expected = (expected + i) % (1 << N);
      if (acc !== expected)
        $error("step %0d: expected %0d, got %0d", i, expected, acc);
    end
    $display("Test finished.");
    $finish;
  end
endmodule
