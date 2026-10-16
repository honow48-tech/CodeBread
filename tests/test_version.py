import re

import codebread


def test_version_is_a_plain_semver_like_string():
    assert re.match(r"^\d+\.\d+\.\d+", codebread.__version__)


def test_version_is_not_the_unresolved_fallback():
    # "0.0.0+unknown" only happens if codebread is neither installed nor
    # runnable from a checkout with a readable pyproject.toml — shouldn't
    # happen in this repo's own test environment.
    assert codebread.__version__ != "0.0.0+unknown"


def test_version_follows_pyproject_in_a_checkout():
    # an editable install's metadata goes stale after a bump; the checkout's
    # pyproject.toml must win so `codebread --version` matches what you set
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(codebread.__file__)))
    with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
        declared = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    assert codebread.__version__ == declared
