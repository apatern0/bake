// A netlist of adc that disagrees with its LEF: busy is missing and start
// is an output. Non-ANSI, with the supplies as ports.
module adc (clk, start, dout, vin, VDD, VSS);
  parameter W = 3;
  input clk;
  output start;
  output [W-1:0] dout;
  inout vin;
  inout VDD, VSS;
endmodule
