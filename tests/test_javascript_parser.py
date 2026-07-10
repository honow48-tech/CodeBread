from conftest import read_fixture

from codebread.models import FileInfo
from codebread.parsers.javascript_parser import parse_javascript


def _parse_express():
    info = FileInfo(path="server.js", language="javascript")
    parse_javascript(info, read_fixture("javascript", "sample_express.js"), "javascript")
    return info


def _parse_ts():
    info = FileInfo(path="app.ts", language="typescript")
    parse_javascript(info, read_fixture("javascript", "sample_types.ts"), "typescript")
    return info


def _parse_vue():
    info = FileInfo(path="Counter.vue", language="vue")
    parse_javascript(info, read_fixture("vue", "sample.vue"), "vue")
    return info


def test_extracts_functions_and_class_method():
    info = _parse_express()
    names = {f.name for f in info.functions}
    assert {"fetchExternalProfile", "getUser", "createUser", "getById"} <= names
    by_name = {f.name: f for f in info.functions}
    assert by_name["getById"].parent_class == "UserService"
    assert by_name["getById"].kind == "method"


def test_extracts_mongoose_model():
    info = _parse_express()
    assert len(info.tables) == 1
    table = info.tables[0]
    assert table.model == "User"
    assert set(table.fields) >= {"name", "email"}


def test_extracts_route_attached_to_named_handler():
    info = _parse_express()
    all_routes = list(info.routes)
    for f in info.functions:
        all_routes.extend(f.routes)
    methods_paths = {(r.method, r.path) for r in all_routes}
    assert ("GET", "/users/:id") in methods_paths
    assert ("POST", "/users") in methods_paths


def test_extracts_fetch_api_call():
    info = _parse_express()
    by_name = {f.name: f for f in info.functions}
    calls = by_name["fetchExternalProfile"].api_calls
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert "api.example.com" in calls[0].url


def test_extracts_orm_usage_and_raw_sql():
    info = _parse_express()
    by_name = {f.name: f for f in info.functions}
    assert any(r.table == "User" for r in by_name["getUser"].db_refs)
    assert any(r.table == "users" and r.via == "sql" and r.op == "insert"
               for r in by_name["createUser"].db_refs)


def test_typescript_type_annotations_dont_break_extraction():
    info = _parse_ts()
    names = {f.name for f in info.functions}
    assert {"getUserName", "double", "greet"} <= names
    by_name = {f.name: f for f in info.functions}
    assert by_name["greet"].parent_class == "Greeter"


def test_vue_script_setup_functions_extracted_and_template_excluded():
    info = _parse_vue()
    names = {f.name for f in info.functions}
    assert {"increment", "logChange"} <= names
    # template-only content shouldn't leak in as a function name
    assert "button" not in names
