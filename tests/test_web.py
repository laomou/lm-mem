"""web.py 路由测试:起真实 HTTP server,覆盖删除/origin 校验/分页/详情。

用嵌入式 chroma(临时 DB),不依赖外部后端。
"""
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest


@pytest.fixture()
def web_srv(free_port):
    """起一个真实 web server,返回 (base_url, web模块)。每测试独立 DB。"""
    os.environ["LM_MEM_DB_PATH"] = tempfile.mkdtemp(prefix="lm-mem-web-test-")
    os.environ.pop("LM_MEM_BACKEND_URL", None)
    for m in ("lm_mem.backend", "lm_mem.memory_utils", "lm_mem.client",
              "lm_mem.web", "lm_mem"):
        sys.modules.pop(m, None)
    import lm_mem.web as web
    web = importlib.reload(web)

    # 预置数据(直接用 web 复用的 client)
    web._client.add(content="用户偏好 pytest", user_id="u1",
                    metadata=json.dumps({"category": "preference"}))
    web._client.add(content="项目用 PostgreSQL", app_id="acme", force=True)

    httpd = ThreadingHTTPServer(("127.0.0.1", free_port), web._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{free_port}"
    yield base, web
    httpd.shutdown()


def _req(method, url, headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _first_id(web):
    return web._list_records()[0]["id"]


def test_version(web_srv):
    base, _ = web_srv
    code, body = _req("GET", f"{base}/version")
    assert code == 200 and json.loads(body)["version"]


def test_list_renders(web_srv):
    base, _ = web_srv
    code, body = _req("GET", f"{base}/")
    assert code == 200
    assert "pytest" in body and "PostgreSQL" in body


def test_api_list_json(web_srv):
    base, _ = web_srv
    code, body = _req("GET", f"{base}/api/list?user_id=u1")
    data = json.loads(body)
    assert code == 200 and data["ok"]
    assert all(it["scope"].get("user_id") == "u1" for it in data["items"])


def test_detail_and_missing(web_srv):
    base, web = web_srv
    mid = _first_id(web)
    code, body = _req("GET", f"{base}/mem/{mid}")
    assert code == 200 and mid in body
    # 不存在的详情页仍 200,渲染"没有这条记忆"
    code, body = _req("GET", f"{base}/mem/nope")
    assert code == 200 and "没有这条记忆" in body


def test_delete_success_and_404(web_srv):
    base, web = web_srv
    mid = _first_id(web)
    # 带本机 Origin,删除成功
    code, body = _req("DELETE", f"{base}/api/mem/{mid}",
                      headers={"Origin": base, "Host": base.split("//")[1]})
    assert code == 200 and json.loads(body)["ok"]
    # 再删已不存在 → 404
    code, body = _req("DELETE", f"{base}/api/mem/{mid}",
                      headers={"Origin": base, "Host": base.split("//")[1]})
    assert code == 404 and not json.loads(body)["ok"]


def test_delete_cross_origin_forbidden(web_srv):
    base, web = web_srv
    mid = _first_id(web)
    code, body = _req("DELETE", f"{base}/api/mem/{mid}",
                      headers={"Origin": "http://evil.example.com",
                               "Host": base.split("//")[1]})
    assert code == 403
    # 记忆未被删除
    assert web._get_one(mid) is not None


def test_search_route(web_srv):
    base, _ = web_srv
    code, body = _req("GET", f"{base}/api/search?q=%E6%B5%8B%E8%AF%95")  # 测试
    data = json.loads(body)
    assert code == 200 and data["ok"]


def test_cross_origin_substring_bypass_blocked(web_srv):
    # #7:Host 作为子串出现的伪域名不得绕过(精确匹配)
    base, web = web_srv
    mid = _first_id(web)
    host = base.split("//")[1]
    code, _ = _req("DELETE", f"{base}/api/mem/{mid}",
                   headers={"Origin": f"http://{host}.evil.com", "Host": host})
    assert code == 403
    assert web._get_one(mid) is not None  # 未被删


def test_pager_url_encodes_special_chars(web_srv):
    # #6:含 & 空格的作用域值应被 URL 编码进翻页链接,不产生裸 & 断链
    base, web = web_srv
    # 造 >30 条同作用域记忆以触发分页
    weird = "a&b c"
    for i in range(35):
        web._client.add(content=f"记忆{i}", app_id=weird, force=True)
    code, body = _req("GET", f"{base}/?app_id=a%26b+c")
    assert code == 200
    # 分页链接里应出现编码后的值,而非裸 "a&b c"
    assert "a%26b" in body and "第 1/2 页" in body
