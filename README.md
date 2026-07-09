<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/honow48-tech/CodeBread@main/assets/logo-wordmark.png" alt="CodeBread" width="360">
</p>

<p align="center">
  <b>Slice open any codebase and see how it's actually wired together.</b><br>
  An interactive, zero-dependency map of files → functions → API routes → database tables.
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-1.0.0-2dd4bf">
  <img alt="python" src="https://img.shields.io/badge/python-3.9%2B-0284c7">
  <img alt="deps" src="https://img.shields.io/badge/required%20dependencies-none-2dd4bf">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-8b5cf6">
</p>

---

## What is this

CodeBread scans a project, extracts every function and class, maps how
everything connects — **frontend → API → backend → database** — and renders
it as an interactive node-graph in your browser. Click a file to slice it
open into its functions; click a function to see everything it calls and
everything that calls it, with the full chain lit up end to end.

**The problem it solves:** dropping into a codebase you didn't write — or one
an AI generated for you — and not knowing where anything is. Reading files
one at a time doesn't build a mental model fast. CodeBread builds the model
for you: it finds the routes, follows the `fetch()` calls to the handlers
that answer them, follows the handlers to the tables they touch, and draws
the whole path.

## Why I built this

This started as a personal tool. I kept generating projects with AI and then
staring at the result with no idea how the pieces fit together — which file
called which, where the API boundary actually was, what touched the
database. I wanted something that would just *show* me, instead of me
grepping through the tree file by file. CodeBread is that tool.

It's a v1.0 — actively used by me on my own projects, and I'll keep adding
to it. If it's useful to you too, that's a bonus. Issues and PRs are welcome.

## What it's built with

- **Backend/analysis engine:** pure Python **standard library** — no
  required third-party packages, nothing to `pip install` beyond Python
  itself. Parsing is stdlib `ast` for Python and structural regex for
  everything else (see language table below).
- **Frontend:** vanilla **JavaScript + SVG**, no framework, no build step,
  no `npm install`. The entire UI is three files (`app.js`, `index.html`,
  `style.css`).
- **Serving:** a tiny local server built on `http.server` from the stdlib.

That's it. Clone it, run it, nothing to compile.

---

## Install

```bash
pip install codebread
```

Optional extra (better `.gitignore` matching while scanning):

```bash
pip install codebread[full]        # adds pathspec
```

Requires **Python 3.9+**. Nothing else.

Prefer running from source instead (e.g. to contribute)?

```bash
git clone https://github.com/honow48-tech/CodeBread.git
cd CodeBread
pip install .                      # or: python codebread.py --path /path/to/project
```

## Use

```bash
codebread --path /path/to/project        # scan + open the UI in your browser
codebread                                # prompts for the path
```

That's the whole quick start: point it at a folder, a browser tab opens with
the map already scanned.

### CLI reference

| Flag | What it does |
|---|---|
| `--path, -p PATH` | root folder to scan (prompted if omitted) |
| `--port 8137` | local server port (auto-picks a free one nearby if taken) |
| `--json out.json` | export the full graph as JSON |
| `--load out.json` | re-open a saved scan without re-scanning |
| `--html out.html` | export a **self-contained static HTML** file you can share |
| `--diff old.json new.json` | compare two saved scans and print what changed (files/functions/tables added, removed, changed) |
| `--no-open` | don't auto-open the browser |
| `--no-serve` | scan + export only, don't start the server |
| `--version` | print the installed version |

---

## What you get

- **Explorer sidebar** — the full folder tree, expandable like a file
  explorer; every file tagged with its layer color.
- **Orbit layout (default)** — files float freely in space, spread apart so
  connections stay untangled. Expand a file and its functions arrange in a
  clean ring around it, spoked by straight lines back to the center. A
  **Free** force-directed layout is also available (toggle bottom-right).
- **Focus mode** — clears the canvas so you inspect one file at a time:
  pick a file in the Explorer and only it, its functions, and its direct
  connections show up. Toggle it off to go back to the full overview.
- **Progressive reveal (OSINT-style)** — click a file to slice it open into
  its numbered functions; click a function to draw in what it calls and
  what calls it. Dense codebases stay readable.
- **Full-chain highlight** — select any node and its complete end-to-end
  chain lights up (frontend `fetch()` → `GET /api/users` route → handler →
  `users` table), everything unrelated dims.
- **Right-click for actions** — a context menu on every node, edge, and
  the empty canvas: reveal connections, focus a file, open it in the IDE
  view, jump to a route's source/target, copy a name or path, and more.
- **Insights panel** — flags orphaned functions (no detected callers) and
  circular call chains, both clickable to jump straight to them.
- **Diff mode** — compare two saved scans (`--diff old.json new.json`) to
  see exactly what changed between them.
- **Minimap + breadcrumb** — a live minimap of the whole graph with a
  draggable viewport, and a breadcrumb showing the real folder path of
  whatever's currently selected.
