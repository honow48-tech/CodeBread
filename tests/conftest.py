"""Shared pytest fixtures/helpers."""
from __future__ import annotations

import os

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture_path(*parts: str) -> str:
    return os.path.join(FIXTURES_DIR, *parts)


def read_fixture(*parts: str) -> str:
    with open(fixture_path(*parts), "r", encoding="utf-8") as f:
        return f.read()
