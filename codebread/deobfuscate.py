"""Safe, execution-free de-obfuscation scanner.

Finds and statically decodes the constant-literal obfuscation idioms
commonly used to hide payloads/strings in source: hex/octal/unicode string
escapes, "chr()"-style character-code arithmetic (chr(65+1),
String.fromCharCode(...), (char)(65), Go's string(rune(...)), Ruby's
.chr, ...), base64-encoded string literals, and dead "chaff" literal
statements that are built and never used.

Everything here operates on literal numbers/strings already sitting in the
scanned text. Nothing is ever executed, imported, or eval'd — an
expression that involves anything beyond integer literals and
+-*/%<<>>|&^ arithmetic (a variable, a function call, string
concatenation with a runtime value, ...) is left alone rather than guessed
at. That property is what makes it safe to run this over code you don't
trust yet, which is the whole point.
"""
from __future__ import annotations

import ast
import base64
import binascii
import operator
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ---------------- safe constant-arithmetic evaluator ----------------

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.LShift: operator.lshift, ast.RShift: operator.rshift,
    ast.BitOr: operator.or_, ast.BitAnd: operator.and_, ast.BitXor: operator.xor,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Invert: operator.invert}

# PHP/Ruby/legacy-JS/Go style leading-zero octal (e.g. 0144) isn't valid
# Python literal syntax (Python needs 0o144) — normalize before parsing.
_LEADING_ZERO_OCTAL_RE = re.compile(r"(?<![\w.])0([0-7]+)\b(?!\.)")


def safe_eval_int_expr(expr: str) -> Optional[int]:
    """Evaluate a constant integer arithmetic expression with no code
    execution risk: only int literals and +-*/%, shifts, and bitwise
    operators are permitted. Returns None for anything else — a name, a
    call, a float, unparsable text — which is the safety property this
    function exists to provide. Never raises."""
    expr = expr.strip()
    if not expr:
        return None
    normalized = _LEADING_ZERO_OCTAL_RE.sub(r"0o\1", expr)
    try:
        tree = ast.parse(normalized, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int) \
                and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left, right = ev(node.left), ev(node.right)
            if left is None or right is None:
                return None
            try:
                return _BINOPS[type(node.op)](left, right)
            except (ZeroDivisionError, ValueError, OverflowError):
                return None
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
            val = ev(node.operand)
            return None if val is None else _UNARYOPS[type(node.op)](val)
        return None  # Name, Call, Attribute, float, ... -> refuse, not guess

    result = ev(tree)
    return result if isinstance(result, int) and not isinstance(result, bool) else None


def _codepoint_to_char(n: Optional[int]) -> Optional[str]:
    # 0xD800-0xDFFF are UTF-16 surrogate halves, not standalone Unicode
    # scalar values — chr() will happily build one (Python str can hold
    # any codepoint), but json.dumps(...).encode("utf-8") later blows up
    # with "surrogates not allowed" the moment it's serialized. A source
    # file with an unpaired \uD8xx/\uDCxx-style escape (or char-code math
    # landing in that range) must be left undecoded, not turned into a
    # value that crashes the whole scan downstream.
    if n is None or n < 0 or n > 0x10FFFF or 0xD800 <= n <= 0xDFFF:
        return None
    try:
        return chr(n)
    except (ValueError, OverflowError):
        return None


# ---------------- balanced-paren / top-level-comma helpers ----------------

def _extract_balanced(text: str, open_idx: int) -> Optional[str]:
    """Given the index of an opening '(' in text, return the substring
    between it and its matching ')', or None if unbalanced."""
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
        elif c in "'\"":
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i]
        i += 1
    return None


def _split_top_level(s: str, sep: str) -> List[str]:
    """Split `s` on `sep` outside strings/brackets. Must treat a backslash
    inside a string as escaping the next character (skip it as a pair) —
    without that, a single escaped quote anywhere earlier in a real file
    desyncs in_str for everything after it, which then corrupts every
    subsequent depth/boundary decision for the rest of the file."""
    parts, depth, cur = [], 0, []
    in_str: Optional[str] = None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < n:
                cur.append(s[i + 1])
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "'\"":
            in_str = c
            cur.append(c)
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            depth -= 1
            cur.append(c)
        elif c == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts]


@dataclass
class ObfFinding:
    line: int
    kind: str          # "escape" | "char-code" | "base64" | "chaff"
    original: str
    decoded: str


# ---------------- string-escape decoding ----------------

