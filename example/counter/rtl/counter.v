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

`timescale 1ns/1ps
module counter #(
  parameter N=32
)(
  input clk,
  input rst,
  output reg [N-1:0] q
);

  wire [N-1:0] qNext = q+1;
  wire [N-1:0] qNextVoted = qNext;

  always @(posedge clk or posedge rst)
    if (rst)
      q <= {N{1'b1}};
    else
      q <= qNextVoted;

// synopsys translate_off
  initial
    q = $random;
// synopsys translate_on
endmodule

