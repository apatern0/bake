`timescale 1ns/1ps
//# The state registers of a pixel, by the names synthesis gives their cells
//% set state = []
//% for i in range(2)
//%   do state.append("counter_reg_%d" % i)
//% endfor
//% do state.append("tac_stop_reg")
//% set netlist = "NETLIST" in BAKE_SIM_DEFINES
module tb();
  logic [7:0] hit_probe;
  wire  [7:0] zeros = {{4{1'b0}}, 4'h0};

  ${BAKE_TOP} u_core();

  //% for r in range(2)
  //%   for p in range(2)
  //%     if netlist
  //%       set pixel = "u_core.gen_regions_%d_gen_pixels_%d_u_pixel" % (r, p)
  //%     else
  //%       set pixel = "u_core.gen_regions[%d].gen_pixels[%d].u_pixel" % (r, p)
  //%     endif
  assign hit_probe[${r * 2 + p}] = ${pixel}.hit_o;
  //%     if netlist
  initial begin
    //% for reg in state
    $deposit(${pixel}.${reg}.IQ, 1'b0);
    //% endfor
  end
  //%     endif
  //%   endfor
  //% endfor
endmodule
