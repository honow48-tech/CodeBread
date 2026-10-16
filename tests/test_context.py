import os

from codebread.analyzer import analyze
from codebread.context import export_markdown, to_markdown

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_brief_maps_routes_tables_and_calls(tmp_path):
    md = to_markdown(analyze(FIXTURES, progress=lambda m: None))
    assert md.startswith("# fixtures: codebase context")
    for section in ("## At a glance", "## HTTP routes", "## Database tables", "## Files"):
        assert section in md
    assert "| POST | `/users` |" in md                     # route -> handler table
    assert "**users** in `sql/schema.sql`" in md          # table with its source
    assert "calls `logChange()`" in md                   # same-file call, short form
    out = export_markdown({"nodes": [], "edges": []}, str(tmp_path / "x.md"))
    assert open(out, encoding="utf-8").read().startswith("# project: codebase context")
