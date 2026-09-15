# Copyright 2025 CERN
# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
# Modified version of a file from tmake (https://gitlab.cern.ch/tmake/tmake).

%.svg : %.d2
	d2 --sketch --theme=5 $< $@

all: $(addsuffix .svg, $(basename $(wildcard *.d2)))

clean:
	rm *.svg

