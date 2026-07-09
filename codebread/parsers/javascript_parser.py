"""JavaScript / TypeScript extractor (regex + brace matching).

Handles: function declarations, arrow/const functions, classes + methods,
imports, Express/Fastify/Koa route definitions, NestJS decorators,
fetch/axios API calls, and Mongoose/Prisma/Sequelize/Knex/raw-SQL DB usage.
Also parses the <script> block of .vue / .svelte single-file components.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..models import (ApiCall, DbRef, FileInfo, FunctionInfo, Route,
                      TableInfo, describe)

JS_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "new",
    "function", "await", "async", "else", "do", "try", "throw", "delete",
    "in", "of", "instanceof", "void", "yield", "case", "break", "continue",
    "super", "this", "import", "export", "default", "constructor",
}

RE_FUNC_DECL = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*"
    r"([A-Za-z_$][\w$]*)\s*\(([^)]*)\)", re.MULTILINE)
RE_ARROW = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
    r"(?::[^=]{0,80})?=\s*(?:async\s*)?"
    r"(?:\(([^)]*)\)|([A-Za-z_$][\w$]*))\s*(?::\s*[\w<>\[\]., |]+)?\s*=>",
    re.MULTILINE)
RE_CLASS = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+"
    r"([A-Za-z_$][\w$]*)(?:\s+extends\s+([\w$.]+))?", re.MULTILINE)
RE_METHOD = re.compile(
    r"^[ \t]*(?:public\s+|private\s+|protected\s+|readonly\s+)*"
    r"(?:static\s+)?(?:async\s+)?\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*"
    r"(?::\s*[\w<>\[\]., |&{}]+)?\s*\{", re.MULTILINE)
RE_IMPORT = re.compile(
    r"""(?:import\s+(?:[\w${},*\s]+\s+from\s+)?|require\s*\(\s*)"""
    r"""['"]([^'"]+)['"]""")
RE_ROUTE = re.compile(
    r"\b(?:app|router|server|api|fastify|routes?)\s*\.\s*"
    r"(get|post|put|delete|patch|all|options|head)\s*\(\s*[`'\"]([^`'\"]+)[`'\"]"
    r"\s*,\s*([A-Za-z_$][\w$.]*)?", re.IGNORECASE)
RE_NEST_ROUTE = re.compile(
    r"@(Get|Post|Put|Delete|Patch|All)\s*\(\s*(?:[`'\"]([^`'\"]*)[`'\"])?\s*\)")
RE_FETCH = re.compile(r"\bfetch\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")
RE_FETCH_METHOD = re.compile(r"method\s*:\s*[`'\"](\w+)[`'\"]", re.IGNORECASE)
RE_AXIOS = re.compile(
    r"\b(?:axios|http|api|apiClient|client|\$http)\s*\.\s*"
    r"(get|post|put|delete|patch)\s*\(\s*[`'\"]([^`'\"]+)[`'\"]",
    re.IGNORECASE)
RE_AXIOS_OBJ = re.compile(
    r"\baxios\s*\(\s*\{[^}]*?url\s*:\s*[`'\"]([^`'\"]+)[`'\"]", re.DOTALL)
RE_MONGOOSE = re.compile(r"mongoose\.model\s*\(\s*[`'\"](\w+)[`'\"]")
RE_MONGOOSE_SCHEMA = re.compile(
    r"new\s+(?:mongoose\.)?Schema\s*\(\s*\{([^}]*)\}", re.DOTALL)
RE_PRISMA = re.compile(
    r"\bprisma\.(\w+)\.(findMany|findUnique|findFirst|create|createMany|"
    r"update|updateMany|delete|deleteMany|upsert|count|aggregate)\b")
RE_SEQUELIZE = re.compile(r"sequelize\.define\s*\(\s*[`'\"](\w+)[`'\"]")
RE_KNEX = re.compile(r"\bknex\s*\(\s*[`'\"](\w+)[`'\"]")
RE_TYPEORM_ENTITY = re.compile(r"@Entity\s*\(\s*(?:[`'\"](\w+)[`'\"])?\s*\)")
RE_SQL = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE)\b[\s\S]{0,200}?"
    r"\b(?:FROM|INTO|UPDATE|JOIN)\s+[`\"\[]?([A-Za-z_][A-Za-z0-9_.]*)",
    re.IGNORECASE)
RE_MODEL_OP = re.compile(
    r"\b([A-Z][\w$]*)\.(find|findOne|findById|findAll|findMany|create|"
    r"insertMany|updateOne|updateMany|findByIdAndUpdate|findByIdAndDelete|"
    r"deleteOne|deleteMany|destroy|save|aggregate|countDocuments)\b")
RE_CALL = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")

OP_MAP = {"create": "insert", "insertmany": "insert", "save": "insert",
          "update": "update", "updateone": "update", "updatemany": "update",
          "findbyidandupdate": "update", "delete": "delete",
          "deleteone": "delete", "deletemany": "delete", "destroy": "delete",
          "findbyidanddelete": "delete"}


def _strip_comments(text: str) -> str:
    """Blank out comments and (roughly) string contents so structural regexes
    don't fire inside them — but keep offsets/line numbers identical."""
    out = list(text)
    i, n = 0, len(text)
    in_str: Optional[str] = None
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "'\"`":
            in_str = c
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def _match_brace(text: str, open_idx: int) -> int:
    """Index of the `}` matching the `{` at open_idx. -1 if unbalanced."""
    depth = 0
    i, n = open_idx, len(text)
    in_str: Optional[str] = None
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "'\"`":
            in_str = c
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            nl = text.find("\n", i)
            if nl == -1:
                return -1
            i = nl
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                return -1
            i = end + 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def _body_range(clean: str, start_idx: int) -> Tuple[int, int]:
    """(start, end) offsets of the function body starting at/after start_idx."""
    brace = clean.find("{", start_idx)
    arrow = clean.find("=>", start_idx)
    if arrow != -1 and (brace == -1 or arrow < brace):
        after = arrow + 2
        b2 = clean.find("{", after)
        nl = clean.find("\n", after)
        if b2 != -1 and (nl == -1 or b2 < nl) and clean[after:b2].strip() == "":
            end = _match_brace(clean, b2)
            return (b2, end if end != -1 else min(len(clean), b2 + 400))
        # expression-body arrow fn: body = rest of statement (approx one line)
        end = nl if nl != -1 else len(clean)
        return (after, end)
    if brace == -1:
        return (start_idx, min(len(clean), start_idx + 200))
    end = _match_brace(clean, brace)
    return (brace, end if end != -1 else min(len(clean), brace + 2000))


def _extract_script(text: str) -> str:
    """For .vue/.svelte: keep only <script> content, preserving line offsets."""
    out_lines = [""] * (text.count("\n") + 1)
    for m in re.finditer(r"<script[^>]*>([\s\S]*?)</script>", text,
                         re.IGNORECASE):
        start_line = text.count("\n", 0, m.start(1))
        for i, line in enumerate(m.group(1).split("\n")):
            if start_line + i < len(out_lines):
                out_lines[start_line + i] = line
    return "\n".join(out_lines)


def _scan_body(raw_body: str, base_line: int, fn: FunctionInfo):
    """Populate calls / api_calls / db_refs from a function body (raw text)."""
    for m in RE_FETCH.finditer(raw_body):
        window = raw_body[m.end():m.end() + 220]
        mm = RE_FETCH_METHOD.search(window)
        method = mm.group(1).upper() if mm else "GET"
        fn.api_calls.append(ApiCall(method=method, url=m.group(1),
                                    line=base_line + raw_body.count("\n", 0, m.start())))
    for m in RE_AXIOS.finditer(raw_body):
        fn.api_calls.append(ApiCall(method=m.group(1).upper(), url=m.group(2),
                                    line=base_line + raw_body.count("\n", 0, m.start())))
    for m in RE_AXIOS_OBJ.finditer(raw_body):
        fn.api_calls.append(ApiCall(method="ANY", url=m.group(1),
                                    line=base_line + raw_body.count("\n", 0, m.start())))
    for m in RE_PRISMA.finditer(raw_body):
        fn.db_refs.append(DbRef(table=m.group(1),
                                op=OP_MAP.get(m.group(2).lower(), "query"),
                                via="orm",
                                line=base_line + raw_body.count("\n", 0, m.start())))
    for m in RE_MODEL_OP.finditer(raw_body):
        name = m.group(1)
        if name in ("Object", "Array", "JSON", "Math", "Promise", "Date",
                    "Number", "String", "Boolean", "Map", "Set", "Symbol",
                    "Reflect", "Proxy", "RegExp", "Error", "Intl"):
            continue
        fn.db_refs.append(DbRef(table=name,
                                op=OP_MAP.get(m.group(2).lower(), "query"),
                                via="orm",
                                line=base_line + raw_body.count("\n", 0, m.start())))
    for m in RE_KNEX.finditer(raw_body):
        fn.db_refs.append(DbRef(table=m.group(1), op="query", via="orm",
                                line=base_line + raw_body.count("\n", 0, m.start())))
    for m in RE_SQL.finditer(raw_body):
        fn.db_refs.append(DbRef(table=m.group(2), op=m.group(1).lower(),
                                via="sql",
                                line=base_line + raw_body.count("\n", 0, m.start())))
    clean_body = _strip_comments(raw_body)
    seen = set(fn.calls)
    for m in RE_CALL.finditer(clean_body):
        name = m.group(1)
        if name in JS_KEYWORDS or name == fn.name or name in seen:
            continue
        seen.add(name)
        fn.calls.append(name)
    # de-dup db refs
    seen_db = set()
    fn.db_refs = [d for d in fn.db_refs
                  if not ((d.table, d.op) in seen_db or seen_db.add((d.table, d.op)))]


def parse_javascript(info: FileInfo, text: str, language: str) -> None:
    if language in ("vue", "svelte"):
        text = _extract_script(text)
    clean = _strip_comments(text)
    covered: List[Tuple[int, int]] = []  # body ranges already owned by a fn

    for m in RE_IMPORT.finditer(text):
        info.imports.append(m.group(1))
    info.imports = sorted(set(info.imports))

    def add_function(name: str, params: str, decl_start: int,
                     parent_class: str = ""):
        body_start, body_end = _body_range(clean, decl_start)
        fn = FunctionInfo(
            name=name,
            params=[p.strip() for p in params.split(",") if p.strip()],
            line=_line_of(text, decl_start),
            end_line=_line_of(text, min(body_end, len(text) - 1) if text else 0),
            parent_class=parent_class,
            kind="method" if parent_class else "function",
        )
        raw_body = text[body_start:body_end + 1]
        _scan_body(raw_body, fn.line - 1 + text[decl_start:body_start].count("\n"),
                   fn)
        # routes attached via decorator on the preceding lines (NestJS)
        prefix = text[max(0, decl_start - 200):decl_start]
        nm = RE_NEST_ROUTE.search(prefix)
        if nm:
            fn.routes.append(Route(method=nm.group(1).upper(),
                                   path="/" + (nm.group(2) or "").strip("/"),
                                   line=fn.line))
        fn.description = describe(fn, raw_body[:600])
        info.functions.append(fn)
        covered.append((decl_start, body_end))
        return fn

    # classes first (so methods get parent_class and aren't re-matched)
    for cm in RE_CLASS.finditer(clean):
        cls_name = cm.group(1)
        brace = clean.find("{", cm.end())
        if brace == -1:
            continue
        cend = _match_brace(clean, brace)
        if cend == -1:
            continue
        # TypeORM @Entity above the class -> table definition
        prefix = clean[max(0, cm.start() - 160):cm.start()]
        em = RE_TYPEORM_ENTITY.search(prefix)
        if em:
            body_txt = text[brace:cend]
            cols = re.findall(r"@(?:Primary\w*Column|Column|OneToMany|"
                              r"ManyToOne|ManyToMany|OneToOne)[^\n]*\n\s*"
                              r"([A-Za-z_$][\w$]*)", body_txt)
            info.tables.append(TableInfo(name=em.group(1) or cls_name.lower(),
                                         model=cls_name, fields=cols,
                                         line=_line_of(text, cm.start()),
                                         source=info.path))
        for mm in RE_METHOD.finditer(clean[brace:cend]):
            name = mm.group(1)
            if name in JS_KEYWORDS:
                continue
            add_function(name, mm.group(2), brace + mm.start(), cls_name)
        covered.append((cm.start(), cend))

    def in_class(idx: int) -> bool:
        return any(s <= idx <= e for s, e in covered)

    for m in RE_FUNC_DECL.finditer(clean):
        if not in_class(m.start()):
            add_function(m.group(1), m.group(2), m.start())
    for m in RE_ARROW.finditer(clean):
        if not in_class(m.start()):
            add_function(m.group(1), m.group(2) or m.group(3) or "", m.start())

    # route definitions (Express-style) — attach to enclosing fn or file level
    for m in RE_ROUTE.finditer(clean):
        route = Route(method=m.group(1).upper(),
                      path=m.group(2),
                      line=_line_of(text, m.start()),
                      handler=(m.group(3) or "").split(".")[-1])
        owner = None
        for fn in info.functions:
            if fn.line <= route.line <= max(fn.end_line, fn.line):
                if owner is None or fn.line > owner.line:
                    owner = fn
        if owner is not None and not route.handler:
            owner.routes.append(route)
        else:
            info.routes.append(route)

    # DB model definitions at file level
    for m in RE_MONGOOSE.finditer(clean):
        fields: List[str] = []
        sm = RE_MONGOOSE_SCHEMA.search(clean)
        if sm:
            fields = re.findall(r"([A-Za-z_$][\w$]*)\s*:", sm.group(1))[:20]
        info.tables.append(TableInfo(name=m.group(1).lower(), model=m.group(1),
                                     fields=fields,
                                     line=_line_of(text, m.start()),
                                     source=info.path))
    for m in RE_SEQUELIZE.finditer(clean):
        info.tables.append(TableInfo(name=m.group(1), model=m.group(1),
                                     line=_line_of(text, m.start()),
                                     source=info.path))

    # file-level API calls (outside any extracted function)
    def outside_functions(line: int) -> bool:
        return not any(f.line <= line <= max(f.end_line, f.line)
                       for f in info.functions)

    for m in RE_FETCH.finditer(text):
        line = _line_of(text, m.start())
        if outside_functions(line):
            info.api_calls.append(ApiCall(method="GET", url=m.group(1),
                                          line=line))
    for m in RE_AXIOS.finditer(text):
        line = _line_of(text, m.start())
        if outside_functions(line):
            info.api_calls.append(ApiCall(method=m.group(1).upper(),
                                          url=m.group(2), line=line))

    # module-level calls (top-level script code outside any function)
    seen_top = set()
    for m in RE_CALL.finditer(clean):
        name = m.group(1)
        if name in JS_KEYWORDS or name in seen_top:
            continue
        if outside_functions(_line_of(text, m.start())):
            seen_top.add(name)
            info.calls.append(name)
    info.calls = info.calls[:40]
