// Copyright 2025 CERN
// Copyright 2026 Andrea Paterno'
// SPDX-License-Identifier: Apache-2.0
//
// This file is a modified version of a file from tmake
// (https://gitlab.cern.ch/tmake/tmake), developed at CERN and
// distributed under the Apache License, Version 2.0.
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

`timescale 1 ps / 1 ps

module counter_test;

  // - - - - - - - - - - - - - - Parameters section  - - - - - - - - - - - - - - 
  parameter N = 32;

  // - - - - - - - - - - - - - - Input/Output section  - - - - - - - - - - - - - 
  reg  clk;
  wire [N-1:0] q;
  reg  rst;

  // - - - - - - - - - - - - - Device Under Test section - - - - - - - - - - - -

  counterWrapper
`ifndef NETLIST
  #(
    .N(N)
  )
`endif
  DUT (
    .clk(clk),
    .q(q),
    .rst(rst)
  );

  integer i;
  // - - - - - - - - - - - - - Actual testbench section  - - - - - - - - - - - -
  initial
    begin
      clk=0;
      rst=1;
      @(negedge clk)
      rst=0;
      for(i=0;i<1000;i=i+1) begin
          @(negedge clk);
          if(q!=i)
              $error("Expected: %d, Actual: %d" , i, q);
      end
      $display("Test finished.");
      $finish;
    end

  localparam CLK_PERIOD = 25_000;
  always
      #(CLK_PERIOD/2) clk = !clk;
endmodule

