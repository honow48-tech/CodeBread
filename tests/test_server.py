import os
import threading
import urllib.error
import urllib.request

import pytest

from codebread.server import WEB_DIR, build_server, safe_web_path


def test_safe_web_path_allows_files_inside_web_dir():
    resolved = safe_web_path("app.js")
    assert resolved is not None
    assert os.path.isfile(resolved)


def test_safe_web_path_blocks_relative_traversal():
    assert safe_web_path("../../../../Windows/win.ini") is None


@pytest.mark.skipif(os.name != "nt",
                    reason="drive-absolute os.path.join discard is an "
                           "ntpath-only quirk; on POSIX there's no drive "
                           "letter so the path safely stays under WEB_DIR")
def test_safe_web_path_blocks_windows_drive_absolute_traversal():
    # The bug this locks in: os.path.join(WEB_DIR, "C:/x") on Windows
    # discards WEB_DIR entirely because the second arg is drive-absolute.
    drive = os.path.splitdrive(WEB_DIR)[0] or "C:"
    assert safe_web_path(f"{drive}/Windows/win.ini") is None


def test_safe_web_path_blocks_unc_style_path():
    assert safe_web_path("//server/share/file.txt") is None


def test_build_server_with_port_zero_lets_os_assign_a_port():
    # Regression: port 0 ("let the OS pick") is a falsy int, and an earlier
    # version of _free_port() returned 0 for both "OS-assigned" and "no
    # free port found", so `if not port:` treated a successful bind as
    # failure.
    server = build_server({"nodes": [], "edges": [], "tree": {}, "stats": {}}, port=0)
    try:
        assert server is not None
        assert server.server_port > 0
    finally:
        if server is not None:
            server.server_close()


@pytest.fixture
def live_server():
    server = build_server({"nodes": [], "edges": [], "tree": {}, "stats": {}}, port=0)
    assert server is not None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_server_serves_legit_asset(live_server):
    with urllib.request.urlopen(f"{live_server}/app.js") as resp:
        assert resp.status == 200
        assert len(resp.read()) > 0


def test_live_server_serves_data_json(live_server):
    with urllib.request.urlopen(f"{live_server}/data.json") as resp:
        assert resp.status == 200


@pytest.mark.skipif(os.name != "nt",
                    reason="drive-absolute os.path.join discard is an "
                           "ntpath-only quirk; on POSIX the request just "
                           "404s as a normal missing file under WEB_DIR")
def test_live_server_rejects_drive_absolute_traversal(live_server):
    drive = os.path.splitdrive(WEB_DIR)[0] or "C:"
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{live_server}/{drive}/Windows/win.ini")
    assert exc.value.code == 403
