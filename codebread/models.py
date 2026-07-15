"""Shared data structures for scan results."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class ApiCall:
    """An outgoing HTTP call found in source (fetch/axios/requests/...)."""
    method: str          # GET/POST/... or ANY
    url: str             # raw url/path as written
    line: int = 0


@dataclass
class Route:
    """A server route definition (@app.route, app.get, @GetMapping, ...)."""
    method: str          # GET/POST/... or ANY
    path: str
    line: int = 0
    handler: str = ""    # handler function name, if separate from the decorated fn


@dataclass
class DbRef:
    """A database touch: ORM model usage or raw SQL."""
    table: str           # table/collection/model name as written
    op: str = "query"    # query/insert/update/delete/define
    via: str = "orm"     # orm | sql
    line: int = 0


@dataclass
class FunctionInfo:
    name: str
    params: List[str] = field(default_factory=list)
    returns: str = ""
    line: int = 0
    end_line: int = 0
    doc: str = ""
    description: str = ""
    calls: List[str] = field(default_factory=list)      # names of callees
    api_calls: List[ApiCall] = field(default_factory=list)
    routes: List[Route] = field(default_factory=list)   # routes this fn handles
    db_refs: List[DbRef] = field(default_factory=list)
    parent_class: str = ""
    kind: str = "function"   # function | method
    index: int = 0           # "Function 1", "Function 2" ... per file
    code: str = ""           # source snippet (capped), for the UI viewer


@dataclass
class TableInfo:
    """A DB table/collection/model definition."""
    name: str            # table name
    model: str = ""      # ORM class name, if any
    fields: List[str] = field(default_factory=list)
    line: int = 0
    source: str = ""     # file that defines it


@dataclass
class FileInfo:
    path: str            # relative, forward slashes
    language: str = "unknown"
    layer: str = "unknown"   # frontend | backend | database | config | unknown
    parsed: bool = False
    loc: int = 0
    imports: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)       # top-level calls
    links: List[str] = field(default_factory=list)       # page navigations
    functions: List[FunctionInfo] = field(default_factory=list)
    tables: List[TableInfo] = field(default_factory=list)
    api_calls: List[ApiCall] = field(default_factory=list)   # top-level calls
    routes: List[Route] = field(default_factory=list)        # top-level route defs
    db_refs: List[DbRef] = field(default_factory=list)       # top-level db refs
    warnings: List[str] = field(default_factory=list)
    db_config: List[str] = field(default_factory=list)       # masked config lines
    source: str = ""                                          # full text (capped)
    obfuscation: List[Dict] = field(default_factory=list)     # decoded literals (see deobfuscate.py)

    def to_dict(self):
        return asdict(self)


def humanize(name: str) -> str:
    """Turn get_user_by_id / getUserById into 'Get user by id'."""
    import re
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    s = s.replace("_", " ").replace("-", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return (s[:1].upper() + s[1:]) if s else name


def describe(fn: FunctionInfo, body_hint: str = "") -> str:
    """Auto-description: docstring first line, else heuristic summary."""
    if fn.doc:
        first = fn.doc.strip().splitlines()[0].strip()
        if first:
            return first
    hints = []
    if fn.routes:
        r = fn.routes[0]
        hints.append(f"handles {r.method} {r.path}")
    if fn.api_calls:
        hints.append("calls an API")
    if fn.db_refs:
        tables = sorted({d.table for d in fn.db_refs})
        hints.append("queries " + ", ".join(tables[:3]))
    low = body_hint.lower()
    if not hints:
        if "open(" in low or "readfile" in low or "writefile" in low:
            hints.append("reads/writes files")
        elif "render" in low or "jsx" in low or "createelement" in low:
            hints.append("renders UI")
    base = humanize(fn.name)
    if hints:
        return f"{base} — {'; '.join(hints)}."
    return base + "."
