from conftest import read_fixture

from codebread.models import FileInfo
from codebread.parsers.generic_parser import (parse_generic, parse_sql,
                                               redact_secrets)


def _parse(language, *fixture_parts):
    info = FileInfo(path="/".join(fixture_parts), language=language)
    parse_generic(info, read_fixture(*fixture_parts), language)
    return info


def test_java_functions_class_and_route():
    info = _parse("java", "java", "UserController.java")
    names = {f.name for f in info.functions}
    assert {"getUser", "createUser"} <= names
    by_name = {f.name: f for f in info.functions}
    assert by_name["getUser"].routes[0].method == "GET"
    assert by_name["getUser"].routes[0].path == "/users/{id}"


def test_java_raw_sql_detected():
    info = _parse("java", "java", "UserController.java")
    by_name = {f.name: f for f in info.functions}
    assert any(r.table == "users" and r.op == "insert"
               for r in by_name["createUser"].db_refs)


def test_csharp_functions_and_route():
    info = _parse("csharp", "csharp", "UsersController.cs")
    names = {f.name for f in info.functions}
    assert {"GetUser", "CreateUser"} <= names
    by_name = {f.name: f for f in info.functions}
    assert by_name["GetUser"].routes[0].method == "GET"


def test_go_functions_and_struct():
    info = _parse("go", "go", "sample.go")
    names = {f.name for f in info.functions}
    assert {"getUser", "createUser", "main"} <= names
    # structs are extracted as classes via a separate pass in analyzer/UI —
    # parse_generic itself doesn't record "class" nodes for Go, only imports
    # and functions, so we just check the struct's type line didn't get
    # mistaken for a function.
    assert "User" not in names


def test_go_raw_sql_detected():
    info = _parse("go", "go", "sample.go")
    by_name = {f.name: f for f in info.functions}
    assert any(r.table == "users" and r.op == "insert"
               for r in by_name["createUser"].db_refs)


def test_php_functions_route_and_page_link():
    info = _parse("php", "php", "users.php")
    names = {f.name for f in info.functions}
    assert {"find", "render_user_page"} <= names
    assert any(r.method == "GET" and r.path == "/users/{id}"
               for r in info.routes)
    assert "dashboard.php" in info.links


def test_php_import_extracted():
    info = _parse("php", "php", "users.php")
    assert "db.php" in info.imports


def test_ruby_functions_and_route():
    info = _parse("ruby", "ruby", "users_controller.rb")
    names = {f.name for f in info.functions}
    assert {"show", "create", "helper_method"} <= names
    assert any(r.method == "GET" and r.path == "/users/:id"
               for r in info.routes)


def test_sql_create_table_schema():
    info = FileInfo(path="schema.sql", language="sql")
    parse_sql(info, read_fixture("sql", "schema.sql"))
    by_name = {t.name: t for t in info.tables}
    assert set(by_name) == {"users", "orders"}
    assert set(by_name["users"].fields) >= {"id", "name", "email"}
    # constraint lines must not be mistaken for columns
    assert "FOREIGN" not in by_name["orders"].fields


def test_redact_secrets_masks_password_and_url_creds():
    text = (
        "DATABASE_URL=postgres://admin:hunter2@db.example.com:5432/prod\n"
        "API_KEY=sk-abcdef123456\n"
        "DEBUG=true\n"
    )
    out = redact_secrets(text)
    assert "hunter2" not in out
    assert "sk-abcdef123456" not in out
    assert "DEBUG=true" in out
    assert "db.example.com" in out  # non-secret parts stay readable


def test_redact_secrets_preserves_line_count():
    text = "A=1\nB=2\nPASSWORD=x\nC=3\n"
    out = redact_secrets(text)
    assert len(out.splitlines()) == len(text.splitlines())
