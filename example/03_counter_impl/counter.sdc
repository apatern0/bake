# Timing constraints for the counter: a 100 MHz clock on the clk port.
create_clock -name clk -period 10.0 [get_ports clk]
set_input_delay  2.0 -clock clk [delete_from_list [all_inputs] [get_ports clk]]
set_output_delay 2.0 -clock clk [all_outputs]
