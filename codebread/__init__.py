"""CodeBread — slice open a codebase and see its internal structure."""
from __future__ import annotations

import os


def _read_version() -> str:
    """Single source of truth: pyproject.toml's [project] version.

    Installed packages get it from the wheel's own metadata (always in
    sync with what was actually published). Running from a source
    checkout without installing falls back to reading pyproject.toml
    directly — no parser dependency needed for one `version = "..."`
    line, keeping the zero-dependency promise intact.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("codebread")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("version"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return "0.0.0+unknown"


__version__ = _read_version()
