from codebread.connections import build_graph
from codebread.models import ApiCall, DbRef, FileInfo, FunctionInfo, Route, TableInfo


def _fn(name, calls=None, routes=None, api_calls=None, db_refs=None, line=1):
    return FunctionInfo(
        name=name, line=line, end_line=line + 5,
        calls=calls or [], routes=routes or [],
        api_calls=api_calls or [], db_refs=db_refs or [],
    )


def build(files):
    return build_graph(files, tree={}, warnings=[])


def test_same_file_call_edge():
    f = FileInfo(path="app.py", language="python", layer="backend",
                 functions=[_fn("main", calls=["helper"]), _fn("helper", line=10)])
    g = build([f])
    call_edges = [e for e in g["edges"] if e["kind"] == "call"]
    assert any(e["source"].endswith("::main@1") and e["target"].endswith("::helper@10")
               for e in call_edges)


def test_cross_file_call_resolves_unique_name():
    a = FileInfo(path="app.py", language="python", layer="backend",
                 functions=[_fn("main", calls=["fetch_user"])])
    b = FileInfo(path="utils.py", language="python", layer="backend",
                 functions=[_fn("fetch_user", line=1)])
    g = build([a, b])
    call_edges = [e for e in g["edges"] if e["kind"] == "call"]
    assert any(e["target"] == "utils.py::fetch_user@1" for e in call_edges)


def test_api_call_matches_route_despite_param_syntax_difference():
    frontend = FileInfo(path="frontend.js", language="javascript", layer="frontend",
                        api_calls=[ApiCall(method="GET", url="/api/users/:id")])
    backend = FileInfo(path="backend.py", language="python", layer="backend",
                       functions=[_fn("get_user",
                                     routes=[Route(method="GET", path="/api/users/<id>")])])
    g = build([frontend, backend])
    api_edges = [e for e in g["edges"] if e["kind"] == "api"]
    assert len(api_edges) == 1
    assert api_edges[0]["target"] == "backend.py::get_user@1"


def test_db_edge_links_function_to_table():
    models = FileInfo(path="models.py", language="python", layer="database",
                      tables=[TableInfo(name="users", model="User")])
    backend = FileInfo(path="backend.py", language="python", layer="backend",
                       functions=[_fn("get_user",
                                     db_refs=[DbRef(table="User", op="query", via="orm")])])
    g = build([models, backend])
    db_edges = [e for e in g["edges"] if e["kind"] == "db"]
    assert len(db_edges) == 1
    assert db_edges[0]["target"] == "table::users"


def test_include_edge_resolves_python_import():
    idx = FileInfo(path="index.py", language="python", layer="backend",
                   imports=["helperlib"])
    lib = FileInfo(path="helperlib.py", language="python", layer="backend")
    g = build([idx, lib])
    include_edges = [e for e in g["edges"] if e["kind"] == "include"]
    assert any(e["source"] == "index.py" and e["target"] == "helperlib.py"
               for e in include_edges)


def test_orphan_detection_respects_entry_names():
    f = FileInfo(path="app.py", language="python", layer="backend",
                 functions=[_fn("main"), _fn("never_called", line=10)])
    g = build([f])
    by_label_line = {(n["label"], n.get("line")): n for n in g["nodes"]
                     if n["kind"] == "function"}
    assert not by_label_line[("main", 1)].get("orphan")
    assert by_label_line[("never_called", 10)].get("orphan") is True


def test_cycle_detection_flags_both_functions_and_reports_cycle():
    f = FileInfo(path="cycle.py", language="python", layer="backend",
                 functions=[_fn("a", calls=["b"]), _fn("b", calls=["a"], line=10)])
    g = build([f])
    fn_nodes = [n for n in g["nodes"] if n["kind"] == "function"]
    assert all(n.get("cycle") for n in fn_nodes)
    assert g["stats"]["cycles"] == 1
    assert len(g["cycles"]) == 1


def test_stats_counts_are_consistent():
    f = FileInfo(path="app.py", language="python", layer="backend",
                 functions=[_fn("main", calls=["helper"]), _fn("helper", line=10)])
    g = build([f])
    assert g["stats"]["files"] == 1
    assert g["stats"]["functions"] == 2
    assert g["stats"]["connections"] == len(g["edges"])
