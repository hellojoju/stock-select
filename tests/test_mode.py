import pytest
from pathlib import Path

from stock_select.runtime import resolve_runtime, DEMO_DB_PATH, LIVE_DB_PATH, LEGACY_DB_PATH
from stock_select.db import connect, init_db
from stock_select.seed import seed_demo_data


def test_demo_mode_resolves_to_demo_db():
    ctx = resolve_runtime("demo")
    assert ctx.mode == "demo"
    assert ctx.db_path == DEMO_DB_PATH
    assert ctx.database_role == "demo"
    assert ctx.is_demo_data is True


def test_live_mode_resolves_to_live_db():
    ctx = resolve_runtime("live")
    assert ctx.mode == "live"
    assert ctx.db_path == LIVE_DB_PATH
    assert ctx.database_role == "live"
    assert ctx.is_demo_data is False


def test_custom_db_path_recognizes_live():
    ctx = resolve_runtime("live", db_path=str(LIVE_DB_PATH))
    assert ctx.database_role == "live"


def test_custom_db_path_recognizes_demo():
    ctx = resolve_runtime("demo", db_path=str(DEMO_DB_PATH))
    assert ctx.database_role == "demo"


def test_custom_db_path_recognizes_legacy():
    # DEMO_DB_PATH 和 LEGACY_DB_PATH 是同一个文件，所以 legacy 路径返回 demo 角色
    ctx = resolve_runtime("demo", db_path=str(LEGACY_DB_PATH))
    assert ctx.database_role == "demo"


def test_invalid_mode_raises():
    with pytest.raises(ValueError, match="Unknown runtime mode"):
        resolve_runtime("production")


def test_live_mode_forbids_seed_demo(tmp_path):
    db = tmp_path / "live.db"
    conn = connect(db)
    init_db(conn)
    with pytest.raises(SystemExit, match="seed-demo is not allowed in live mode"):
        seed_demo_data(conn)


def test_runtime_context_as_payload():
    ctx = resolve_runtime("live")
    payload = ctx.as_payload()
    assert payload["runtime_mode"] == "live"
    assert payload["database_role"] == "live"
    assert payload["is_demo_data"] is False
