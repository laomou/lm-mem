"""manage.py:PID 文件损坏不崩溃、后端地址 backend/web/mcp 三方一致。

这些都是回归测试:对应 review 里的 #4(int(pid) 抛 ValueError 并吞掉 pkill 兜底)
和 #5(LM_MEM_BACKEND_PORT 文档里有、实际被忽略,web 去连 8901)。
"""
import dataclasses
import importlib
import os
import sys

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
    monkeypatch.setattr(m, "_await_exit", lambda pid, timeout=10.0: True)  # 假装已退出
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

    assert (4242, m.signal.SIGTERM) in killed
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


# ── #1:启动时自动回收过期记忆 ─────────────────────────


@pytest.fixture()
def purge_env(tmp_path, monkeypatch):
    """嵌入式模式 + 干净临时 DB,供 _auto_purge 测试用。"""
    monkeypatch.setenv("LM_MEM_DB_PATH", str(tmp_path / "db"))
    monkeypatch.setenv("LM_MEM_EMBEDDED", "1")
    monkeypatch.delenv("LM_MEM_BACKEND_URL", raising=False)
    import lm_mem.backend as b
    import lm_mem.client as c
    importlib.reload(b)
    importlib.reload(c)
    yield c.MemoryClient()
    importlib.reload(b)


def _expire(client, mem_id):
    col = client._col()
    meta = col.get(ids=[mem_id], include=["metadatas"])["metadatas"][0]
    meta["expires_at"] = 1.0
    col.update(ids=[mem_id], metadatas=[meta])


def test_auto_purge_deletes_expired_on_startup(purge_env, monkeypatch):
    client = purge_env
    keep = client.add("长期偏好", user_id="u")["id"]
    dead = client.add("临时便签", user_id="u", force=True, ttl_seconds=3600)["id"]
    _expire(client, dead)
    assert client._col().count() == 2

    m = _manage()
    m._auto_purge()

    assert client._col().count() == 1, "过期项应被真正删除,而不只是检索时被过滤"
    assert client._col().get(ids=[keep])["ids"] == [keep]
    assert client._col().get(ids=[dead])["ids"] == []


def test_auto_purge_can_be_disabled(purge_env, monkeypatch):
    client = purge_env
    dead = client.add("临时便签", user_id="u", ttl_seconds=3600)["id"]
    _expire(client, dead)
    monkeypatch.setenv("LM_MEM_AUTO_PURGE", "0")

    m = _manage()
    m._auto_purge()

    assert client._col().count() == 1, "LM_MEM_AUTO_PURGE=0 时不该删任何东西"


def test_auto_purge_never_blocks_startup(monkeypatch, capsys):
    """后端连不上等任何异常都只警告,绝不抛出 —— 否则 MCP 起不来。"""
    m = _manage()
    monkeypatch.delenv("LM_MEM_AUTO_PURGE", raising=False)
    monkeypatch.setenv("LM_MEM_BACKEND_URL", "http://127.0.0.1:1")  # 必然连不上
    monkeypatch.delenv("LM_MEM_EMBEDDED", raising=False)
    import lm_mem.backend as b
    importlib.reload(b)
    m._auto_purge()          # 不得抛异常
    assert "跳过过期清理" in capsys.readouterr().err
    importlib.reload(b)


# ── chroma 可执行文件解析(finding #1) ─────────────────
#
# 从 PyPI 装、不激活 venv 时 `lm-mem backend start` 会 FileNotFoundError:
# _backend_spawn 用裸 "chroma" 靠 PATH,而 chroma 装在 venv/bin 里。
# 所有单测都跑在 LM_MEM_EMBEDDED=1 下、从不起 chroma CLI,故此前无覆盖。


def test_resolve_chroma_prefers_sys_executable_dir(tmp_path, monkeypatch):
    """chroma 与 sys.executable 同目录时,用它的绝对路径(不靠 PATH)。"""
    (tmp_path / "chroma").write_text("")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    monkeypatch.delenv("LM_MEM_CHROMA", raising=False)
    m = _manage()
    assert m._resolve_chroma() == str(tmp_path / "chroma")


