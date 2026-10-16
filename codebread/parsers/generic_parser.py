"""Regex-based extractors for Java, Go, PHP, Ruby, C#, plus SQL schema files
and config files (with credential masking). Less precise than a real parser,
but keeps these languages visible in the graph instead of silently skipped.
"""
from __future__ import annotations

import re
from typing import Dict, List, Pattern

from ..models import (ApiCall, DbRef, FileInfo, FunctionInfo, Route,
                      TableInfo, describe)

KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "new", "else", "do",
    "try", "throw", "case", "using", "lock", "foreach", "select", "func",
    "defer", "go", "range", "elsif", "unless", "until", "when", "match",
    "sizeof", "typeof", "yield", "puts", "print", "println", "printf",
    "function", "fn", "use",  # PHP closures: `function () use ($x)`, `fn () =>`
}

SQL_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE)\b[\s\S]{0,200}?"
    r"\b(?:FROM|INTO|UPDATE|JOIN)\s+[`\"\[]?([A-Za-z_][A-Za-z0-9_.]*)",
    re.IGNORECASE)
CALL_RE = re.compile(r"(?<![\w$.:])([A-Za-z_][\w]*)\s*\(")

# ---- PHP / Laravel ------------------------------------------------------
# CALL_RE skips `X::f(` and would read `$obj->label(` as a call to any
# function named label. In PHP only these member calls are trustworthy:
PHP_MEMBER_CALL_RE = re.compile(
    r"(?:\$this->|\b(?:self|static|parent)::|\b[A-Z]\w*::)(\w+)\s*\(")
PHP_USE_RE = re.compile(r"^\s*use\s+([A-Za-z_][\w\\]*\\\w+)\s*(?:as\s+\w+\s*)?;",
                        re.MULTILINE)
PHP_VIEW_RE = re.compile(r"\bview\s*\(\s*['\"]([\w.\-/]+)['\"]")
# Eloquent: Booking::where(...), Booking::create(...), DB::table('bookings')
PHP_ORM_RE = re.compile(
    r"\b([A-Z]\w*)::(query|where\w*|find\w*|first\w*|create|insert\w*|"
    r"update\w*|upsert|destroy|all|with|latest|oldest|orderBy|count|sum|"
    r"pluck|paginate|select)\s*\(")
PHP_DB_TABLE_RE = re.compile(r"\bDB::table\(\s*['\"](\w+)['\"]")
ORM_OP = {"create": "insert", "insert": "insert", "upsert": "insert",
          "update": "update", "destroy": "delete"}
NOT_MODELS = {"DB", "Route", "Schema", "Carbon", "Str", "Arr", "Auth", "Cache",
              "Log", "Http", "Storage", "Validator", "Hash", "Session", "Config",
              "Gate", "Mail", "Event", "Queue", "App", "Request", "Response"}
SCHEMA_RE = re.compile(r"Schema::(create|table)\s*\(\s*['\"](\w+)['\"]")
BLUEPRINT_COL_RE = re.compile(r"\$\w+->(\w+)\s*\(\s*(?:['\"](\w+)['\"])?")
BLUEPRINT_IMPLIED = {"id": ["id"], "timestamps": ["created_at", "updated_at"],
                     "timestampsTz": ["created_at", "updated_at"],
                     "softDeletes": ["deleted_at"], "rememberToken": ["remember_token"]}
BLUEPRINT_SKIP = {"index", "unique", "primary", "foreign", "dropColumn",
                  "dropForeign", "dropIndex", "renameColumn", "fullText",
                  "spatialIndex", "comment", "engine", "charset", "collation"}
ELOQUENT_RE = re.compile(
    r"^\s*(?:final\s+)?class\s+(\w+)\s+extends\s+(?:Model|Authenticatable|Pivot)\b",
    re.MULTILINE)
PHP_TABLE_PROP_RE = re.compile(r"\$table\s*=\s*['\"](\w+)['\"]")


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


def _plural_candidates(snake: str) -> List[str]:
    """Laravel's table guess for a model, best first (Booking -> bookings)."""
    if snake.endswith("y") and snake[-2:-1] not in "aeiou":
        first = snake[:-1] + "ies"
    elif snake.endswith(("s", "x", "z", "ch", "sh")):
        first = snake + "es"
    else:
        first = snake + "s"
    return [first, snake]  # bare name covers uncountables like `equipment`


def _php_member_calls(body: str) -> List[str]:
    return [m.group(1) for m in PHP_MEMBER_CALL_RE.finditer(body)]


def _php_db_refs(body: str, line: int) -> List[DbRef]:
    refs = [DbRef(table=m.group(1), op="query", via="sql", line=line)
            for m in PHP_DB_TABLE_RE.finditer(body)]
    for m in PHP_ORM_RE.finditer(body):
        if m.group(1) in NOT_MODELS:
            continue
        op = next((v for k, v in ORM_OP.items() if m.group(2).startswith(k)), "select")
        refs.append(DbRef(table=m.group(1), op=op, via="orm-guess", line=line))
    return refs


