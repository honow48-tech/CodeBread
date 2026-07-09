"""Python extractor built on the stdlib `ast` module.

Extracts functions/classes/methods with params + return annotations,
call targets, Flask/FastAPI/Django routes, outgoing HTTP calls
(requests/httpx/aiohttp/urllib), ORM models (SQLAlchemy/Django/peewee/
tortoise) and raw SQL usage.
"""
from __future__ import annotations

import ast
import re
from typing import List, Optional

from ..models import (ApiCall, DbRef, FileInfo, FunctionInfo, Route,
                      TableInfo, describe)

HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}
ROUTE_ATTRS = HTTP_VERBS | {"route", "api_route", "websocket"}
ROUTE_OWNERS = {"app", "router", "api", "bp", "blueprint", "urlpatterns"}
HTTP_LIBS = {"requests", "httpx", "aiohttp", "session", "client", "urllib3"}
ORM_BASES = {"model", "base", "document", "declarativebase", "basemodel_db"}
SQL_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE)\b[\s\S]{0,200}?\b(?:FROM|INTO|UPDATE|JOIN)\s+"
    r"[`\"\[]?([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)
FIELD_CALL_RE = re.compile(r"(Column|Field)$", re.IGNORECASE)


def _unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _name_of(func) -> str:
    """Dotted name of a call target, e.g. requests.get -> 'requests.get'."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _name_of(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    if isinstance(func, ast.Call):
        return _name_of(func.func)
    return ""


def _str_arg(call: ast.Call) -> str:
    for a in call.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
        if isinstance(a, ast.JoinedStr):  # f-string url
            parts = []
            for v in a.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                else:
                    parts.append("{param}")
            return "".join(parts)
    return ""


def _params(node) -> List[str]:
    out = []
    args = node.args
    for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        p = a.arg
        if a.annotation is not None:
            ann = _unparse(a.annotation)
            if ann:
                p += f": {ann}"
        out.append(p)
    if args.vararg:
        out.append("*" + args.vararg.arg)
    if args.kwarg:
        out.append("**" + args.kwarg.arg)
    return [p for p in out if p not in ("self", "cls")]


def _route_from_decorator(dec) -> Optional[Route]:
    if not isinstance(dec, ast.Call):
        return None
    name = _name_of(dec.func)
    if "." not in name:
        return None
    owner, attr = name.rsplit(".", 1)
    owner_base = owner.split(".")[-1].lower()
    if attr.lower() not in ROUTE_ATTRS:
        return None
    if owner_base not in ROUTE_OWNERS and not owner_base.endswith("router"):
        return None
    path = _str_arg(dec)
    if not path:
        return None
    method = attr.upper() if attr.lower() in HTTP_VERBS else "ANY"
    # Flask: @app.route('/x', methods=['GET','POST'])
    for kw in dec.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
            ms = [e.value for e in kw.value.elts
                  if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if ms:
                method = "/".join(m.upper() for m in ms)
    return Route(method=method, path=path, line=dec.lineno)


def _scan_calls(node, fn: FunctionInfo, source_seg: str):
    """Collect callee names, HTTP calls, and DB touches inside a function."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            dotted = _name_of(sub.func)
            if not dotted:
                continue
            head = dotted.split(".")[0]
            tail = dotted.split(".")[-1]
            low_head, low_tail = head.lower(), tail.lower()

            # outgoing HTTP call: requests.get(url), httpx.post(...)
            if low_tail in HTTP_VERBS and low_head in HTTP_LIBS:
                url = _str_arg(sub)
                if url:
                    fn.api_calls.append(ApiCall(method=tail.upper(), url=url,
                                                line=sub.lineno))
                continue
            if dotted in ("urllib.request.urlopen", "urlopen"):
                url = _str_arg(sub)
                if url:
                    fn.api_calls.append(ApiCall(method="GET", url=url,
                                                line=sub.lineno))
                continue

            # ORM usage: session.query(User), User.objects.filter(...),
            # db.session.add(user), Model.select() ...
            if low_tail == "query" and sub.args:
                model = _name_of(sub.args[0].func if isinstance(sub.args[0], ast.Call)
                                 else sub.args[0])
                if model and model[0].isupper():
                    fn.db_refs.append(DbRef(table=model, op="query",
                                            via="orm", line=sub.lineno))
            elif ".objects." in dotted:
                model = dotted.split(".objects.")[0].split(".")[-1]
                op = {"create": "insert", "update": "update",
                      "delete": "delete"}.get(low_tail, "query")
                if model and model[0].isupper():
                    fn.db_refs.append(DbRef(table=model, op=op,
                                            via="orm", line=sub.lineno))
            elif low_tail in ("execute", "executemany", "read_sql",
                              "read_sql_query"):
                sql = _str_arg(sub)
                m = SQL_RE.search(sql or "")
                if m:
                    fn.db_refs.append(DbRef(table=m.group(2),
                                            op=m.group(1).lower(),
                                            via="sql", line=sub.lineno))

            # record the plain callee name for the call graph
            if head and head not in ("self", "cls"):
                fn.calls.append(head if "." not in dotted else tail)
            else:
                fn.calls.append(tail)

        # raw SQL sitting in a string constant
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if len(sub.value) > 12:
                m = SQL_RE.search(sub.value)
                if m:
                    fn.db_refs.append(DbRef(table=m.group(2),
                                            op=m.group(1).lower(),
                                            via="sql",
                                            line=getattr(sub, "lineno", fn.line)))
    # de-dup while keeping order
    seen = set()
    fn.calls = [c for c in fn.calls
                if c and not (c in seen or seen.add(c))]
    seen_db = set()
    fn.db_refs = [d for d in fn.db_refs
                  if not ((d.table, d.op) in seen_db or seen_db.add((d.table, d.op)))]


