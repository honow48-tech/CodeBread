"""Recursive, .gitignore-aware directory scanner.

Produces a file tree (for the sidebar) plus a flat list of scannable files.
Never crashes silently: unreadable entries become warnings.
"""
from __future__ import annotations

import fnmatch
import os
import re
from typing import Dict, List, Optional, Tuple

from .languages import detect_language, looks_binary

SKIP_DIRS = {
    "node_modules", ".git", ".hg", ".svn", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".nox", "venv", ".venv", "env",
    ".env_dir", "virtualenv", "site-packages", "dist", "build", "out",
    ".next", ".nuxt", ".svelte-kit", ".angular", "coverage", ".coverage_html",
    "target", "bin", "obj", ".idea", ".vscode", ".vs", "vendor", "bower_components",
    ".terraform", ".serverless", ".parcel-cache", ".turbo", ".cache", "eggs",
    ".eggs", "htmlcov", ".gradle", "cmake-build-debug",
}


class _SimpleGitignore:
    """Minimal .gitignore matcher used when `pathspec` isn't installed.

    Supports: comments, blank lines, `dir/` patterns, leading `/` anchors,
    `*` / `?` globs, `**` and `!` negation (basic).
    """

    def __init__(self, lines: List[str]):
        self.rules: List[Tuple[bool, str, bool]] = []  # (negated, regex, dir_only)
        for raw in lines:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            neg = line.startswith("!")
            if neg:
                line = line[1:]
            line = line.strip()
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = line.startswith("/") or "/" in line
            line = line.lstrip("/")
            pat = self._to_regex(line, anchored)
            self.rules.append((neg, pat, dir_only))

    @staticmethod
    def _to_regex(glob: str, anchored: bool) -> str:
        out = []
        i = 0
        while i < len(glob):
            c = glob[i]
            if c == "*":
                if glob[i:i + 2] == "**":
                    out.append(".*")
                    i += 2
                    if i < len(glob) and glob[i] == "/":
                        i += 1
                    continue
                out.append("[^/]*")
            elif c == "?":
                out.append("[^/]")
            else:
                out.append(re.escape(c))
            i += 1
        body = "".join(out)
        prefix = "^" if anchored else "(^|.*/)"
        return prefix + body + "$"

    def matches(self, rel_path: str, is_dir: bool) -> bool:
        rel = rel_path.replace(os.sep, "/")
        ignored = False
        for neg, pat, dir_only in self.rules:
            if dir_only and not is_dir:
                # dir-only pattern still ignores files *inside* that dir
                if not re.match(pat.rstrip("$") + "(/.*)?$", rel):
                    continue
            elif not re.match(pat, rel):
                continue
            ignored = not neg
        return ignored


class GitignoreStack:
    """Every .gitignore in the tree, each scoped to its own folder — like git.

    Frameworks lean on nested ones (Laravel's storage/framework/views/.gitignore
    is just `*` + `!.gitignore`), so reading only the root file lets compiled
    caches flood the scan. Uses pathspec when available.
    """

    def __init__(self, root: str):
        self.root = root
        self._rules: List[Tuple[str, object]] = []  # (folder rel to root, matcher)
        self.load_dir(root, "")

    def load_dir(self, abs_dir: str, rel_dir: str) -> None:
        gi = os.path.join(abs_dir, ".gitignore")
        if not os.path.isfile(gi):
            return
        try:
            with open(gi, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return
        try:
            import pathspec  # type: ignore
            matcher: object = pathspec.GitIgnoreSpec.from_lines(lines)
        except ImportError:
            matcher = _SimpleGitignore(lines)
        self._rules.append((rel_dir.replace(os.sep, "/").strip("/"), matcher))

    def ignored(self, rel_path: str, is_dir: bool) -> bool:
        rel = rel_path.replace(os.sep, "/")
        for base, m in self._rules:
            if base and not rel.startswith(base + "/"):
                continue
            sub = rel[len(base) + 1:] if base else rel
            if isinstance(m, _SimpleGitignore):
                if m.matches(sub, is_dir):
                    return True
            elif m.match_file(sub + "/" if is_dir else sub):
                return True
        return False


def scan(root: str, max_file_kb: int = 1024) -> Dict:
    """Walk `root`, returning {'tree': ..., 'files': [...], 'warnings': [...]}.

    Each entry in `files`: {'path': rel, 'abspath': abs, 'language': str}.
    Tree nodes: {'name', 'path', 'type': 'dir'|'file', 'language', 'children'}.
    """
    root = os.path.abspath(root)
    gitignore = GitignoreStack(root)
    warnings: List[Dict] = []
    files: List[Dict] = []

    def walk_dir(abs_dir: str, rel_dir: str) -> Dict:
        name = os.path.basename(abs_dir) or abs_dir
        node = {"name": name, "path": rel_dir.replace(os.sep, "/"),
                "type": "dir", "children": []}
        try:
            entries = sorted(os.scandir(abs_dir),
                             key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            warnings.append({"path": rel_dir or ".",
                             "message": "Permission denied — folder skipped. "
                                        "Re-run with elevated permissions to include it."})
            node["warning"] = "permission"
            return node
        except OSError as exc:
            warnings.append({"path": rel_dir or ".", "message": f"Unreadable folder: {exc}"})
            node["warning"] = "unreadable"
            return node

        for entry in entries:
            rel = os.path.join(rel_dir, entry.name) if rel_dir else entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_link = entry.is_symlink()
            except OSError:
                continue
            if is_link:
                continue
            if is_dir:
                if entry.name in SKIP_DIRS or entry.name.startswith(".git"):
                    continue
                if gitignore.ignored(rel, True):
                    continue
                gitignore.load_dir(entry.path, rel)
                child = walk_dir(entry.path, rel)
                # keep dirs that contain anything (incl. warning stubs)
                if child["children"] or child.get("warning"):
                    node["children"].append(child)
            else:
                if gitignore.ignored(rel, False):
                    continue
                lang = detect_language(entry.path)
                if lang == "lockfile":
                    continue
                fnode = {"name": entry.name, "path": rel.replace(os.sep, "/"),
                         "type": "file", "language": lang}
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                if size > max_file_kb * 1024:
                    fnode["warning"] = "too-large"
                    warnings.append({"path": fnode["path"],
                                     "message": f"File larger than {max_file_kb} KB — parsing skipped."})
                    node["children"].append(fnode)
                    continue
                if looks_binary(entry.path):
                    if lang in ("unknown", "config"):
                        continue  # true binaries stay out of the tree
                    fnode["warning"] = "binary"
                    node["children"].append(fnode)
                    continue
                node["children"].append(fnode)
                files.append({"path": fnode["path"], "abspath": entry.path,
                              "language": lang})
        return node

    tree = walk_dir(root, "")
    tree["name"] = os.path.basename(root) or root
    return {"tree": tree, "files": files, "warnings": warnings}


def read_text(abspath: str) -> Tuple[str, str]:
    """Read a file as text. Returns (text, error). Never raises."""
    try:
        with open(abspath, "r", encoding="utf-8", errors="replace") as f:
            return f.read(), ""
    except PermissionError:
        return "", "Permission denied reading file."
    except OSError as exc:
        return "", f"Could not read file: {exc}"