def parse_laravel(info: FileInfo, text: str) -> None:
    """File-level Laravel facts: `use` imports, view() links, migrations,
    Eloquent models. Cheap regex passes; nothing matches in non-Laravel PHP."""
    info.imports.extend(m.group(1).replace("\\", "/") for m in PHP_USE_RE.finditer(text))
    for m in PHP_VIEW_RE.finditer(text):
        info.links.append("resources/views/" + m.group(1).replace(".", "/") + ".blade.php")

    for m in SCHEMA_RE.finditer(text):
        end = _brace_end_line(text, m.end())
        block = "\n".join(text.split("\n")[_line_of(text, m.start()) - 1:end or None])
        cols: List[str] = []
        for c in BLUEPRINT_COL_RE.finditer(block):
            method, col = c.group(1), c.group(2)
            if method in BLUEPRINT_SKIP:
                continue
            for name in BLUEPRINT_IMPLIED.get(method, [col] if col else []):
                if name not in cols:
                    cols.append(name)
        # Schema::table() only alters: it adds columns but doesn't define the table
        info.tables.append(TableInfo(name=m.group(2), fields=cols[:40],
                                     line=_line_of(text, m.start()),
                                     source=info.path if m.group(1) == "create" else ""))

    for m in ELOQUENT_RE.finditer(text):
        cls = m.group(1)
        explicit = PHP_TABLE_PROP_RE.search(text)
        cands = [explicit.group(1)] if explicit else _plural_candidates(_snake(cls))
        # no source: the migration defines the table; the model links to it by edge
        info.tables.append(TableInfo(name=cands[0], model=cls, aliases=cands,
                                     line=_line_of(text, m.start())))

LANG_PATTERNS: Dict[str, Dict[str, Pattern]] = {
    "go": {
        "function": re.compile(
            r"^func\s+(?:\([^)]*\)\s+)?([A-Za-z_]\w*)\s*\(([^)]*)\)",
            re.MULTILINE),
        "class": re.compile(
            r"^type\s+([A-Za-z_]\w*)\s+struct\b", re.MULTILINE),
        "import": re.compile(r'"([\w./-]+)"'),
        "route": re.compile(
            r'\.(?:GET|POST|PUT|DELETE|PATCH|Handle(?:Func)?)\s*\(\s*"([^"]+)"'
            r"\s*,\s*(\w+)?"),
    },
    "java": {
        "function": re.compile(
            r"^[ \t]*(?:public|private|protected)[ \t]+(?:static[ \t]+)?"
            r"(?:final[ \t]+)?[\w<>\[\], ?]+[ \t]+(\w+)\s*\(([^)]*)\)\s*"
            r"(?:throws [\w, ]+)?\s*\{", re.MULTILINE),
        "class": re.compile(
            r"^[ \t]*(?:public\s+)?(?:abstract\s+|final\s+)?"
            r"(?:class|interface|record|enum)\s+(\w+)", re.MULTILINE),
        "import": re.compile(r"^import\s+([\w.]+)", re.MULTILINE),
        "route": re.compile(
            r"@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*"
            r"(?:value\s*=\s*)?\"([^\"]+)\""),
    },
    "csharp": {
        "function": re.compile(
            r"^[ \t]*(?:public|private|protected|internal)[ \t]+"
            r"(?:static[ \t]+|async[ \t]+|virtual[ \t]+|override[ \t]+)*"
            r"[\w<>\[\], ?]+[ \t]+(\w+)\s*\(([^)]*)\)", re.MULTILINE),
        "class": re.compile(
            r"^[ \t]*(?:public\s+)?(?:abstract\s+|sealed\s+|partial\s+)*"
            r"(?:class|interface|record)\s+(\w+)", re.MULTILINE),
        "import": re.compile(r"^using\s+([\w.]+)", re.MULTILINE),
        "route": re.compile(r"\[Http(Get|Post|Put|Delete|Patch)"
                            r"(?:\(\s*\"([^\"]*)\"\s*\))?\]"),
    },
    "php": {
        "function": re.compile(
            r"(?:public\s+|private\s+|protected\s+|static\s+)*"
            r"function\s+&?(\w+)\s*\(([^)]*)\)"),
        "class": re.compile(r"^\s*(?:abstract\s+|final\s+)?class\s+(\w+)",
                            re.MULTILINE),
        "import": re.compile(
            r"(?:require|include)(?:_once)?\s*\(?\s*(?:__DIR__\s*\.\s*)?"
            r"['\"]/?([^'\"]+\.php)['\"]"),
        "route": re.compile(
            r"Route::(get|post|put|delete|patch|any)\s*\(\s*['\"]([^'\"]+)['\"]"
            r"(?:\s*,\s*\[?\s*[\w:]*['\"]?\s*,?\s*['\"]?(\w+))?"),
    },
    "ruby": {
        "function": re.compile(r"^\s*def\s+(?:self\.)?(\w+[?!]?)\s*"
                               r"(?:\(([^)]*)\))?", re.MULTILINE),
        "class": re.compile(r"^\s*(?:class|module)\s+([A-Z]\w*)",
                            re.MULTILINE),
        "import": re.compile(r"^\s*require(?:_relative)?\s+['\"]([^'\"]+)",
                             re.MULTILINE),
        "route": re.compile(r"^\s*(get|post|put|delete|patch)\s+['\"]([^'\"]+)"
                            r"['\"](?:\s*(?:,\s*to:\s*|=>\s*)['\"]([\w#]+))?",
                            re.MULTILINE),
    },
}


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def _brace_end_line(text: str, from_idx: int) -> int:
    """Line of the `}` closing the first `{` at/after from_idx. 0 if none."""
    i = text.find("{", from_idx)
    if i == -1 or i - from_idx > 300:
        return 0
    depth, n = 0, len(text)
    in_str = None
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "'\"":
            in_str = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return _line_of(text, i)
        i += 1
    return 0


