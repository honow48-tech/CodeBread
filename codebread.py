#!/usr/bin/env python3
"""Convenience launcher so the spec's `python codebread.py --path ...` works
without installing the package."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codebread.cli import main

if __name__ == "__main__":
    main()
