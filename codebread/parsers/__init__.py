"""Parser dispatch: pick the right extractor for a file's language."""
from __future__ import annotations

from typing import Optional

from ..models import FileInfo
from ..languages import PARSED, KNOWN_UNPARSED


def parse_file(rel_path: str, text: str, language: str) -> FileInfo:
    """Parse `text` and return a populated FileInfo. Never raises."""
    info = FileInfo(path=rel_path, language=language)
    info.loc = text.count("\n") + 1 if text else 0

    try:
        if language == "python":
            from .python_parser import parse_python
            parse_python(info, text)
        elif language in ("javascript", "typescript", "vue", "svelte"):
            from .javascript_parser import parse_javascript
            parse_javascript(info, text, language)
        elif language in ("java", "go", "php", "ruby", "csharp"):
            from .generic_parser import parse_generic
            parse_generic(info, text, language)
        elif language == "sql":
            from .generic_parser import parse_sql
            parse_sql(info, text)
        elif language == "config":
            from .generic_parser import parse_config
            parse_config(info, text)
        elif language in KNOWN_UNPARSED:
            info.warnings.append(
                f"Unsupported: {language} — parsing skipped.")
        # html/css/markdown/text/unknown: listed in the tree, nothing to extract
        info.parsed = language in PARSED or language == "config"
    except Exception as exc:  # a parser bug must never kill the scan
        info.warnings.append(f"Parser error ({type(exc).__name__}): {exc}")
        info.parsed = False

    # assign "Function 1", "Function 2", ... numbering per file,
    # and attach a source snippet for the UI's expandable code viewer
    lines = text.splitlines()
    for i, fn in enumerate(info.functions, 1):
        fn.index = i
        if 0 < fn.line <= len(lines):
            end = max(fn.line, min(fn.end_line or fn.line, len(lines)))
            snippet = lines[fn.line - 1:min(end, fn.line - 1 + 120)]
            while snippet and not snippet[-1].strip():
                snippet.pop()
            fn.code = "\n".join(snippet)
            if end - fn.line + 1 > 120:
                fn.code += "\n… (truncated)"
    return info
