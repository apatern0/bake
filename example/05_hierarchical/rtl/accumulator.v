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
// Accumulates `din` on every clock while `en` is high. The adder is a
// separate block so the two can be implemented and verified independently.
module accumulator #(
  parameter N = 16
)(
  input              clk,
  input              rst,
  input              en,
  input  [N-1:0]     din,
  output reg [N-1:0] acc
);
  wire [N-1:0] next;

  // No parameter override: an implemented adder is a hard macro with fixed
  // ports, so the accumulator takes the adder's own width (N = 16).
  adder u_adder (
    .a  (acc),
    .b  (din),
    .sum(next)
  );

  always @(posedge clk or posedge rst)
    if (rst)
      acc <= {N{1'b0}};
    else if (en)
      acc <= next;
endmodule