# Which quote characters are treated as escape-interpreting string
# literals per language, and which escape families that language supports.
# (Single-quoted strings in PHP/Ruby don't interpret \x/\NNN — only their
# double-quoted forms do, so PHP/Ruby only list '"'.)
_LANG_ESCAPES: Dict[str, Dict] = {
    "python":     dict(quotes='"\'', hex=True, octal=True, uni4=True, uni_brace=False),
    "javascript": dict(quotes='"\'`', hex=True, octal=True, uni4=True, uni_brace=True),
    "typescript": dict(quotes='"\'`', hex=True, octal=True, uni4=True, uni_brace=True),
    "vue":        dict(quotes='"\'`', hex=True, octal=True, uni4=True, uni_brace=True),
    "svelte":     dict(quotes='"\'`', hex=True, octal=True, uni4=True, uni_brace=True),
    "java":       dict(quotes='"', hex=False, octal=True, uni4=True, uni_brace=False),
    "csharp":     dict(quotes='"', hex=True, octal=False, uni4=True, uni_brace=False),
    "go":         dict(quotes='"', hex=True, octal=True, uni4=True, uni_brace=False),
    "php":        dict(quotes='"', hex=True, octal=True, uni4=False, uni_brace=True),
    "ruby":       dict(quotes='"', hex=True, octal=True, uni4=True, uni_brace=True),
}


