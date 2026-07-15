"""Connection mapper: turns per-file facts into a single graph.

Node kinds: file, function (incl. methods), table.
Edge kinds:
  call — function A calls function B
  api  — frontend fetch/axios/requests call matched to a backend route
  db   — function reads/writes a table
"""
from __future__ import annotations

import posixpath
import re
from typing import Dict, List, Optional, Tuple

from .models import FileInfo, FunctionInfo, TableInfo

COMMON_NAMES = {  # never resolve these across files by name alone
    "main", "run", "init", "setup", "get", "set", "update", "handle",
    "start", "stop", "index", "render", "log", "test", "create", "close",
    "open", "load", "save", "send", "next", "call", "apply", "toString",
    "connect", "execute", "process", "add", "remove", "push", "pop",
}

# never flag these as orphans by name alone — common framework entry points
# (constructors, lifecycle hooks, test functions) that are called implicitly
ENTRY_NAMES = {
    "main", "__init__", "__main__", "__new__", "__call__", "setup", "setUp",
    "tearDown", "run", "handler", "index", "render", "constructor",
}


def _norm_path(p: str) -> List[str]:
    """Normalize an URL/route path into comparable segments.
    ':id', '{id}', '<id>', '${...}', '{param}' all become '*'."""
    p = re.sub(r"^[a-z]+://[^/]*", "", p.strip())
    p = p.split("?")[0].split("#")[0]
    segs = []
    for s in p.split("/"):
        s = s.strip()
        if not s:
            continue
        if (s.startswith(":") or s.startswith("{") or s.startswith("<")
                or "${" in s or "{param}" in s or s.startswith("*")):
            segs.append("*")
        else:
            segs.append(s.lower())
    return segs


def _paths_match(a: List[str], b: List[str]) -> bool:
    if len(a) != len(b):
        # allow route prefixes mounted elsewhere: match on trailing segments
        if len(a) > len(b):
            a = a[-len(b):] if b else a
        else:
            b = b[-len(a):] if a else b
        if len(a) != len(b) or not a:
            return False
    return all(x == y or x == "*" or y == "*" for x, y in zip(a, b))


def _methods_match(call_m: str, route_m: str) -> bool:
    if call_m == "ANY" or route_m == "ANY":
        return True
    return bool(set(call_m.split("/")) & set(route_m.split("/")))


_RESOLVE_EXTS = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".vue", ".svelte",
                 ".py", ".php", ".rb")


def _resolve_file_ref(base_file: str, target: str, file_set) -> Optional[str]:
    """Resolve an import/include/link string to a scanned file path."""
    target = target.replace("\\", "/").strip()
    if not target or "://" in target:
        return None
    base_dir = posixpath.dirname(base_file)
    candidates = [
        posixpath.normpath(posixpath.join(base_dir, target)),
        posixpath.normpath(target.lstrip("/")),
        target.lstrip("./"),
    ]
    # python dotted modules: models / app.utils -> models.py / app/utils.py
    if "/" not in target and "." not in posixpath.basename(target):
        candidates.append(target.replace(".", "/"))
        candidates.append(posixpath.join(base_dir, target.replace(".", "/")))
    for cand in candidates:
        if cand.startswith(".."):
            continue
        if cand in file_set:
            return cand
        for ext in _RESOLVE_EXTS:
            if cand + ext in file_set:
                return cand + ext
            idx = posixpath.join(cand, "index" + ext)
            if idx in file_set:
                return idx
    return None


