"""CodeBread — slice open a codebase and see its internal structure."""
from __future__ import annotations

import os
import re


def _read_version() -> str:
    """Single source of truth: pyproject.toml's [project] version.

    A source checkout (pyproject.toml sitting next to the package) wins:
    an editable `pip install -e .` freezes its metadata at install time,
    so after a version bump importlib.metadata keeps reporting the old
    number until you reinstall. Wheel installs have no pyproject.toml
    beside them and fall through to their own (always correct) metadata.
    No toml parser needed for one `version = "..."` line — keeps the
    zero-dependency promise.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
            text = f.read()
        if re.search(r"""^name\s*=\s*["']codebread["']""", text, re.M):
            m = re.search(r"""^version\s*=\s*["']([^"']+)["']""", text, re.M)
            if m:
                return m.group(1)
    except OSError:
        pass
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("codebread")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    return "0.0.0+unknown"


__version__ = _read_version()