def _decode_escape_body(body: str, rules: Dict) -> Tuple[str, bool]:
    """Decode \\xHH / \\NNN (octal) / \\uHHHH / \\u{HHHH} inside a string
    literal body. Returns (decoded_text, changed)."""
    out, i, n, changed = [], 0, len(body), False
    while i < n:
        c = body[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        nxt = body[i + 1]
        if rules["hex"] and nxt == "x":
            m = re.match(r"[0-9A-Fa-f]{1,2}", body[i + 2:i + 4])
            if m:
                out.append(chr(int(m.group(0), 16)))
                i += 2 + len(m.group(0))
                changed = True
                continue
        if rules["uni_brace"] and nxt == "u" and body[i + 2:i + 3] == "{":
            m = re.match(r"\{([0-9A-Fa-f]{1,6})\}", body[i + 2:i + 10])
            if m:
                ch = _codepoint_to_char(int(m.group(1), 16))
                if ch is not None:
                    out.append(ch)
                    i += 2 + len(m.group(0))
                    changed = True
                    continue
        if rules["uni4"] and nxt == "u":
            m = re.match(r"[0-9A-Fa-f]{4}", body[i + 2:i + 6])
            if m:
                ch = _codepoint_to_char(int(m.group(0), 16))
                if ch is not None:
                    out.append(ch)
                    i += 2 + 4
                    changed = True
                    continue
                # a lone UTF-16 surrogate half (e.g. one side of a \uD83D
                # \uDE00 astral-character pair) — chr() would build it,
                # but it can't be emitted as valid UTF-8 later, so leave
                # the escape as literal text rather than crash downstream.
        if rules["octal"] and nxt in "01234567":
            m = re.match(r"[0-7]{1,3}", body[i + 1:i + 4])
            if m:
                out.append(chr(int(m.group(0), 8)))
                i += 1 + len(m.group(0))
                changed = True
                continue
        out.append(nxt)
        i += 2
    return "".join(out), changed


def _find_string_literals(text: str, quote_chars: str):
    """Yield (start, end, quote_char, raw_body) for each single-line
    quoted-string literal using any of quote_chars."""
    pattern = re.compile(
        "|".join(f"{re.escape(q)}((?:[^{re.escape(q)}\\\\\\n]|\\\\.)*){re.escape(q)}"
                 for q in quote_chars))
    for m in pattern.finditer(text):
        q = m.group(0)[0]
        yield m.start(), m.end(), q, m.group(m.lastindex if m.lastindex else 1)


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def scan_escapes(text: str, language: str) -> List[ObfFinding]:
    rules = _LANG_ESCAPES.get(language)
    if not rules:
        return []
    findings = []
    for start, end, _q, body in _find_string_literals(text, rules["quotes"]):
        decoded, changed = _decode_escape_body(body, rules)
        if changed and decoded != body:
            findings.append(ObfFinding(line=_line_of(text, start), kind="escape",
                                       original=text[start:end], decoded=decoded))
    return findings


# ---------------- char-code call decoding (chr(), fromCharCode(), ...) ----

_CHARCODE_PREFIXES: Dict[str, List[Tuple[re.Pattern, bool]]] = {
    "python": [(re.compile(r"\bchr\s*\("), False)],
    "php":    [(re.compile(r"\bchr\s*\("), False)],
    "javascript": [(re.compile(r"\bString\s*\.\s*fromCharCode\s*\("), True),
                   (re.compile(r"\bString\s*\.\s*fromCodePoint\s*\("), True)],
    "java":   [(re.compile(r"\(char\)\s*\("), False)],
    "csharp": [(re.compile(r"\(char\)\s*\("), False)],
}
_CHARCODE_PREFIXES["typescript"] = _CHARCODE_PREFIXES["javascript"]
_CHARCODE_PREFIXES["vue"] = _CHARCODE_PREFIXES["javascript"]
_CHARCODE_PREFIXES["svelte"] = _CHARCODE_PREFIXES["javascript"]

_GO_STRING_RUNE_RE = re.compile(r"\bstring\s*\(")
_RUBY_CHR_RE = re.compile(r"(?:\(([^()]+)\)|\b(\d[\d_]*)\b)\s*\.\s*chr\b")


def _scan_charcode_generic(text: str, language: str) -> List[ObfFinding]:
    findings = []
    for prefix_re, multi_arg in _CHARCODE_PREFIXES.get(language, []):
        for m in prefix_re.finditer(text):
            open_idx = m.end() - 1
            arg_text = _extract_balanced(text, open_idx)
            if arg_text is None:
                continue
            end_idx = text.index(")", open_idx)
            # find the real matching close (re-walk to be exact)
            depth, i = 0, open_idx
            while i < len(text):
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
                i += 1
            args = _split_top_level(arg_text, ",") if multi_arg else [arg_text]
            chars = []
            ok = True
            for a in args:
                n = safe_eval_int_expr(a)
                ch = _codepoint_to_char(n)
                if ch is None:
                    ok = False
                    break
                chars.append(ch)
            if ok and chars:
                findings.append(ObfFinding(line=_line_of(text, m.start()), kind="char-code",
                                           original=text[m.start():end_idx + 1],
                                           decoded="".join(chars)))
    return findings


def _scan_charcode_go(text: str) -> List[ObfFinding]:
    findings = []
    for m in _GO_STRING_RUNE_RE.finditer(text):
        open_idx = m.end() - 1
        inner = _extract_balanced(text, open_idx)
        if inner is None:
            continue
        end_idx = open_idx + len(inner) + 1
        rm = re.match(r"^\s*rune\s*\((.*)\)\s*$", inner, re.DOTALL)
        expr = rm.group(1) if rm else inner
        ch = _codepoint_to_char(safe_eval_int_expr(expr))
        if ch is not None:
            findings.append(ObfFinding(line=_line_of(text, m.start()), kind="char-code",
                                       original=text[m.start():end_idx + 1], decoded=ch))
    return findings


def _scan_charcode_ruby(text: str) -> List[ObfFinding]:
    findings = []
    for m in _RUBY_CHR_RE.finditer(text):
        expr = m.group(1) if m.group(1) is not None else m.group(2)
        ch = _codepoint_to_char(safe_eval_int_expr(expr))
        if ch is not None:
            findings.append(ObfFinding(line=_line_of(text, m.start()), kind="char-code",
                                       original=m.group(0), decoded=ch))
    return findings


def scan_charcode(text: str, language: str) -> List[ObfFinding]:
    if language == "go":
        return _scan_charcode_go(text)
    if language == "ruby":
        return _scan_charcode_ruby(text)
    return _scan_charcode_generic(text, language)


# ---------------- base64 literal decoding ----------------

_BASE64_CALLS: Dict[str, re.Pattern] = {
    "python": re.compile(r"\bbase64\s*\.\s*b64decode\s*\("),
    "javascript": re.compile(r"\batob\s*\("),
    "php": re.compile(r"\bbase64_decode\s*\("),
    "java": re.compile(r"\bBase64\s*\.\s*getDecoder\s*\(\s*\)\s*\.\s*decode\s*\("),
    "csharp": re.compile(r"\bConvert\s*\.\s*FromBase64String\s*\("),
    "go": re.compile(r"base64\s*\.\s*StdEncoding\s*\.\s*DecodeString\s*\("),
    "ruby": re.compile(r"\bBase64\s*\.\s*decode64\s*\("),
}
_BASE64_CALLS["typescript"] = _BASE64_CALLS["javascript"]
_BASE64_CALLS["vue"] = _BASE64_CALLS["javascript"]
_BASE64_CALLS["svelte"] = _BASE64_CALLS["javascript"]

_QUOTED_LITERAL_RE = re.compile(r"""(['"])((?:[^'"\\\n]|\\.)*)\1""")
_B64_CHARS_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _looks_like_text(raw: bytes) -> bool:
    if not raw:
        return False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    printable = sum(1 for c in text if c.isprintable() or c in "\r\n\t")
    return printable / len(text) >= 0.85


def scan_base64(text: str, language: str) -> List[ObfFinding]:
    call_re = _BASE64_CALLS.get(language)
    if not call_re:
        return []
    findings = []
    for m in call_re.finditer(text):
        open_idx = m.end() - 1
        arg_text = _extract_balanced(text, open_idx)
        if arg_text is None:
            continue
        end_idx = open_idx + len(arg_text) + 1
        lm = _QUOTED_LITERAL_RE.search(arg_text)
        if not lm:
            continue
        candidate = lm.group(2).strip()
        if len(candidate) < 8 or not _B64_CHARS_RE.match(candidate):
            continue
        try:
            raw = base64.b64decode(candidate, validate=True)
        except (binascii.Error, ValueError):
            continue
        if not _looks_like_text(raw):
            continue
        findings.append(ObfFinding(line=_line_of(text, m.start()), kind="base64",
                                   original=text[m.start():end_idx + 1],
                                   decoded=raw.decode("utf-8")))
    return findings


# ---------------- dead "chaff" literal-statement detection ----------------

# Languages with a clear ';'-terminated statement boundary and a known
# literal-concatenation operator — needed to reliably tell "this whole
# statement is just literals glued together and discarded" from a normal
# expression. Python/Ruby (no required terminator) are intentionally not
# covered yet; see README.
_CHAFF_CONCAT_OP = {
    "php": ".", "javascript": "+", "typescript": "+", "vue": "+", "svelte": "+",
    "java": "+", "csharp": "+", "go": "+",
}

def _blank_comments(text: str, hash_comments: bool = False) -> str:
    """Blank /* */ and // comments (and # for PHP), position-preserving,
    string-literal aware (so a URL like "https://x" inside quotes isn't
    mistaken for a // comment). Needed because a comment sitting between
    two statements isn't a token _CHAFF_TOKEN_RE recognizes, so leaving it
    in place breaks the "entire statement is pure literal concat" walk for
    the statement right after it — found via a real file where the vendor
    comment immediately preceding the target line did exactly this."""
    out = []
    in_str: Optional[str] = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "'\"":
            in_str = c
            out.append(c)
            i += 1
            continue
        if c == "/" and text[i + 1:i + 2] == "*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:end]))
            i = end
            continue
        if c == "/" and text[i + 1:i + 2] == "/":
            nl = text.find("\n", i)
            end = n if nl == -1 else nl
            out.append(" " * (end - i))
            i = end
            continue
        if hash_comments and c == "#":
            nl = text.find("\n", i)
            end = n if nl == -1 else nl
            out.append(" " * (end - i))
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out)


