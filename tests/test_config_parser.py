from codebread.models import FileInfo
from codebread.parsers.generic_parser import parse_config


def _parse(text):
    info = FileInfo(path=".env", language="config")
    parse_config(info, text)
    return info


def test_secret_keys_are_masked_in_summary():
    info = _parse("PASSWORD=hunter2\nAPI_KEY=sk-live-abc123\n")
    joined = "\n".join(info.db_config)
    assert "hunter2" not in joined
    assert "sk-live-abc123" not in joined
    assert "masked" in joined


def test_db_url_credentials_masked_but_host_kept():
    info = _parse("DATABASE_URL=postgres://admin:hunter2@db.example.com:5432/prod\n")
    joined = "\n".join(info.db_config)
    assert "hunter2" not in joined
    assert "db.example.com" in joined


def test_non_db_non_secret_keys_ignored():
    info = _parse("DEBUG=true\nPORT=8080\n")
    assert info.db_config == []


def test_comments_and_blank_lines_skipped():
    info = _parse("# PASSWORD=shouldnotmatch\n\nPASSWORD=realsecret\n")
    joined = "\n".join(info.db_config)
    assert "shouldnotmatch" not in joined
    assert "realsecret" not in joined  # masked either way
    assert joined.count("PASSWORD") == 1
