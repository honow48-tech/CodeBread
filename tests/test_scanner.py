import os

from codebread.languages import detect_language, looks_binary
from codebread.scanner import scan


def _write(root, rel_path, content=""):
    full = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return full


def test_scan_respects_gitignore(tmp_path):
    root = str(tmp_path)
    _write(root, ".gitignore", "ignored.py\nbuild/\n")
    _write(root, "keep.py", "def f(): pass\n")
    _write(root, "ignored.py", "def g(): pass\n")
    _write(root, "build/output.py", "def h(): pass\n")

    result = scan(root)
    paths = {f["path"] for f in result["files"]}
    assert "keep.py" in paths
    assert "ignored.py" not in paths
    assert "build/output.py" not in paths


def test_scan_skips_known_noise_dirs(tmp_path):
    root = str(tmp_path)
    _write(root, "app.py", "def f(): pass\n")
    _write(root, "node_modules/pkg/index.js", "module.exports = {};\n")
    _write(root, ".git/HEAD", "ref: refs/heads/main\n")

    result = scan(root)
    paths = {f["path"] for f in result["files"]}
    assert "app.py" in paths
    assert not any(p.startswith("node_modules/") for p in paths)
    assert not any(p.startswith(".git/") for p in paths)


def test_scan_flags_oversized_files_as_warning(tmp_path):
    root = str(tmp_path)
    big = "x = 1\n" * 200_000  # comfortably over the 1MB default cap
    _write(root, "huge.py", big)

    result = scan(root, max_file_kb=1)
    assert any(w["path"] == "huge.py" for w in result["warnings"])
    assert not any(f["path"] == "huge.py" for f in result["files"])


def test_detect_language_env_files_are_config():
    assert detect_language(".env") == "config"
    assert detect_language(".env.production") == "config"


def test_detect_language_settings_py_stays_python():
    # CONFIG_BASENAMES includes settings.py, but it should still be parsed
    # as real Python (full extraction), not routed into the generic
    # config-key-scan bucket.
    assert detect_language("settings.py") == "python"


def test_detect_language_common_extensions():
    assert detect_language("app.py") == "python"
    assert detect_language("component.tsx") == "typescript"
    assert detect_language("main.go") == "go"
    assert detect_language("style.css") == "css"


def test_looks_binary_by_extension():
    assert looks_binary("photo.png") is True


def test_looks_binary_by_null_byte(tmp_path):
    p = tmp_path / "weird.dat"
    p.write_bytes(b"\x00\x01\x02binary-ish")
    assert looks_binary(str(p)) is True


def test_looks_binary_false_for_text(tmp_path):
    p = tmp_path / "note.unknownext"
    p.write_text("just plain text", encoding="utf-8")
    assert looks_binary(str(p)) is False
