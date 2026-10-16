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


def test_laravel_migrations_models_routes_and_calls():
    from codebread.connections import build_graph

    def php(path, src):
        info = FileInfo(path=path, language="php")
        parse_generic(info, src, "php")
        return info

    files = [
        php("database/migrations/1_create_bookings.php", """<?php
return new class extends Migration { public function up(): void {
    Schema::create('bookings', function (Blueprint $table) {
        $table->id(); $table->string('reference'); $table->timestamps();
    });
    Schema::create('equipment', function (Blueprint $table) { $table->id(); });
} };"""),
        php("database/migrations/2_add_status.php", """<?php
return new class extends Migration { public function up(): void {
    Schema::table('bookings', function (Blueprint $table) { $table->string('status'); });
} };"""),
        php("app/Models/Booking.php", "<?php\nclass Booking extends Model {\n"
            "    public function user() { return $this->belongsTo(User::class); }\n}\n"),
        php("app/Models/Equipment.php", "<?php\nclass Equipment extends Model {}\n"),
        php("app/Support/Icons.php", "<?php\nclass Icons { public static function label($k) { return $k; } }\n"),
        php("app/Widgets/Stats.php", r"""<?php
use App\Support\Icons;
class Stats { public function table($t) {
    return $t->label('Total')->value(Booking::where('status', 'x')->count());
} }"""),
        php("routes/web.php", """<?php
Route::get('/', function () { return view('welcome'); });
Route::get('/icons', function () { return Icons::label('x'); });"""),
        FileInfo(path="resources/views/welcome.blade.php", language="php"),
    ]
    g = build_graph(files, {"type": "dir", "children": []}, [])
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}

    # migrations define tables; an alter adds columns without stealing the source
    assert nodes["table::bookings"]["fields"] == ["id", "reference", "created_at",
                                                 "updated_at", "status"]
    assert nodes["table::bookings"]["file"] == "database/migrations/1_create_bookings.php"
    # models snap to the real table: Booking -> bookings, Equipment -> equipment
    assert nodes["table::bookings"]["model"] == "Booking"
    assert nodes["table::equipment"]["model"] == "Equipment"
    assert "table::equipments" not in nodes
    # closure routes land on the routes file; view() links to the Blade file
    assert {r["path"] for r in nodes["routes/web.php"]["routes"]} == {"/", "/icons"}
    assert ("routes/web.php", "resources/views/welcome.blade.php", "link") in edges
    # static calls count, $obj->label() does not; Eloquent calls reach the table
    label = "app/Support/Icons.php::label@2"
    assert ("routes/web.php", label, "call") in edges
    assert not any(s.startswith("app/Widgets/Stats.php") and t == label for s, t, _ in edges)
    assert ("app/Widgets/Stats.php::table@3", "table::bookings", "db") in edges
    # `use App\...` resolves to the file (PSR-4)
    assert ("app/Widgets/Stats.php", "app/Support/Icons.php", "include") in edges
    # framework-called code isn't "unused": migration hooks, Eloquent relations
    by_label = {(n.get("file"), n["label"]): n for n in g["nodes"]}
    assert not by_label[("database/migrations/1_create_bookings.php", "up")].get("orphan")
    assert not by_label[("app/Models/Booking.php", "user")].get("orphan")