_PHP_TAG_RE = re.compile(r"<\?php\b|<\?=|<\?(?!xml)|\?>")


def _php_code_only(text: str) -> str:
    """Blank out everything OUTSIDE <?php ... ?> / <?= ... ?> tags (space
    for space, newlines kept as newlines) so a real .php view file — PHP
    blocks interleaved with raw HTML — doesn't throw off the naive
    semicolon/brace statement-splitting below. Same length as `text`, so
    line numbers computed against either one agree."""
    out = []
    in_php = False
    i, n = 0, len(text)
    while i < n:
        m = _PHP_TAG_RE.match(text, i)
        if m:
            tag = m.group(0)
            # the tag delimiter itself is never "code" either way — blank
            # it too (preserving length/newlines) rather than dropping it,
            # or every position after the first tag would be shifted
            out.append("".join(c if c == "\n" else " " for c in tag))
            in_php = tag != "?>"
            i = m.end()
            continue
        c = text[i]
        out.append(c if (in_php or c == "\n") else " ")
        i += 1
    return "".join(out)

def _split_statements(s: str) -> List[str]:
    """Rough top-level 'statement' splitter for chaff detection: ends a
    chunk at a ';' seen at bracket-depth 0, OR right after a '}' that
    closes back down to depth 0. The second case matters because a
    control-flow block (`if (...) { ... }`) has no trailing ';' — without
    treating its closing brace as a boundary too, `_split_top_level`'s
    ';'-only splitting glues the *next* statement onto the end of the
    entire preceding if/else block (found via a real file: a chaff
    statement sitting right after an if/else got merged into one 1500+
    char blob together with everything inside that block, which then
    trivially failed the "whole statement is pure literal concat" check)."""
    parts, depth, cur = [], 0, []
    in_str: Optional[str] = None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < n:
                cur.append(s[i + 1])
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "'\"":
            in_str = c
            cur.append(c)
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            depth -= 1
            cur.append(c)
            if depth == 0 and c == "}":
                parts.append("".join(cur))
                cur = []
        elif c == ";" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts]


