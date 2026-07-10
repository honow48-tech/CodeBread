from conftest import read_fixture

from codebread.models import FileInfo
from codebread.parsers.python_parser import parse_python


def _parse():
    info = FileInfo(path="app.py", language="python")
    parse_python(info, read_fixture("python", "sample_flask.py"))
    return info


def test_extracts_functions():
    info = _parse()
    names = {f.name for f in info.functions}
    assert {"fetch_remote_profile", "get_user", "create_user"} <= names


def test_extracts_orm_model():
    info = _parse()
    assert len(info.tables) == 1
    table = info.tables[0]
    assert table.name == "users"
    assert table.model == "User"
    assert set(table.fields) >= {"id", "name"}


def test_extracts_routes():
    info = _parse()
    by_name = {f.name: f for f in info.functions}
    assert by_name["get_user"].routes[0].method == "GET"
    assert by_name["get_user"].routes[0].path == "/users/<int:user_id>"
    assert by_name["create_user"].routes[0].method == "POST"


def test_extracts_outgoing_api_call():
    info = _parse()
    by_name = {f.name: f for f in info.functions}
    calls = by_name["fetch_remote_profile"].api_calls
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert "/profiles/" in calls[0].url


def test_extracts_orm_query_and_raw_sql():
    info = _parse()
    by_name = {f.name: f for f in info.functions}
    get_refs = by_name["get_user"].db_refs
    assert any(r.table == "User" and r.via == "orm" for r in get_refs)
    create_refs = by_name["create_user"].db_refs
    assert any(r.table == "users" and r.via == "sql" and r.op == "insert"
               for r in create_refs)


def test_syntax_error_is_reported_not_raised():
    info = FileInfo(path="broken.py", language="python")
    parse_python(info, "def broken(:\n    pass\n")
    assert info.functions == []
    assert any("syntax error" in w.lower() for w in info.warnings)
