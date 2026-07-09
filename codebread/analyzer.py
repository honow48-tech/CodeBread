"""Orchestrates: scan -> parse -> classify -> connect -> graph dict."""
from __future__ import annotations

import datetime
import os
import sys
from typing import Callable, Dict, Optional

from . import __version__
from .classifier import classify
from .connections import build_graph
from .parsers import parse_file
from .scanner import read_text, scan


def analyze(root: str,
            progress: Optional[Callable[[str], None]] = None) -> Dict:
    """Run the full pipeline on `root` and return the graph dict."""
    say = progress or (lambda msg: None)
    root = os.path.abspath(root)

    say(f"Scanning {root} ...")
    result = scan(root)
    files_meta = result["files"]
    warnings = result["warnings"]
    say(f"  found {len(files_meta)} scannable files")

    parsed = []
    unsupported = {}
    for i, meta in enumerate(files_meta, 1):
        text, err = read_text(meta["abspath"])
        info = parse_file(meta["path"], text, meta["language"])
        if err:
            info.warnings.append(err)
        info.layer = classify(info, text)
        if info.parsed or info.language in ("html", "css"):
            info.source = text if len(text) <= 300_000 else \
                text[:300_000] + "\n… (truncated)"
        parsed.append(info)
        for w in info.warnings:
            if w.startswith("Unsupported:"):
                unsupported.setdefault(meta["language"], 0)
                unsupported[meta["language"]] += 1
            warnings.append({"path": meta["path"], "message": w})
        if i % 50 == 0:
            say(f"  parsed {i}/{len(files_meta)} files")

    for lang, count in sorted(unsupported.items()):
        say(f"  note: {count} file(s) in {lang} - no parser available, "
            f"shown as unsupported in the UI")

    say("Mapping connections ...")
    _annotate_tree(result["tree"], {f.path: f for f in parsed})
    graph = build_graph(parsed, result["tree"], warnings)
    graph["meta"] = {
        "root": root,
        "name": os.path.basename(root) or root,
        "scannedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "version": __version__,
    }
    s = graph["stats"]
    say(f"Done: {s['files']} files, {s['functions']} functions, "
        f"{s['tables']} tables, {s['connections']} connections, "
        f"{s['warnings']} warnings")
    return graph


def _annotate_tree(node: Dict, by_path: Dict) -> None:
    """Copy layer/warning info onto tree nodes for the sidebar."""
    if node.get("type") == "file":
        info = by_path.get(node.get("path"))
        if info is not None:
            node["layer"] = info.layer
            node["nFunctions"] = len(info.functions)
            if info.warnings and "warning" not in node:
                node["warning"] = "parse"
        return
    layers = set()
    for child in node.get("children", []):
        _annotate_tree(child, by_path)
        if child.get("layer") and child["layer"] not in ("unknown", None):
            layers.add(child["layer"])
    if len(layers) == 1:
        node["layer"] = layers.pop()