# No leading ^ here: this is walked via .match(s, pos) at increasing pos,
# and without re.MULTILINE, ^ only ever matches absolute index 0 — with a
# nonzero pos it would silently fail to match anything past the first
# token, exactly the false-negative this caused before being caught by a
# manual smoke test.
_CHAFF_TOKEN_RE = re.compile(
    r"""\s*(?:
        "(?:[^"\\\n]|\\.)*"                    # double-quoted literal
      | '(?:[^'\\\n]|\\.)*'                    # single-quoted literal
      | `(?:[^`\\]|\\.)*`                      # JS template literal
      | chr\s*\([^()]*\)                       # chr(...) call
      | \(char\)\s*\([^()]*\)                  # (char)(...) cast
      | String\s*\.\s*fromCharCode\s*\([^()]*\)   # JS
      | String\s*\.\s*fromCodePoint\s*\([^()]*\)  # JS
      | string\s*\(\s*rune\s*\([^()]*\)\s*\)   # Go
    )\s*""", re.VERBOSE)


def scan_chaff(text: str, language: str) -> List[ObfFinding]:
    op = _CHAFF_CONCAT_OP.get(language)
    if not op:
        return []
    findings = []
    # PHP files interleave <?php ... ?> blocks with raw HTML — split on the
    # blanked-HTML view so a plain-text '<div class="...">' elsewhere in
    # the file can't be mistaken for part of a statement (and so the tag
    # boundaries themselves don't get glued onto a following chaff
    # statement). Line numbers still come from the original `text` below,
    # since the blanked view is byte-for-byte the same length.
    scan_text = _php_code_only(text) if language == "php" else text
    scan_text = _blank_comments(scan_text, hash_comments=(language == "php"))
    for stmt in _split_statements(scan_text):
        raw = stmt
        stripped = stmt.strip()
        if not stripped or op not in stripped:
            continue
        # No separate "contains =/echo/return" pre-check here on purpose:
        # a naive text search for those tokens false-triggers whenever a
        # *literal itself* happens to contain "=" or a keyword-looking
        # substring (e.g. the real-world example this targets has a chaff
        # string literal "=t*&" — its content, not an assignment). The
        # token walk below is the actual proof: it only reaches the end of
        # the statement if every character belongs to a literal/call token
        # or the concat operator, which structurally rules out assignments
        # and keywords without needing to pattern-match string contents.
        pos, pieces = 0, 0
        s = stripped
        while pos < len(s):
            m = _CHAFF_TOKEN_RE.match(s, pos)
            if not m or m.end() == pos:
                break
            pos = m.end()
            pieces += 1
            if pos < len(s) and s[pos] == op[0]:
                pos += 1
        if pos == len(s) and pieces >= 2:
            raw_idx = text.find(raw)
            # locate the actual content within `raw` (skips the <?php tag
            # / leading whitespace stripped above) for an accurate line
            content_idx = text.find(s, max(raw_idx, 0)) if raw_idx != -1 else -1
            idx = content_idx if content_idx != -1 else max(raw_idx, 0)
            findings.append(ObfFinding(line=_line_of(text, idx), kind="chaff",
                                       original=stripped, decoded=""))
    return findings


# ---------------- top-level entry point ----------------

# Reapplied to every decoded value: revealing an obfuscated literal
# shouldn't be a backdoor around the "credentials always masked" guarantee
# elsewhere in the codebase (generic_parser.parse_config / redact_secrets)
# — a base64 or char-code blob can just as easily hide a real connection
# string as it can hide a license nag.
_URL_CREDS_RE = re.compile(r"://([^:/@\s]+):([^@\s]+)@")


def scan_obfuscation(text: str, language: str) -> List[ObfFinding]:
    """Run every safe, static decoder over `text` for `language` and
    return every finding, sorted by line. Never executes `text`."""
    findings: List[ObfFinding] = []
    findings.extend(scan_escapes(text, language))
    findings.extend(scan_charcode(text, language))
    findings.extend(scan_base64(text, language))
    findings.extend(scan_chaff(text, language))
    for f in findings:
        if f.decoded:
            f.decoded = _URL_CREDS_RE.sub("://***:***@", f.decoded)
    findings.sort(key=lambda f: f.line)
    return findings
