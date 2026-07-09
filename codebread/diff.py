"""Diff two exported graph JSONs to see what changed between scans."""
from __future__ import annotations

from typing import Dict, List, Tuple


def _index_files(graph: Dict) -> Dict[str, Dict]:
    return {n["id"]: n for n in graph.get("nodes", []) if n["kind"] == "file"}


def _index_functions(graph: Dict) -> Dict[str, Dict]:
    out = {}
    for n in graph.get("nodes", []):
        if n["kind"] in ("function", "method"):
            out[f"{n.get('file', '')}::{n.get('label', '')}"] = n
    return out


def _index_tables(graph: Dict) -> Dict[str, Dict]:
    return {n["label"].lower(): n for n in graph.get("nodes", []) if n["kind"] == "table"}


def compute_diff(old: Dict, new: Dict) -> Dict:
    """Compare two graph dicts (as produced by analyzer.analyze / loaded
    from export_json) and return what was added, removed and changed."""
    old_files, new_files = _index_files(old), _index_files(new)
    old_fns, new_fns = _index_functions(old), _index_functions(new)
    old_tables, new_tables = _index_tables(old), _index_tables(new)

    files_added = sorted(set(new_files) - set(old_files))
    files_removed = sorted(set(old_files) - set(new_files))

    fn_added = sorted(set(new_fns) - set(old_fns))
    fn_removed = sorted(set(old_fns) - set(new_fns))
    fn_changed: List[Tuple[str, List[str]]] = []
    for key in sorted(set(old_fns) & set(new_fns)):
        a, b = old_fns[key], new_fns[key]
        diffs = []
        if a.get("params") != b.get("params"):
            diffs.append(f"params {a.get('params')} -> {b.get('params')}")
        if a.get("returns") != b.get("returns"):
            diffs.append(f"returns {a.get('returns')!r} -> {b.get('returns')!r}")
        if a.get("line") != b.get("line"):
            diffs.append(f"moved line {a.get('line')} -> {b.get('line')}")
        if diffs:
            fn_changed.append((key, diffs))

    tables_added = sorted(set(new_tables) - set(old_tables))
    tables_removed = sorted(set(old_tables) - set(new_tables))
    tables_changed: List[Tuple[str, List[str], List[str]]] = []
    for key in sorted(set(old_tables) & set(new_tables)):
        a, b = old_tables[key], new_tables[key]
        af, bf = set(a.get("fields") or []), set(b.get("fields") or [])
        if af != bf:
            tables_changed.append((key, sorted(bf - af), sorted(af - bf)))

    old_stats, new_stats = old.get("stats", {}), new.get("stats", {})
    stats_delta = {k: new_stats.get(k, 0) - old_stats.get(k, 0)
                   for k in set(old_stats) | set(new_stats)}

    return {
        "files_added": files_added, "files_removed": files_removed,
        "functions_added": fn_added, "functions_removed": fn_removed,
        "functions_changed": fn_changed,
        "tables_added": tables_added, "tables_removed": tables_removed,
        "tables_changed": tables_changed,
        "stats_delta": stats_delta,
        "old_meta": old.get("meta", {}), "new_meta": new.get("meta", {}),
    }


def format_diff_report(d: Dict) -> str:
    lines = []
    om, nm = d["old_meta"], d["new_meta"]
    lines.append(f"Diff: {om.get('name', 'old')} ({om.get('scannedAt', '?')})  ->  "
                 f"{nm.get('name', 'new')} ({nm.get('scannedAt', '?')})")
    lines.append("")

    def bucket(title: str, added: List[str], removed: List[str]) -> None:
        if not added and not removed:
            return
        lines.append(title)
        for x in added:
            lines.append(f"  + {x}")
        for x in removed:
            lines.append(f"  - {x}")
        lines.append("")

    bucket("Files:", d["files_added"], d["files_removed"])
    bucket("Functions:", d["functions_added"], d["functions_removed"])
    if d["functions_changed"]:
        lines.append("Functions changed:")
        for key, diffs in d["functions_changed"]:
            lines.append(f"  ~ {key}")
            for line in diffs:
                lines.append(f"      {line}")
        lines.append("")
    bucket("Tables:", d["tables_added"], d["tables_removed"])
    if d["tables_changed"]:
        lines.append("Table fields changed:")
        for key, added, removed in d["tables_changed"]:
            bits = []
            if added:
                bits.append("+" + ",".join(added))
            if removed:
                bits.append("-" + ",".join(removed))
            lines.append(f"  ~ {key}: {'; '.join(bits)}")
        lines.append("")

    nonzero = {k: v for k, v in d["stats_delta"].items() if v}
    if nonzero:
        lines.append("Stats delta:")
        for k, v in sorted(nonzero.items()):
            sign = "+" if v > 0 else ""
            lines.append(f"  {k}: {sign}{v}")
        lines.append("")

    if not any([d["files_added"], d["files_removed"], d["functions_added"],
                d["functions_removed"], d["functions_changed"],
                d["tables_added"], d["tables_removed"], d["tables_changed"]]):
        lines.append("No structural changes detected.")

    return "\n".join(lines)
