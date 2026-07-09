"""Language detection by extension + light content sniffing."""
from __future__ import annotations

import os

# extension -> language id
EXT_MAP = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".vue": "vue", ".svelte": "svelte",
    ".java": "java",
    ".go": "go",
    ".php": "php",
    ".rb": "ruby", ".rake": "ruby",
    ".cs": "csharp",
    ".sql": "sql",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
    ".json": "config", ".yaml": "config", ".yml": "config", ".toml": "config",
    ".ini": "config", ".cfg": "config", ".conf": "config", ".env": "config",
    ".properties": "config", ".xml": "config",
    ".md": "markdown", ".rst": "markdown", ".txt": "text",
    ".sh": "shell", ".bash": "shell", ".ps1": "shell", ".bat": "shell", ".cmd": "shell",
    # known-but-unparsed languages (surface as "unsupported", never silently skip)
    ".rs": "rust", ".kt": "kotlin", ".kts": "kotlin", ".swift": "swift",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".scala": "scala", ".ex": "elixir", ".exs": "elixir", ".erl": "erlang",
    ".lua": "lua", ".r": "r", ".pl": "perl", ".dart": "dart", ".zig": "zig",
}

CONFIG_BASENAMES = {
    ".env", ".env.local", ".env.development", ".env.production", ".env.example",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", "makefile",
    "settings.py", "config.py", "config.js", "config.ts", ".babelrc", ".eslintrc",
    "tsconfig.json", "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "webpack.config.js", "vite.config.js", "vite.config.ts", "next.config.js",
    "tailwind.config.js", "requirements.txt", "gemfile", "pom.xml", "build.gradle",
    "go.mod", "cargo.toml", "composer.json", "appsettings.json", "web.config",
}

# languages CodeBread can actually parse
PARSED = {"python", "javascript", "typescript", "vue", "svelte",
          "java", "go", "php", "ruby", "csharp", "sql"}

# languages that exist but have no parser -> shown as unsupported warnings
KNOWN_UNPARSED = {"rust", "kotlin", "swift", "c", "cpp", "scala", "elixir",
                  "erlang", "lua", "r", "perl", "dart", "zig", "shell"}

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg", ".avif",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".mov", ".avi",
    ".zip", ".gz", ".tar", ".rar", ".7z", ".bz2",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".class", ".jar",
    ".pyc", ".pyo", ".pyd", ".db", ".sqlite", ".sqlite3", ".DS_Store",
    ".lock", ".map", ".wasm",
}

LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "pipfile.lock", "composer.lock", "cargo.lock", "gemfile.lock", "go.sum",
    "bun.lockb",
}


def detect_language(path: str) -> str:
    """Best-effort language id for a file path (with shebang sniffing)."""
    base = os.path.basename(path).lower()
    if base in LOCKFILES:
        return "lockfile"
    if base in CONFIG_BASENAMES or base.startswith(".env"):
        # config files keep their real language when parseable (settings.py etc.)
        ext = os.path.splitext(base)[1]
        lang = EXT_MAP.get(ext, "config")
        return lang if lang in PARSED else "config"
    ext = os.path.splitext(base)[1].lower()
    if ext in EXT_MAP:
        return EXT_MAP[ext]
    if not ext:
        # sniff a shebang
        try:
            with open(path, "rb") as f:
                head = f.read(160)
            if head.startswith(b"#!"):
                line = head.splitlines()[0].decode("utf-8", "ignore")
                if "python" in line:
                    return "python"
                if "node" in line:
                    return "javascript"
                if "ruby" in line:
                    return "ruby"
                if "bash" in line or "sh" in line:
                    return "shell"
        except OSError:
            pass
    return "unknown"


def looks_binary(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext in BINARY_EXTS:
        return True
    try:
        with open(path, "rb") as f:
            chunk = f.read(2048)
        return b"\x00" in chunk
    except OSError:
        return True