def test_resolve_chroma_env_override_wins(tmp_path, monkeypatch):
    """LM_MEM_CHROMA 显式覆盖优先于同目录探测。"""
    (tmp_path / "chroma").write_text("")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    monkeypatch.setenv("LM_MEM_CHROMA", "/opt/chroma")
    m = _manage()
    assert m._resolve_chroma() == "/opt/chroma"


def test_resolve_chroma_falls_back_to_bare(tmp_path, monkeypatch):
    """同目录没有 chroma 时退回裸命令,靠 PATH(保持老行为)。"""
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))  # 旁边无 chroma
    monkeypatch.delenv("LM_MEM_CHROMA", raising=False)
    m = _manage()
    assert m._resolve_chroma() == "chroma"


def test_backend_spawn_uses_resolved_chroma(tmp_path, monkeypatch):
    """_backend_spawn 的 argv[0] 应是解析后的路径,而非永远裸 'chroma'。"""
    (tmp_path / "chroma").write_text("")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    monkeypatch.delenv("LM_MEM_CHROMA", raising=False)
    m = _manage()
    argv, _ = m._backend_spawn("127.0.0.1", 8901)
    assert argv[0] == str(tmp_path / "chroma")
    assert argv[1] == "run"


# ── _await_exit / _stop 等进程真退(优雅停服务) ──────────


def test_await_exit_returns_when_process_gone(monkeypatch):
    """探测到进程消失(ProcessLookupError)→ 返回 True,不发 SIGKILL。"""
    m = _manage()
    calls = []
    def fake_kill(pid, sig):
        calls.append(sig)
        if sig == 0:
            raise ProcessLookupError()   # 一上来就没了
        raise AssertionError("不该发 SIGKILL")
    monkeypatch.setattr(m.os, "kill", fake_kill)
    assert m._await_exit(999999, timeout=2) is True
    assert m.signal.SIGKILL not in calls


def test_await_exit_sigkills_after_timeout(monkeypatch):
    """进程一直存活 → 超时后发 SIGKILL 兜底,返回 False。"""
    m = _manage()
    sigkilled = []
    def fake_kill(pid, sig):
        if sig == 0:
            return                       # 永远"还在"
        sigkilled.append(sig)
    monkeypatch.setattr(m.os, "kill", fake_kill)
    assert m._await_exit(4242, timeout=0.5) is False
    assert sigkilled == [m.signal.SIGKILL]


def test_stop_waits_for_real_exit(tmp_path, monkeypatch):
    """_stop 发完 SIGTERM 后必须调用 _await_exit 等进程真退,而不是立刻返回。

    用一个"前 N 次探测存活、之后消失"的假 os.kill 模拟 SIGTERM 生效的过程,
    验证 _stop 确实在等(而不是发完信号就走)。真实进程的父子/僵尸语义与被测
    逻辑无关,不引入。
    """
    m = _manage()
    probes = {"n": 0}
    sigterm_sent = []

    def fake_kill(pid, sig):
        if sig == m.signal.SIGTERM:
            sigterm_sent.append(pid)
            return
        if sig == 0:                     # 存活探测
            probes["n"] += 1
            if probes["n"] < 3:          # 前两次"还在",之后"没了"
                return
            raise ProcessLookupError()
        raise AssertionError(f"不该发送信号 {sig}")   # 不该走到 SIGKILL

    monkeypatch.setattr(m, "_pid_is", lambda *a: True)
    monkeypatch.setattr(m.os, "kill", fake_kill)
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: type("P", (), {"returncode": 1})())
    pid_file = tmp_path / "backend.pid"
    pid_file.write_text("4242")
    svc = dataclasses.replace(m.BACKEND, pid_file=pid_file)

    m._stop(svc, "127.0.0.1", 8901)

    assert sigterm_sent == [4242], "应先发 SIGTERM"
    assert probes["n"] >= 3, "应轮询探测存活直到进程消失,而不是发完信号就返回"
    assert not pid_file.exists()
