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

`ifdef TMR
module counterVoter (inA, inB, inC, out, tmrErr);
  parameter WIDTH = 1;
  input   [(WIDTH-1):0]   inA, inB, inC;
  output  [(WIDTH-1):0]   out;
  output                  tmrErr;
  reg                     tmrErr;
  assign out = (inA&inB) | (inA&inC) | (inB&inC);
  always @(inA or inB or inC)
  begin
    if (inA!=inB || inA!=inC || inB!=inC)
      tmrErr = 1;
    else
      tmrErr = 0;
  end
endmodule
`endif

module counterWrapper#(
  parameter N=32
)(
  input clk,
  input rst,
  output [N-1:0] q
);


`ifdef TMR
  // fanout for clk
  wire  clkA=clk;
  wire  clkB=clk;
  wire  clkC=clk;
  // voter for q
  wire [N-1:0] qA;
  wire [N-1:0] qB;
  wire [N-1:0] qC;
  wire qtmrErr;
  counterVoter #(.WIDTH(((N-1) > (0)) ? ((N-1) - (0) + 1) : ((0) - (N-1) + 1) )) qVoter (
    .inA(qA),
    .inB(qB),
    .inC(qC),
    .out(q),
    .tmrErr(qtmrErr)
  );
  // fanout for rst
  wire  rstA=rst;
  wire  rstB=rst;
  wire  rstC=rst;
  counterTMR
`ifndef NETLIST
  #(
    .N(N)
  )
`endif
  DUT (
    .clkA(clkA),
    .clkB(clkB),
    .clkC(clkC),
    .qA(qA),
    .qB(qB),
    .qC(qC),
    .rstA(rstA),
    .rstB(rstB),
    .rstC(rstC)
  );
`else
  counter
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
`endif

// - - - - - - - - - - - - Timing annotation section - - - - - - - - - - - - - 
`ifdef NETLIST
  initial
`ifdef TMR
    $sdf_annotate("counterTMR.sdf", DUT, ,"sdf.log");
`else
    $sdf_annotate("counter.sdf", DUT, ,"sdf.log");
`endif
`endif

// - - - - - - - - - - - - - - - VDD section - - - - - - - - - - - - - - - - - 

`ifdef VCD
  initial begin
     $dumpfile("counter.vcd");
     $dumpvars(0, DUT);
  end
`endif
endmodule

