"""CodeBread command line interface."""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__

BANNER = r"""
   ___         _     ___                  _
  / __|___  __| |___| _ )_ _ ___ __ _ __| |
 | (__/ _ \/ _` / -_) _ \ '_/ -_) _` / _` |
  \___\___/\__,_\___|___/_| \___\__,_\__,_|  v{v}
  slice open a codebase and see how it's wired
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="codebread",
        description="Interactive codebase analyzer & visualizer. Scans a "
                    "project, extracts every function/class, maps frontend "
                    "-> backend -> database connections, and opens an "
                    "interactive graph in your browser.")
    parser.add_argument("--path", "-p",
                        help="root folder to scan (prompted if omitted)")
    parser.add_argument("--load", metavar="GRAPH.json",
                        help="serve a previously exported graph JSON "
                             "instead of re-scanning")
    parser.add_argument("--diff", nargs=2, metavar=("OLD.json", "NEW.json"),
                        help="compare two saved graph JSON exports and "
                             "print what changed, then exit")
    parser.add_argument("--port", type=int, default=8137,
                        help="local server port (default: 8137)")
    parser.add_argument("--json", metavar="OUT.json",
                        help="also export the full graph as JSON")
    parser.add_argument("--html", metavar="OUT.html",
                        help="also export a self-contained static HTML file")
    parser.add_argument("--no-open", action="store_true",
                        help="don't auto-open the browser")
    parser.add_argument("--no-serve", action="store_true",
                        help="scan + export only, don't start the server")
    parser.add_argument("--version", action="version",
                        version=f"codebread {__version__}")
    args = parser.parse_args(argv)

    print(BANNER.format(v=__version__))

    from .export import export_html, export_json, load_json

    if args.diff:
        old_path, new_path = args.diff
        for p in (old_path, new_path):
            if not os.path.isfile(p):
                print(f"error: {p} not found", file=sys.stderr)
                return 2
        from .diff import compute_diff, format_diff_report
        report = format_diff_report(compute_diff(load_json(old_path), load_json(new_path)))
        print(report)
        return 0

    if args.load:
        if not os.path.isfile(args.load):
            print(f"error: {args.load} not found", file=sys.stderr)
            return 2
        graph = load_json(args.load)
        print(f"[codebread] Loaded saved graph: {args.load}")
    else:
        root = args.path
        if not root:
            try:
                root = input("Path to the project to analyze: ").strip().strip('"')
            except (EOFError, KeyboardInterrupt):
                print()
                return 1
        if not root:
            print("error: no path given", file=sys.stderr)
            return 2
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            print(f"error: not a folder: {root}", file=sys.stderr)
            return 2

        from .analyzer import analyze
        graph = analyze(root, progress=lambda m: print(f"[codebread] {m}"))

        if graph["stats"]["warnings"]:
            print(f"[codebread] {graph['stats']['warnings']} warning(s) - "
                  f"they are shown as badges in the UI, nothing was hidden.")

    if args.json:
        p = export_json(graph, args.json)
        print(f"[codebread] Graph JSON written to {p}")
    if args.html:
        p = export_html(graph, args.html)
        print(f"[codebread] Static HTML written to {p}")

    if not args.no_serve:
        from .server import serve
        serve(graph, port=args.port, open_browser=not args.no_open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