def _ruby_end_line(lines: list, start_line: int) -> int:
    """Line of the `end` matching a `def` on start_line (1-based). 0 if none."""
    head = lines[start_line - 1]
    indent = len(head) - len(head.lstrip())
    for j in range(start_line, min(len(lines), start_line + 300)):
        line = lines[j]
        if line.strip() == "end" and len(line) - len(line.lstrip()) <= indent:
            return j + 1
    return 0


def parse_generic(info: FileInfo, text: str, language: str) -> None:
    pats = LANG_PATTERNS[language]

    for m in pats["import"].finditer(text):
        info.imports.append(m.group(1))
    info.imports = sorted(set(info.imports))[:60]

    lines = text.split("\n")

    for m in pats["function"].finditer(text):
        name = m.group(1)
        if name in KEYWORDS or (language == "go" and name == "init"):
            if name in KEYWORDS:
                continue
        params_raw = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
        start_line = _line_of(text, m.start())
        if language == "ruby":
            end_line = _ruby_end_line(lines, start_line)
        else:
            end_line = _brace_end_line(text, m.end())
        if not end_line or end_line < start_line:
            end_line = min(start_line + 60, len(lines))  # fallback guess
        body = "\n".join(lines[start_line - 1:min(end_line, start_line + 120)])
        fn = FunctionInfo(
            name=name,
            params=[p.strip() for p in (params_raw or "").split(",")
                    if p.strip()][:10],
            line=start_line, end_line=end_line)
        # route annotation immediately above (Spring / ASP.NET)
        prefix = "\n".join(lines[max(0, start_line - 4):start_line - 1])
        rm = pats["route"].search(prefix)
        if rm:
            g = rm.groups()
            method = (g[0] or "ANY").upper().replace("REQUEST", "ANY")
            path = (g[1] if len(g) > 1 and g[1] else "/")
            fn.routes.append(Route(method=method, path=path, line=start_line))
        for sm in SQL_RE.finditer(body):
            fn.db_refs.append(DbRef(table=sm.group(2), op=sm.group(1).lower(),
                                    via="sql", line=start_line))
        seen = set()
        for cm in CALL_RE.finditer(body):
            cname = cm.group(1)
            if cname in KEYWORDS or cname == name or cname in seen:
                continue
            if language == "php" and body[max(0, cm.start() - 2):cm.start()] == "->":
                continue  # $obj->method(): unknown receiver, see PHP_MEMBER_CALL_RE
            seen.add(cname)
            fn.calls.append(cname)
        if language == "php":
            for cname in _php_member_calls(body):
                if cname not in seen and cname != name and cname not in KEYWORDS:
                    seen.add(cname)
                    fn.calls.append(cname)
            fn.db_refs.extend(_php_db_refs(body, start_line))
        fn.calls = fn.calls[:40]
        fn.description = describe(fn, body[:400])
        info.functions.append(fn)

    # file-level routes not attached to a function (Laravel/Sinatra/Gin)
    fn_lines = [(f.line, f.end_line) for f in info.functions]
    for m in pats["route"].finditer(text):
        line = _line_of(text, m.start())
        if any(s <= line <= e for s, e in fn_lines):
            continue
        g = m.groups()
        method = (g[0] or "ANY").upper().replace("REQUEST", "ANY")
        path = g[1] if len(g) > 1 and g[1] else "/"
        handler = g[2] if len(g) > 2 and g[2] else ""
        if "#" in handler:  # rails 'users#index'
            handler = handler.split("#")[-1]
        info.routes.append(Route(method=method, path=path, line=line,
                                 handler=handler))

    if language in ("php", "ruby"):
        extract_toplevel(info, text)
    if language == "php":
        parse_laravel(info, text)
        info.imports = sorted(set(info.imports))[:60]
        info.links = list(dict.fromkeys(info.links))[:30]


