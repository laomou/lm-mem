"""backend 客户端连接测试。"""
import importlib
import os
from pathlib import Path

import pytest


def test_connect_returns_none_when_no_backend(srv, free_port):
    # _connect 连不上应快速返回 None,不抛异常
    assert srv._connect("127.0.0.1", free_port) is None


# ── #8:模式由环境变量显式选择,库代码不嗅探 pytest ────


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    """用干净环境重载 backend,收尾再恢复默认。"""
    monkeypatch.delenv("LM_MEM_BACKEND_URL", raising=False)
    monkeypatch.delenv("LM_MEM_EMBEDDED", raising=False)
    monkeypatch.setenv("LM_MEM_DB_PATH", str(tmp_path / "db"))
    import lm_mem.backend as b
    yield importlib.reload(b)
    os.environ.pop("LM_MEM_DB_PATH", None)
    importlib.reload(b)


def test_no_url_no_embedded_raises(backend):
    """既没 BACKEND_URL 也没 EMBEDDED → 明确报错,不得静默退化成嵌入式。"""
    with pytest.raises(RuntimeError) as exc:
        backend._init_client()
    msg = str(exc.value)
    assert "LM_MEM_BACKEND_URL" in msg and "LM_MEM_EMBEDDED" in msg


def test_embedded_flag_enables_embedded_client(backend, monkeypatch):
    monkeypatch.setenv("LM_MEM_EMBEDDED", "1")
    assert backend._init_client() is not None
    assert Path(backend.DB_PATH).is_dir()  # 真要落盘时才建目录


@pytest.mark.parametrize("off", ["", "0", "false", "no", "off", "  "])
def test_embedded_flag_falsey_values_stay_off(backend, monkeypatch, off):
    monkeypatch.setenv("LM_MEM_EMBEDDED", off)
    assert backend._embedded_enabled() is False
    with pytest.raises(RuntimeError):
        backend._init_client()


def test_backend_url_takes_precedence_over_embedded(backend, monkeypatch):
    """给了 URL 就必须走 HTTP 客户端,不能因为 EMBEDDED 也开着就抄近路。"""
    monkeypatch.setenv("LM_MEM_EMBEDDED", "1")
    monkeypatch.setenv("LM_MEM_BACKEND_URL", "http://127.0.0.1:1")  # 必然连不上
    monkeypatch.setattr(backend, "_embedded_client",
                        lambda: pytest.fail("不该退化到嵌入式"))
    with pytest.raises(RuntimeError, match="连接失败"):
        backend._init_client()


# ── #9:import 不得有建目录副作用 ─────────────────────


def test_import_does_not_create_db_dir(tmp_path, monkeypatch):
    """纯客户端模式下 DB_PATH 用不到,import 时不该把它建出来。"""
    target = tmp_path / "never-created"
    monkeypatch.setenv("LM_MEM_DB_PATH", str(target))
    import lm_mem.backend as b
    importlib.reload(b)
    try:
        assert b.DB_PATH == str(target)
        assert not target.exists(), "import 不应产生建目录副作用"
    finally:
        os.environ.pop("LM_MEM_DB_PATH", None)
        importlib.reload(b)
