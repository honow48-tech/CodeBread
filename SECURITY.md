# Security Policy

CodeBread is a local developer tool: it scans a project on your own
machine and serves the resulting map on `127.0.0.1` only. It never sends
your code anywhere. That said, it does read arbitrary files on disk and
runs a local HTTP server, so it has a real attack surface — please report
issues rather than silently working around them.

## Supported versions

Only the latest release on PyPI is supported. Please upgrade
(`pip install --upgrade codebread`) before reporting an issue, in case it's
already fixed.

## Reporting a vulnerability

Preferred: use GitHub's **private vulnerability reporting** for this repo —
[Security tab → "Report a vulnerability"](https://github.com/honow48-tech/CodeBread/security/advisories/new).
This opens a private draft advisory only you and the maintainer can see,
which is safer than a public issue for anything exploitable.

If that's unavailable, open a regular issue with **no exploit details**,
just "possible security issue, please contact me" — a maintainer will
follow up to get specifics privately.

Please include:
- what you found and why it's exploitable (impact, not just a code smell)
- steps to reproduce, or a minimal repro project/snippet
- the CodeBread version (`codebread --version`) and OS

## Scope

In scope:
- the local web server (`codebread/server.py`) — path traversal, anything
  that lets it read/serve files outside its own `web/` directory
- credential/secret handling in scanned config files (`.env`, etc.) —
  anything that leaks a secret CodeBread claims to mask
- the parsers (`codebread/parsers/`) — crashes or resource exhaustion on
  malicious/malformed input files (denial of service via a crafted repo)
- the exported HTML/JSON artifacts (`--json`/`--html`) — anything that
  makes a shared export unsafe to open

Generally out of scope:
- parser *inaccuracy* (missed/misattributed functions, routes, etc.) —
  that's a correctness bug, please file it as a normal issue
- issues that require the attacker to already have arbitrary code
  execution on the machine running CodeBread

## Response

This is a small, actively-maintained personal project — no formal SLA, but
reports are taken seriously and fixed promptly. You'll get an
acknowledgment and, once fixed, credit in the release notes if you'd like.