def _make_function(node, source: str, parent_class: str = "") -> FunctionInfo:
    fn = FunctionInfo(
        name=node.name,
        params=_params(node),
        returns=_unparse(node.returns) if node.returns else "",
        line=node.lineno,
        end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
        doc=ast.get_docstring(node) or "",
        parent_class=parent_class,
        kind="method" if parent_class else "function",
    )
    for dec in node.decorator_list:
        r = _route_from_decorator(dec)
        if r:
            fn.routes.append(r)
    _scan_calls(node, fn, source)
    try:
        seg = ast.get_source_segment(source, node) or ""
    except Exception:
        seg = ""
    fn.description = describe(fn, seg)
    return fn


def _model_from_class(node: ast.ClassDef) -> Optional[TableInfo]:
    """SQLAlchemy / Django / peewee / tortoise model -> TableInfo."""
    base_names = []
    for b in node.bases:
        base_names.append(_name_of(b).split(".")[-1].lower())
    is_model = any(b in ORM_BASES or b.endswith("model") for b in base_names)
    if not is_model:
        return None
    table = node.name.lower()
    fields: List[str] = []
    for item in node.body:
        if isinstance(item, ast.Assign):
            targets = [t.id for t in item.targets if isinstance(t, ast.Name)]
            if targets and targets[0] == "__tablename__" and \
                    isinstance(item.value, ast.Constant):
                table = str(item.value.value)
                continue
            if targets and isinstance(item.value, ast.Call):
                callee = _name_of(item.value.func).split(".")[-1]
                if FIELD_CALL_RE.search(callee) or callee in (
                        "relationship", "ForeignKey", "ManyToManyField"):
                    fields.append(targets[0])
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            fields.append(item.target.id)
    return TableInfo(name=table, model=node.name, fields=fields,
                     line=node.lineno)


def parse_python(info: FileInfo, text: str) -> None:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        info.warnings.append(f"Python syntax error at line {exc.lineno}: "
                             f"{exc.msg} — file skipped.")
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                info.imports.extend(a.name for a in node.names)
            elif node.module:
                info.imports.append(node.module)

    def visit_body(body, parent_class=""):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                info.functions.append(_make_function(node, text, parent_class))
                # nested defs
                inner = [n for n in node.body
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                if inner:
                    visit_body(inner, parent_class)
            elif isinstance(node, ast.ClassDef):
                model = _model_from_class(node)
                if model:
                    model.source = info.path
                    info.tables.append(model)
                visit_body(node.body, parent_class=node.name)

    visit_body(tree.body)

    # Django urls.py: path('users/', views.user_list) -> route + handler name
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _name_of(node.func).split(".")[-1]
            if callee in ("path", "re_path", "url") and len(node.args) >= 2:
                p = _str_arg(node)
                handler = _name_of(node.args[1]).split(".")[-1]
                if p and handler:
                    info.routes.append(Route(method="ANY", path="/" + p.strip("/"),
                                             line=node.lineno, handler=handler))

    # module-level calls (script-style code outside any def)
    fn_ranges = [(f.line, max(f.end_line, f.line)) for f in info.functions]
    seen_top = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        line = getattr(node, "lineno", 0)
        if any(s <= line <= e for s, e in fn_ranges):
            continue
        dotted = _name_of(node.func)
        name = dotted.split(".")[0] if "." not in dotted else \
            dotted.split(".")[-1]
        if name and name not in seen_top:
            seen_top.add(name)
            info.calls.append(name)
    info.calls = info.calls[:40]

    info.imports = sorted(set(info.imports))
