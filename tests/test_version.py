import re

import codebread


def test_version_is_a_plain_semver_like_string():
    assert re.match(r"^\d+\.\d+\.\d+", codebread.__version__)


def test_version_is_not_the_unresolved_fallback():
    # "0.0.0+unknown" only happens if codebread is neither installed nor
    # runnable from a checkout with a readable pyproject.toml — shouldn't
    # happen in this repo's own test environment.
    assert codebread.__version__ != "0.0.0+unknown"
