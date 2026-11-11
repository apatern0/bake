`timescale 1ns/1ps
// ${BAKE_BLOCK}: one pixel per region
module ${BAKE_TOP}();
  //% for r in range(2)
  pixel u_pixel_${r}();
  //% endfor
endmodule
