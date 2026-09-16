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
// Test bench parametrised through a define set by the manifest.
`ifndef WIDTH
`define WIDTH 8
`endif

module counter_width_tb;
  localparam N = `WIDTH;

  reg          clk = 0;
  reg          rst = 1;
  wire [N-1:0] q;

  counter #(.N(N)) DUT (.clk(clk), .rst(rst), .q(q));

  always #5 clk = ~clk;

  integer i;
  initial begin
    @(negedge clk) rst = 0;
    // Run past the wrap-around point to check that the width is really N.
    for (i = 0; i < (1 << N) + 3; i = i + 1) begin
      @(negedge clk);
      if (q !== (i % (1 << N)))
        $error("N=%0d, cycle %0d: expected %0d, got %0d", N, i, i % (1 << N), q);
    end
    $display("Test finished (N=%0d).", N);
    $finish;
  end
endmodule
