"""Exports: graph JSON (re-loadable) and a single-file static HTML."""
from __future__ import annotations

import json
import os
from typing import Dict

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def export_json(graph: Dict, out_path: str) -> str:
    out_path = os.path.abspath(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=1)
    return out_path


def load_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def export_html(graph: Dict, out_path: str) -> str:
    """Inline CSS+JS+data into one shareable HTML file."""
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(WEB_DIR, "style.css"), encoding="utf-8") as f:
        css = f.read()
    with open(os.path.join(WEB_DIR, "app.js"), encoding="utf-8") as f:
        js = f.read()

    data = json.dumps(graph, ensure_ascii=False)
    data = data.replace("</", "<\\/")  # keep </script> out of the payload
    html = html.replace(
        '<link rel="stylesheet" href="style.css">',
        f"<style>\n{css}\n</style>")
    html = html.replace(
        '<script src="app.js"></script>',
        f"<script>window.CODEBREAD_DATA = {data};</script>\n"
        f"<script>\n{js}\n</script>")

    out_path = os.path.abspath(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
