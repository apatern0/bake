# Security

`bake` executes `manifest` files and flow scripts as trusted Python and shell code with the
full permissions of the invoking user. Never run `bake` on a project you do not trust; a manifest
can do anything a Python script can.

To report a vulnerability in `bake` itself, please use GitHub's private vulnerability reporting
on this repository rather than a public issue. You will get an acknowledgement within a week.
