"""manage.py:PID 文件损坏不崩溃、后端地址 backend/web/mcp 三方一致。

这些都是回归测试:对应 review 里的 #4(int(pid) 抛 ValueError 并吞掉 pkill 兜底)
和 #5(LM_MEM_BACKEND_PORT 文档里有、实际被忽略,web 去连 8901)。
"""
import dataclasses
import importlib
import os

import pytest

_BACKEND_ENV = ("LM_MEM_BACKEND_URL", "LM_MEM_BACKEND_HOST", "LM_MEM_BACKEND_PORT")


@pytest.fixture(scope="module", autouse=True)
def _tmp_data_root(tmp_path_factory):
    """把 PID_DIR 指到临时目录,别在真实 ~/.lm-mem 里建东西。"""
    os.environ["LM_MEM_DATA_DIR"] = str(tmp_path_factory.mktemp("manage-data"))
    yield
    os.environ.pop("LM_MEM_DATA_DIR", None)


@pytest.fixture(autouse=True)
def _clean_manage():
    """每个用例结束后把 manage 的模块级常量恢复成默认值。"""
    yield
    for key in _BACKEND_ENV:
        os.environ.pop(key, None)
    import lm_mem.manage
    importlib.reload(lm_mem.manage)


def _manage(**env):
    for key, val in env.items():
        os.environ[key] = val
    import lm_mem.manage
    return importlib.reload(lm_mem.manage)


# ── #4:PID 文件损坏 ──────────────────────────────────


@pytest.mark.parametrize("junk", ["", "   ", "garbage", "12x", "\n"])
def test_stop_survives_corrupt_pid_file(junk, tmp_path, monkeypatch):
    m = _manage()
    pkills = []
    monkeypatch.setattr(
        m.subprocess, "run",
        lambda *a, **k: (pkills.append(a), type("P", (), {"returncode": 1})())[1],
    )
    pid_file = tmp_path / "web.pid"
    pid_file.write_text(junk)
    svc = dataclasses.replace(m.WEB, pid_file=pid_file)

    m._stop(svc, "127.0.0.1", 7531)  # 不得抛 ValueError

    assert not pid_file.exists(), "陈旧 PID 文件应被清掉"
    assert len(pkills) == 1, "必须继续走 pkill 兜底,而不是提前异常退出"


def test_stop_kills_valid_pid_without_pkill(tmp_path, monkeypatch):
    """PID 有效且身份匹配时走 SIGTERM,不该退化到 pkill。"""
    m = _manage()
    monkeypatch.setattr(m, "_pid_is", lambda svc, pid, host, port: True)
    killed, pkills = [], []
    monkeypatch.setattr(m.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(
        m.subprocess, "run",
        lambda *a, **k: (pkills.append(a), type("P", (), {"returncode": 0})())[1],
    )
    pid_file = tmp_path / "web.pid"
    pid_file.write_text("4242")
    svc = dataclasses.replace(m.WEB, pid_file=pid_file)

    m._stop(svc, "127.0.0.1", 7531)

    assert killed == [(4242, m.signal.SIGTERM)]
    assert pkills == []
    assert not pid_file.exists()


# ── #5:后端端口三方一致 ──────────────────────────────


def test_backend_port_env_reaches_probe_and_web_child():
    m = _manage(LM_MEM_BACKEND_PORT="9123")
    assert m.BACKEND.defaults == ("127.0.0.1", 9123)
    assert "9123" in m.BACKEND.probe(*m.BACKEND.defaults)
    # web 子进程必须被告知同一个后端,否则它会去连默认的 8901
    _, env = m._web_spawn("127.0.0.1", 7531)
    assert env["LM_MEM_BACKEND_URL"] == "http://127.0.0.1:9123"


def test_backend_host_env_honored():
    m = _manage(LM_MEM_BACKEND_HOST="10.0.0.5", LM_MEM_BACKEND_PORT="9123")
    assert m.BACKEND.defaults == ("10.0.0.5", 9123)
    _, env = m._web_spawn("127.0.0.1", 7531)
    assert env["LM_MEM_BACKEND_URL"] == "http://10.0.0.5:9123"


def test_explicit_backend_url_beats_host_port():
    m = _manage(LM_MEM_BACKEND_PORT="9123", LM_MEM_BACKEND_URL="http://box:1234")
    _, env = m._web_spawn("127.0.0.1", 7531)
    assert env["LM_MEM_BACKEND_URL"] == "http://box:1234"


def test_default_backend_url_when_nothing_set():
    m = _manage()
    assert m._backend_url() == "http://127.0.0.1:8901"
