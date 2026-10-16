<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/honow48-tech/CodeBread@main/assets/logo-wordmark.png" alt="CodeBread" width="320">
</p>

<p align="center">
  <b>See how any codebase is wired together.</b><br>
  Files, functions, API routes and database tables, mapped in your browser.
</p>

<p align="center">
  An interactive codebase visualizer: call graph, dependency map and API-to-database tracing<br>
  for Python, JavaScript, TypeScript, PHP, Java, Go, C# and Ruby.
</p>

<p align="center">
  <a href="https://pypi.org/project/codebread/"><img alt="PyPI" src="https://img.shields.io/pypi/v/codebread?color=0e7490&label=pypi&cacheSeconds=3600"></a>
  <a href="https://github.com/honow48-tech/CodeBread/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/honow48-tech/CodeBread/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-5f5c55">
  <img alt="No dependencies" src="https://img.shields.io/badge/dependencies-none-5f5c55">
  <img alt="MIT" src="https://img.shields.io/badge/license-MIT-5f5c55">
</p>

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/honow48-tech/CodeBread@main/assets/overview.gif" alt="The CodeBread overview: project totals, a language breakdown, and a file table that previews each file on hover" width="880">
</p>

## Quick start

```bash
pip install codebread
codebread --path ./my-project
```

A browser tab opens with the project already mapped. Everything runs on your
machine: nothing is uploaded, and nothing in the scanned project is executed.

## What you get

### Overview

Totals, a breakdown of the project by language, and every file in one table.
Hover a row to preview what the file contains and what it talks to.

### Connections

Pick a file to see what uses it, what it uses, and which functions are
linked. Click a neighbour to follow the trail; a breadcrumb takes you back.
It only ever draws one file's neighbourhood, so it stays readable on a
project with thousands of files.

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/honow48-tech/CodeBread@main/assets/connections.gif" alt="The Connections page: callers on the left, the selected file in the middle, the files it uses on the right, joined function to function" width="880">
</p>

### Map

The whole project as a graph. Click a file to open it into its functions.
Click a function to light up everything it calls and everything that calls
it, all the way from a frontend `fetch()` to the database table.

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/honow48-tech/CodeBread@main/assets/map.png" alt="The Map view with one function selected and its call chain highlighted" width="880">
</p>

### Code

Read any file with an outline and syntax highlighting, without leaving the page.

### Your colours

The report follows your system's light or dark mode. Click the dot at the
right of the top bar to pick an accent colour; your choice is saved in your
browser.

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/honow48-tech/CodeBread@main/assets/code.png" alt="The Code view: file tree, function outline and highlighted source" width="880">
</p>

### Context for AI assistants

An AI assistant that reads every file to understand a project spends most of
its tokens on code it never needed. CodeBread can write the map down instead:

```bash
codebread --path ./my-project --md
```

This creates `CODEBREAD.md` in the project: every route, table and function,
and who calls whom. On CodeBread's own repo it's about **13k tokens instead
of 83k** for the full source. The report has the same file one click away:
**Copy for AI** or **Download .md**.

## Commands

| Flag | What it does |
|---|---|
| `--path, -p PATH` | Folder to scan (asks if you leave it out) |
| `--md [FILE]` | Write the AI context file (default: `CODEBREAD.md` in the scanned folder) |
| `--html FILE` | Export the report as one self-contained HTML file you can share |
| `--json FILE` | Save the scan as JSON |
| `--load FILE` | Open a saved JSON scan without scanning again |
| `--diff OLD NEW` | Compare two saved scans and print what changed |
| `--port 8137` | Port for the local server |
| `--no-open` | Don't open the browser |
| `--no-serve` | Scan and export only, no server |
| `--version` | Print the version |

Sharing a report with someone who doesn't have CodeBread:

```bash
codebread --path . --html report.html --no-serve
```

## Languages

| Language | Functions | Routes | API calls | Database |
|---|:---:|:---:|:---:|:---:|
| Python | ✓ | Flask, FastAPI, Django | requests, httpx, aiohttp | SQLAlchemy, Django, peewee |
| JavaScript / TypeScript | ✓ | Express, Fastify, Koa, NestJS | fetch, axios | Prisma, Mongoose, Sequelize, Knex, TypeORM |
| Vue / Svelte | ✓ | same as JS | fetch, axios | same as JS |
| PHP | ✓ | Laravel (incl. closures) | – | Eloquent, migrations, raw SQL |
| Java | ✓ | Spring | – | raw SQL |
| C# | ✓ | ASP.NET | – | raw SQL |
| Go | ✓ | Gin, net/http | – | raw SQL |
| Ruby | ✓ | Rails, Sinatra | – | raw SQL |
| SQL | – | – | – | `CREATE TABLE` schemas |

Files in other languages still appear in the file list, marked as unsupported.

<details>
<summary><b>Full parser details</b></summary>

<br>

Python is parsed with the standard-library `ast` module, so it also gets
parameter types, return types and docstrings. Every other language uses
structural regex with brace matching and gets parameter names only.

