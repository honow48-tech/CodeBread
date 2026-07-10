import json
import os

from codebread.analyzer import analyze


def _write(root, rel_path, content):
    full = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def test_analyze_end_to_end_small_project(tmp_path):
    root = str(tmp_path)
    _write(root, "app.py", (
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/users')\n"
        "def list_users():\n"
        "    return get_users()\n\n"
        "def get_users():\n"
        "    return []\n"
    ))
    _write(root, "frontend/main.js", (
        "async function loadUsers() {\n"
        "  const res = await fetch('/users');\n"
        "  return res.json();\n"
        "}\n"
    ))

    graph = analyze(root)

    assert graph["stats"]["files"] == 2
    assert graph["stats"]["functions"] >= 3
    assert graph["meta"]["name"] == os.path.basename(root)
    # the graph must be JSON-serializable end to end (what --json/server ship)
    json.dumps(graph)


def test_analyze_never_leaks_env_secrets_into_exported_graph(tmp_path):
    root = str(tmp_path)
    _write(root, ".env", (
        "DATABASE_URL=postgres://admin:hunter2@db.example.com:5432/prod\n"
        "API_KEY=sk-abcdef123456\n"
        "DEBUG=true\n"
    ))
    _write(root, "app.py", "def hello():\n    return 'hi'\n")

    graph = analyze(root)
    dumped = json.dumps(graph)

    assert "hunter2" not in dumped
    assert "sk-abcdef123456" not in dumped
    # non-secret content should still be visible (regression against
    # over-redaction hiding everything)
    assert "DEBUG=true" in dumped


def test_analyze_handles_syntax_errors_without_crashing(tmp_path):
    root = str(tmp_path)
    _write(root, "broken.py", "def broken(:\n    pass\n")

    graph = analyze(root)
    assert graph["stats"]["warnings"] >= 1


def test_analyze_empty_directory(tmp_path):
    graph = analyze(str(tmp_path))
    assert graph["stats"]["files"] == 0
    assert graph["nodes"] == []