PAGE_LINK_RE = re.compile(
    r"(?:redirect|url|location|navigate)\s*\(\s*['\"]([\w\-./]+\.(?:php|html?))"
    r"|href\s*=\s*['\"]([\w\-./]+\.(?:php|html?))"
    r"|action\s*=\s*['\"]([\w\-./]+\.php)"
    r"|Location:\s*([\w\-./]+\.php)", re.IGNORECASE)

TOPLEVEL_NOISE = KEYWORDS | {
    "echo", "isset", "empty", "unset", "die", "exit", "list", "array",
    "define", "defined", "declare", "compact", "extract", "eval", "clone",
}


def extract_toplevel(info: FileInfo, text: str) -> None:
    """Calls made outside any extracted function (classic script-style code,
    e.g. a PHP page calling auth_boot()), plus page-navigation links."""
    fn_ranges = [(f.line, max(f.end_line, f.line)) for f in info.functions]

    def outside(line: int) -> bool:
        return not any(s <= line <= e for s, e in fn_ranges)

    is_php = info.language == "php"
    seen = set()
    for m in CALL_RE.finditer(text):
        name = m.group(1)
        if name in TOPLEVEL_NOISE or name in seen:
            continue
        if is_php and text[max(0, m.start() - 2):m.start()] == "->":
            continue
        if outside(_line_of(text, m.start())):
            seen.add(name)
            info.calls.append(name)
    if is_php:  # routes/web.php closures call App\X::y() at top level
        for m in PHP_MEMBER_CALL_RE.finditer(text):
            name = m.group(1)
            if name not in seen and name not in TOPLEVEL_NOISE and outside(_line_of(text, m.start())):
                seen.add(name)
                info.calls.append(name)
    info.calls = info.calls[:40]

    seen_l = set()
    for m in PAGE_LINK_RE.finditer(text):
        target = next(g for g in m.groups() if g)
        if target not in seen_l:
            seen_l.add(target)
            info.links.append(target)
    info.links = info.links[:30]


CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?"
    r"([A-Za-z_][\w.]*)[`\"\]]?\s*\(([\s\S]*?)\)\s*;",
    re.IGNORECASE)


def parse_sql(info: FileInfo, text: str) -> None:
    for m in CREATE_TABLE_RE.finditer(text):
        cols = []
        for raw in m.group(2).split(","):
            token = raw.strip().split()
            if token and not token[0].upper() in (
                    "PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "KEY",
                    "INDEX", "CHECK"):
                cols.append(token[0].strip('`"[]'))
        info.tables.append(TableInfo(name=m.group(1),
                                     fields=cols[:30],
                                     line=_line_of(text, m.start()),
                                     source=info.path))


SECRET_KEY_RE = re.compile(
    r"(PASS(WORD)?|SECRET|TOKEN|API[_-]?KEY|PRIVATE|CREDENTIAL|AUTH)",
    re.IGNORECASE)
DB_KEY_RE = re.compile(
    r"(DB|DATABASE|POSTGRES|MYSQL|MONGO|REDIS|SQL|CONN)", re.IGNORECASE)
URL_CREDS_RE = re.compile(r"://([^:/@\s]+):([^@\s]+)@")


def parse_config(info: FileInfo, text: str) -> None:
    """Look for DB connection settings in config files. Mask every secret."""
    for i, line in enumerate(text.splitlines()[:400], 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "//")):
            continue
        m = re.match(r"^\s*[\"']?([\w.\-]+)[\"']?\s*[:=]\s*(.+)$", stripped)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip().strip("\"',")
        if not (DB_KEY_RE.search(key) or SECRET_KEY_RE.search(key)):
            continue
        if SECRET_KEY_RE.search(key):
            value = "•••masked•••"
        else:
            value = URL_CREDS_RE.sub("://***:***@", value)
            if len(value) > 60:
                value = value[:57] + "..."
        info.db_config.append(f"{key} = {value}")
    info.db_config = info.db_config[:20]


def redact_secrets(text: str) -> str:
    """Mask secret-looking values line by line. Used on config-file source
    before it's stored/exported, so the raw "IDE view" / JSON export can't
    leak what the DB-config summary already redacts."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^(\s*[\"']?[\w.\-]+[\"']?\s*[:=]\s*)(.+)$", line)
        if m and SECRET_KEY_RE.search(m.group(1)):
            out.append(m.group(1) + "•••masked•••")
        else:
            out.append(URL_CREDS_RE.sub("://***:***@", line))
    return "\n".join(out)