| Language | Parser | Functions | Classes | Routes | API calls | ORM models | Raw SQL | Call graph | Page links |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Python | `ast` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| JS / TS / JSX / TSX | regex | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Vue / Svelte | regex, `<script>` only | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Java | regex | ✓ | ✓ | ✓ | – | – | ✓ | ✓ | – |
| C# | regex | ✓ | ✓ | ✓ | – | – | ✓ | ✓ | – |
| Go | regex | ✓ | structs | ✓ | – | – | ✓ | ✓ | – |
| PHP | regex | ✓ | ✓ | ✓ | – | Eloquent + migrations | ✓ | ✓ | ✓ |
| Ruby | regex | ✓ | ✓ | ✓ | – | – | ✓ | ✓ | ✓ |
| SQL | regex | – | – | – | – | tables + columns | ✓ | – | – |
| Config (`.env`, json, yaml, toml, ini, xml) | key scan | – | – | – | – | – | – | – | – |

Config files are only scanned for database connection settings, and
credentials are always masked. Vue and Svelte templates (`@click`, `v-on`)
aren't parsed, only the `<script>` block.

</details>

## How it works

CodeBread reads your files and never runs them. It finds functions, routes
and tables, then matches them up: a `fetch("/api/users")` in the frontend is
linked to the handler that serves `GET /api/users`, and that handler to the
`users` table it queries.

<details>
<summary><b>Layers, unused code and call cycles</b></summary>

<br>

- **Layers.** Each file is scored as frontend, backend, database or config
  from its imports (React, Flask, Prisma…), its folder (`/client`,
  `/server`, `/models`…) and what it contains (routes, models). Files that
  don't clearly fit are left as *Unclassified* rather than guessed.
- **Unused functions.** Functions nothing calls are flagged, except route
  handlers and entry points like `main` and test functions. It's a starting
  point for finding dead code, not proof: calls the parser can't see are
  missed.
- **Call cycles.** Functions that call each other in a loop are flagged on
  the map and listed with the warnings.

</details>

<details>
<summary><b>Decoding obfuscated code</b></summary>

<br>

Some code, often bought or "nulled" PHP scripts, hides its strings behind
hex escapes, `chr()` arithmetic, base64 or junk statements. CodeBread decodes
these **without running anything**: it only evaluates integer literals and
basic operators inside a known decode call (`chr(...)`, `base64_decode(...)`),
and refuses anything else. Decoded values are underlined in the code view
(hover to see the original), and files with findings get a 🔓 badge.

| Language | Hex | Octal | Unicode | Char codes | Base64 | Junk code |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Python | ✓ | ✓ | ✓ | `chr()` | `b64decode` | – |
| JS / TS / Vue / Svelte | ✓ | ✓ | ✓ | `fromCharCode` | `atob` | ✓ |
| Java | – | ✓ | ✓ | `(char)` | `Base64` | ✓ |
| C# | ✓ | – | ✓ | `(char)` | `FromBase64String` | ✓ |
| Go | ✓ | ✓ | ✓ | `rune()` | `base64` | ✓ |
| PHP | ✓ | ✓ | `\u{}` | `chr()` | `base64_decode` | ✓ |
| Ruby | ✓ | ✓ | ✓ | `.chr` | `decode64` | – |

Decoded text goes through the same credential masking as config files.
Junk-code detection needs `;`-terminated statements, so it's off for Python
and Ruby rather than guessing.

</details>

## Safety

- Read-only. Nothing in the scanned project is ever executed.
- Secrets found in `.env` and config files are masked before they reach the
  report, the JSON export or the AI context file.
- Runs on `localhost` only. No network calls, no telemetry.

Found a security issue? Please follow [SECURITY.md](SECURITY.md) instead of
opening a public issue.

## Development

```bash
git clone https://github.com/honow48-tech/CodeBread.git
cd CodeBread
pip install -e ".[full,test]"
pytest -q
```

No build step: the analyzer is Python's standard library, and the UI is three
plain files in [`codebread/web/`](codebread/web) (HTML, CSS and vanilla
JavaScript). `pathspec` in the `full` extra is optional and only improves
`.gitignore` matching.

<details>
<summary><b>Project layout</b></summary>

```
codebread.py             run without installing: python codebread.py --path .
codebread/
  cli.py                 command-line flags
  scanner.py             walks the folder, respects .gitignore
  languages.py           language detection
  parsers/               Python (ast), JS/TS/Vue, and everything else
  classifier.py          frontend / backend / database / config scoring
  connections.py         call graph, API-to-route and function-to-table links
  deobfuscate.py         static decoding of obfuscated literals
  analyzer.py            runs the pipeline
  context.py             the AI context Markdown
  diff.py                compares two saved scans
  export.py              JSON and single-file HTML export
  server.py              local web server
  web/                   the UI
tests/                   pytest suite with a small fixture project per language
```

</details>

## Contributing

Issues and pull requests are welcome, especially parser improvements for more
frameworks. Two rules keep the project easy to run: the core stays on the
Python standard library, and the UI stays plain JavaScript with no build
step. Please run `pytest -q` and add a fixture under `tests/` for new parser
behaviour.

## License

[MIT](LICENSE)