- **Keyboard navigation** — `←`/`→` step through a selected node's
  neighbors, `↑`/`↓` walk back/forward through your selection history,
  `/` to search.
- **Detail panel** — params, return type, auto-generated description
  ("Function 3 · handles GET /api/users · queries users"), every caller and
  callee, clickable.
- **View the actual code** — every function has an expandable
  **▸ View code** section: syntax-highlighted source with real line
  numbers. A full **IDE view** (⌗) opens any file whole, with an outline
  sidebar.
- **Search** (`/`) and **layer filter** (Frontend / Backend / Database /
  Config) in the header.
- **Warnings, never silence** — unreadable files, unsupported languages and
  permission problems show up as ⚠ badges and in the warnings list, never
  hidden. Secrets found in config files are always masked.

## Language support

| Language | Parser | Extracted |
|---|---|---|
| Python | stdlib `ast` (precise) | functions, classes, params/annotations, docstrings, Flask/FastAPI/Django routes, SQLAlchemy/Django models, raw SQL, `requests`/`httpx` calls |
| JavaScript / TypeScript / JSX / TSX / Vue / Svelte | structural regex + brace matching | functions, arrow fns, classes, Express/Nest/Fastify routes, `fetch`/`axios` calls, Mongoose/Prisma/Sequelize/Knex/TypeORM, raw SQL |
| Java, C#, Go, PHP, Ruby | structural regex | functions/methods, classes, Spring/ASP.NET/Laravel/Rails/Gin routes, raw SQL |
| SQL | regex | `CREATE TABLE` schemas with columns |
| Config (`.env`, json/yaml/toml/ini, settings.py…) | key scan | DB connection settings — **credentials always masked** |
| Anything else (Rust, Kotlin, Swift, C/C++…) | — | shown in the UI as "⚠ Unsupported — parsing skipped", never silently dropped |

## How it classifies layers

Score-based heuristics combining framework import signatures
(React/Vue → frontend, Flask/Express → backend, SQLAlchemy/Prisma →
database), folder conventions (`/client`, `/server`, `/models`…), file
extensions, and extracted facts (defines routes → backend, defines models →
database). Ambiguous files are marked **Unclassified** instead of guessed.

## How orphan + cycle detection works

- **Orphaned functions**: any function/method with zero detected incoming
  calls, that isn't a route handler and isn't a common framework entry
  point (`__init__`, `main`, `setUp`, test functions, …). Flagged with a
  badge on the node and listed in the Insights panel — a good starting
  point for finding dead code (heuristic, not exhaustive: it can miss calls
  the static parser doesn't recognize).
- **Circular call chains**: an iterative cycle-detection pass over the
  call graph (no recursion, so it's safe on large codebases) flags
  functions that call each other in a loop, both on the node (↻ badge) and
  as a listed chain in the Insights panel.

## Project layout

```
codebread.py              ← runnable entry point (no install needed)
codebread/
  cli.py                  ← argparse CLI
  scanner.py              ← .gitignore-aware recursive walker
  languages.py             ← language detection / binary sniffing
  parsers/
    python_parser.py      ← ast-based Python extractor
    javascript_parser.py  ← JS/TS/Vue/Svelte extractor
    generic_parser.py     ← Java/C#/Go/PHP/Ruby + SQL + config
  classifier.py           ← frontend/backend/database/config scoring
  connections.py           ← call graph + API↔route + fn↔table matching +
                               orphan/cycle detection
  analyzer.py              ← pipeline orchestration
  diff.py                  ← compares two saved scans
  server.py                ← stdlib local web server
  export.py                ← JSON + single-file HTML export
  web/                     ← the UI (vanilla JS + SVG, zero dependencies)
assets/                    ← logo (.svg source + .png for the README —
                               GitHub blocks same-repo SVG <img> embeds)
```

---

## Roadmap

Already done as of v1.0:

- [x] Orphaned-function and circular-dependency detection
- [x] Diff mode between two scans
- [x] Focus mode, orbit layout, right-click actions, minimap, breadcrumb

Not yet, but planned:

- [ ] "Explain this function" — a plain-language AI summary button
- [ ] More precise multi-language parsing (currently structural regex for
      everything but Python)
- [ ] An automated test suite

Have an idea? Open an issue.

## Contributing

This is a young, actively-changing personal project, so keep that in mind —
but contributions are genuinely welcome:

- **Bugs / ideas** → open an issue with a repro or a description.
- **Pull requests** → welcome, especially for language parser improvements
  or UI polish. Keep the zero-dependency philosophy: the core tool should
  keep running on nothing but the Python standard library, and the UI
  should keep running on vanilla JS with no build step.
- No formal test suite yet, so please describe how you manually verified a
  change in your PR.

## License

[MIT](LICENSE) — use it, modify it, ship it, sell it. No attribution
required beyond keeping the license file. See [LICENSE](LICENSE) for the
full text.