def _find_cycles(adj: Dict[str, List[str]]) -> List[List[str]]:
    """Iterative DFS cycle detection over a directed graph (call edges).
    Returns one representative cycle (as a list of node ids) per strongly
    connected loop found — not an exhaustive enumeration of every cycle,
    but enough to flag circular call chains without recursion-depth risk
    on large codebases."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {}
    cycles: List[List[str]] = []
    seen_keys = set()

    for start in adj:
        if color.get(start, WHITE) != WHITE:
            continue
        stack = [(start, iter(adj.get(start, [])))]
        path = [start]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                c = color.get(nxt, WHITE)
                if c == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(adj.get(nxt, []))))
                    path.append(nxt)
                    advanced = True
                    break
                elif c == GRAY:
                    idx = path.index(nxt)
                    cyc = path[idx:]
                    key = frozenset(cyc)
                    if len(cyc) > 1 and key not in seen_keys:
                        seen_keys.add(key)
                        cycles.append(cyc)
            if not advanced:
                color[stack[-1][0]] = BLACK
                stack.pop()
                path.pop()
    return cycles


def _mark_orphans_and_cycles(nodes: List[Dict], edges: List[Dict]) -> List[Dict]:
    """Flag functions/methods with no detected callers (orphans) and
    functions involved in a circular call chain. Returns the cycle list
    (each entry: {"nodes": [...], "labels": [...]}) for the UI panel."""
    call_adj: Dict[str, List[str]] = {}
    in_call_count: Dict[str, int] = {}
    for e in edges:
        if e["kind"] == "call":
            call_adj.setdefault(e["source"], []).append(e["target"])
        if e["kind"] in ("call", "api"):
            in_call_count[e["target"]] = in_call_count.get(e["target"], 0) + 1

    cycles = _find_cycles(call_adj)
    cycle_node_ids = {nid for cyc in cycles for nid in cyc}
    node_by_id = {n["id"]: n for n in nodes}

    for n in nodes:
        if n["id"] in cycle_node_ids:
            n["cycle"] = True
        if n["kind"] not in ("function", "method"):
            continue
        if n.get("routes"):
            continue
        label = n["label"]
        if label in ENTRY_NAMES or label.startswith("test_") or label.startswith("Test"):
            continue
        if in_call_count.get(n["id"], 0) == 0:
            n["orphan"] = True

    for e in edges:
        if e["kind"] == "call" and e["source"] in cycle_node_ids \
                and e["target"] in cycle_node_ids:
            e["cycle"] = True

    return [{"nodes": cyc,
             "labels": [node_by_id[nid]["label"] for nid in cyc if nid in node_by_id]}
            for cyc in cycles]


def build_graph(files: List[FileInfo], tree: Dict,
                warnings: List[Dict]) -> Dict:
    nodes: List[Dict] = []
    edges: List[Dict] = []
    edge_seen = set()

    def add_edge(src: str, dst: str, kind: str, label: str = ""):
        if src == dst:
            return
        key = (src, dst, kind)
        if key in edge_seen:
            return
        edge_seen.add(key)
        edges.append({"source": src, "target": dst, "kind": kind,
                      "label": label})

    # ---- nodes -------------------------------------------------------
    fn_nodes: Dict[Tuple[str, str], str] = {}   # (file, fn name) -> node id
    name_index: Dict[str, List[Tuple[str, FileInfo, FunctionInfo]]] = {}
    model_to_table: Dict[str, str] = {}         # ORM class name -> table node id
    table_ids: Dict[str, str] = {}

    for f in files:
        file_id = f.path
        nodes.append({
            "id": file_id, "kind": "file", "label": f.path.split("/")[-1],
            "file": f.path, "layer": f.layer, "language": f.language,
            "loc": f.loc, "warnings": f.warnings,
            "nFunctions": len(f.functions),
            "imports": f.imports[:30], "dbConfig": f.db_config,
            "source": f.source, "obfuscation": f.obfuscation,
        })
        for fn in f.functions:
            nid = f"{f.path}::{fn.name}@{fn.line}"
            fn_nodes[(f.path, fn.name)] = nid
            name_index.setdefault(fn.name, []).append((nid, f, fn))
            nodes.append({
                "id": nid, "kind": fn.kind, "label": fn.name,
                "file": f.path, "layer": f.layer, "line": fn.line,
                "endLine": fn.end_line, "params": fn.params,
                "returns": fn.returns, "description": fn.description,
                "parentClass": fn.parent_class, "index": fn.index,
                "language": f.language, "code": fn.code,
                "routes": [{"method": r.method, "path": r.path}
                           for r in fn.routes],
            })

    def table_node(t_name: str, t: Optional[TableInfo] = None) -> str:
        key = t_name.lower()
        if key in table_ids:
            nid = table_ids[key]
            if t is not None:  # enrich a placeholder with real definition
                for n in nodes:
                    if n["id"] == nid:
                        if t.fields:
                            n["fields"] = t.fields
                        if t.model:
                            n["model"] = t.model
                        if t.source:
                            n["file"] = t.source
                        break
            return nid
        nid = f"table::{key}"
        table_ids[key] = nid
        nodes.append({
            "id": nid, "kind": "table", "label": t_name,
            "layer": "database",
            "file": t.source if t else "",
            "fields": t.fields if t else [],
            "model": t.model if t else "",
        })
        return nid

    for f in files:
        for t in f.tables:
            nid = table_node(t.name, t)
            if t.model:
                model_to_table[t.model.lower()] = nid

    # ---- call edges --------------------------------------------------
    for f in files:
        local = {fn.name for fn in f.functions}
        imported_mods = {i.split("/")[-1].split(".")[-1] for i in f.imports}
        for fn in f.functions:
            src = fn_nodes[(f.path, fn.name)]
            for callee in fn.calls:
                if callee == fn.name:
                    continue
                if callee in local:
                    add_edge(src, fn_nodes[(f.path, callee)], "call",
                             f"{fn.name}() → {callee}()")
                    continue
                candidates = name_index.get(callee, [])
                if not candidates or callee in COMMON_NAMES:
                    continue
                if len(candidates) == 1:
                    add_edge(src, candidates[0][0], "call",
                             f"{fn.name}() → {callee}()")
                else:
                    # prefer a candidate whose file is imported by this file
                    hits = [c for c in candidates
                            if c[1].path.split("/")[-1].rsplit(".", 1)[0]
                            in imported_mods]
                    if len(hits) == 1:
                        add_edge(src, hits[0][0], "call",
                                 f"{fn.name}() → {callee}()")

    # ---- file-level connections ---------------------------------------
    file_set = {f.path for f in files}
    for f in files:
        fname = f.path.split("/")[-1]
        local = {fn.name: fn_nodes[(f.path, fn.name)] for fn in f.functions}
        # top-level calls: page/script code calling into functions
        for callee in f.calls:
            if callee in local:
                continue  # a file already implicitly contains its own fns
            candidates = name_index.get(callee, [])
            if not candidates or callee in COMMON_NAMES:
                continue
            if len(candidates) == 1:
                add_edge(f.path, candidates[0][0], "call",
                         f"{fname} → {callee}()")
        # includes / imports that resolve to a scanned file
        for imp in f.imports:
            tgt = _resolve_file_ref(f.path, imp, file_set)
            if tgt and tgt != f.path:
                add_edge(f.path, tgt, "include",
                         f"{fname} includes {tgt.split('/')[-1]}")
        # page navigation links (redirect/href/action)
        for ln in f.links:
            tgt = _resolve_file_ref(f.path, ln, file_set)
            if tgt and tgt != f.path:
                add_edge(f.path, tgt, "link",
                         f"{fname} links to {tgt.split('/')[-1]}")

    # ---- route index (backend endpoints) -----------------------------
    # (method, segments, handler node id, pretty label)
    route_index: List[Tuple[str, List[str], str, str]] = []
    for f in files:
        for fn in f.functions:
            nid = fn_nodes[(f.path, fn.name)]
            for r in fn.routes:
                route_index.append((r.method, _norm_path(r.path), nid,
                                    f"{r.method} {r.path}"))
        for r in f.routes:  # file-level routes referencing a handler by name
            handler_id = None
            if r.handler and (f.path, r.handler) in fn_nodes:
                handler_id = fn_nodes[(f.path, r.handler)]
            elif r.handler and len(name_index.get(r.handler, [])) == 1:
                handler_id = name_index[r.handler][0][0]
            target = handler_id or f.path
            route_index.append((r.method, _norm_path(r.path), target,
                                f"{r.method} {r.path}"))
            if handler_id:
                # mark handler node with its route
                for n in nodes:
                    if n["id"] == handler_id:
                        n.setdefault("routes", []).append(
                            {"method": r.method, "path": r.path})
                        break

    # ---- api edges (frontend call -> backend route) -------------------
    def match_route(method: str, url: str) -> Optional[Tuple[str, str]]:
        segs = _norm_path(url)
        if not segs:
            return None
        best = None
        for r_method, r_segs, target, label in route_index:
            if not _methods_match(method, r_method):
                continue
            if _paths_match(segs, r_segs):
                exact = sum(1 for x, y in zip(segs, r_segs) if x == y)
                if best is None or exact > best[0]:
                    best = (exact, target, label)
        return (best[1], best[2]) if best else None

    for f in files:
        callers = [(fn_nodes[(f.path, fn.name)], fn.api_calls)
                   for fn in f.functions]
        callers.append((f.path, f.api_calls))
        for src, api_calls in callers:
            for call in api_calls:
                hit = match_route(call.method, call.url)
                if hit:
                    add_edge(src, hit[0], "api",
                             f"{call.method} {call.url} → {hit[1]}")

    # ---- db edges ------------------------------------------------------
    for f in files:
        for fn in f.functions:
            src = fn_nodes[(f.path, fn.name)]
            for ref in fn.db_refs:
                tid = model_to_table.get(ref.table.lower()) \
                    or table_ids.get(ref.table.lower())
                if tid is None:
                    # unknown table: create it only for confident refs
                    if ref.via == "sql" or ref.table.lower() in table_ids:
                        tid = table_node(ref.table)
                    elif ref.table[0].isupper() and model_to_table:
                        continue  # unmatched model name in a modeled project
                    else:
                        tid = table_node(ref.table)
                verb = {"query": "queries", "select": "reads",
                        "insert": "inserts into", "update": "updates",
                        "delete": "deletes from",
                        "define": "defines"}.get(ref.op, ref.op)
                add_edge(src, tid, "db", f"{fn.name}() {verb} {ref.table}")

    # ---- orphans + circular dependencies --------------------------------
    cycles = _mark_orphans_and_cycles(nodes, edges)

    # ---- stats ---------------------------------------------------------
    n_fns = sum(1 for n in nodes if n["kind"] in ("function", "method"))
    n_orphans = sum(1 for n in nodes if n.get("orphan"))
    n_obfuscated = sum(1 for f in files if f.obfuscation)
    stats = {
        "files": len(files),
        "functions": n_fns,
        "tables": len(table_ids),
        "connections": len(edges),
        "routes": len(route_index),
        "warnings": len(warnings) + sum(len(f.warnings) for f in files),
        "orphans": n_orphans,
        "cycles": len(cycles),
        "obfuscated": n_obfuscated,
    }
    return {"nodes": nodes, "edges": edges, "tree": tree,
            "warnings": warnings, "cycles": cycles, "stats": stats}
