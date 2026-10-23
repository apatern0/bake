#!/usr/bin/env python3
# Records the interpreter bake ran this flow with.
import os
import sys

os.makedirs("output", exist_ok=True)
with open("output/python.txt", "w", encoding="utf-8") as out:
    out.write(sys.executable)
