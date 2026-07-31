"""真实 HTTP 后端的集成测试(默认跳过)。

其余测试全部跑在 `LM_MEM_EMBEDDED=1` 的进程内嵌模式下,而真实用户走的是
"MCP 进程当纯客户端 + 连独立 chroma 后端"这条 HTTP 路径 —— 那条路径此前
从来没有任何自动化覆盖。这个文件补上它。

默认跳过:起一个真 chroma server 要十几秒,不该拖慢日常 CI。

    LM_MEM_IT=1 uv run pytest tests/test_integration_http.py -v
"""
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LM_MEM_IT", "").strip() in ("", "0", "false"),
    reason="集成测试需显式开启:LM_MEM_IT=1(会启动真实 chroma 后端)",
)

_BOOT_TIMEOUT = 90  # chroma 冷启动可能要几十秒


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(port, timeout=_BOOT_TIMEOUT):
    url = f"http://127.0.0.1:{port}/api/v2/heartbeat"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:  # noqa: BLE001 —— 任何连接错误都只意味着「还没起好」
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def backend():
    """起一个真实 chroma 后端,返回它的 URL。"""
    if shutil.which("chroma") is None:
        pytest.skip("PATH 里没有 chroma 命令")
    port = _free_port()
    data = tempfile.mkdtemp(prefix="lm-mem-it-")
    proc = subprocess.Popen(
        ["chroma", "run", "--path", data, "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        if not _wait_ready(port):
            proc.terminate()
            pytest.fail(f"chroma 后端 {_BOOT_TIMEOUT}s 内未就绪")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(data, ignore_errors=True)


@pytest.fixture()
def client(backend):
    """显式指向该后端的 MemoryClient(走 HttpClient,不是嵌入式)。"""
    from lm_mem import MemoryClient
    return MemoryClient(url=backend)


def test_http_client_full_roundtrip(client):
    """HTTP 路径下 增 / 查 / 检索 / 改 / 删 全链路。"""
    import json

    added = client.add("用户偏好 pytest 而非 unittest", user_id="it-user",
                       metadata=json.dumps({"category": "preference"}))
    mem_id = added["id"]

    got = client.get(mem_id)
    assert got["content"] == "用户偏好 pytest 而非 unittest"
    assert got["scope"]["user_id"] == "it-user"
    assert got["metadata"]["category"] == "preference"

    # 语义检索(embedding 在客户端算,这里验证它在 HTTP 模式下同样工作)
    hits = client.search("测试框架偏好", user_id="it-user")["items"]
    assert any("pytest" in h["content"] for h in hits)

    listed = client.list(user_id="it-user")["items"]
    assert any(i["id"] == mem_id for i in listed)

    ctx = client.get_user_context(user_id="it-user")["items"]
    assert any("pytest" in i["content"] for i in ctx)

    client.update(mem_id, content="用户偏好 pytest + hypothesis")
    assert "hypothesis" in client.get(mem_id)["content"]

    client.delete(mem_id)
    with pytest.raises(ValueError, match="未找到"):
        client.get(mem_id)


def test_http_dedup_and_force(client):
    """查重是在后端数据上做的,HTTP 模式下同样生效。"""
    client.add("我用 neovim 写代码", user_id="it-dedup", force=True)
    dup = client.add("我用 neovim 写代码", user_id="it-dedup")
    assert "duplicate_id" in dup
    forced = client.add("我用 neovim 写代码", user_id="it-dedup", force=True)
    assert "id" in forced
    client.delete_all(user_id="it-dedup")


def test_http_purge_expired_actually_deletes(client):
    """过期记忆能被 purge 真正删掉(不只是检索时被过滤)。"""
    mid = client.add("一秒后过期", user_id="it-ttl", ttl_seconds=1, force=True)["id"]
    time.sleep(1.2)
    # 过期后检索/列表都看不到,但行还在
    assert not any(i["id"] == mid for i in client.list(user_id="it-ttl")["items"])
    assert client.purge_expired()["deleted"] >= 1
    with pytest.raises(ValueError, match="未找到"):
        client.get(mid)


def test_backend_url_arg_beats_env(backend, monkeypatch):
    """MemoryClient(url=...) 应优先于 LM_MEM_BACKEND_URL 环境变量。"""
    from lm_mem import MemoryClient
    monkeypatch.setenv("LM_MEM_BACKEND_URL", "http://127.0.0.1:1")  # 必然连不上
    c = MemoryClient(url=backend)          # 显式 url 应当胜出
    assert c.add("显式 url 优先", user_id="it-url", force=True)["id"]
    c.delete_all(user_id="it-url")
