#!/usr/bin/env python3
"""Pre-rename entry point, kept so old commands and native installs still work.

This service is now Smartt (Smart Attendance Record Tracking Tajuddin); the real
entry point is smartt.py. Datang.my is the vendor API Smartt reports taps to.
"""

import os
import runpy

if __name__ == "__main__":
    runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "smartt.py"),
                   run_name="__main__")
