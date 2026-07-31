"""web.py 路由测试:起真实 HTTP server,覆盖删除/origin 校验/分页/详情。

用嵌入式 chroma(临时 DB),不依赖外部后端。
"""
import html
import http.client
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

import pytest


@pytest.fixture()
def web_srv(free_port):
    """起一个真实 web server,返回 (base_url, web模块)。每测试独立 DB。"""
    os.environ["LM_MEM_DB_PATH"] = tempfile.mkdtemp(prefix="lm-mem-web-test-")
    os.environ["LM_MEM_EMBEDDED"] = "1"
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


# ── 以下为 review 回归测试 ────────────────────────────


def _raw(base, method, path, headers=None):
    """不跟随重定向的裸 HTTP 请求,用于检查 Location 头本身。"""
    u = urlparse(base)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    conn.request(method, path, headers=headers or {})
    resp = conn.getresponse()
    resp.read()
    out = (resp.status, dict(resp.getheaders()))
    conn.close()
    return out


class _FormParser(HTMLParser):
    """抓出第一个 <form> 的属性。HTMLParser 会按浏览器规则解 HTML 实体,
    所以拿到的 onsubmit 就是浏览器交给 JS 引擎的那段源码。"""

    def __init__(self):
        super().__init__()
        self.form = {}

    def handle_starttag(self, tag, attrs):
        if tag == "form" and not self.form:
            self.form = dict(attrs)


@pytest.mark.parametrize("hostile", [
    "');x();\"" + "z" * 20,      # 想提前闭合单引号并调用函数
    '");y();\'' + "z" * 20,      # 双引号版本
    "\\');z();" + "w" * 20,      # 反斜杠开头
    '"+alert(1)+"' + "v" * 20,   # 字符串拼接
])
def test_del_form_hostile_id_stays_single_js_literal(web_srv, hostile):
    """#6:onsubmit 是 JS 上下文,任何 id 都不得逃出 confirm() 的字符串字面量。

    只做 html.escape 是不够的:浏览器先解 HTML 实体再解析 JS,`&#x27;` 会还原
    成 `'`。mem_id 可由 import_memories 指定,所以这是可达路径。
    """
    _, web = web_srv
    parser = _FormParser()
    parser.feed(web._del_form(hostile))
    onsubmit = parser.form["onsubmit"]  # HTMLParser 已按浏览器规则解过实体

    assert onsubmit.startswith("return confirm(") and onsubmit.endswith(")")
    arg = onsubmit[len("return confirm("):-1]
    # 能被 json 整段解析成 str <=> 它是单个完整的 JS 字符串字面量
    msg = json.loads(arg)
    assert isinstance(msg, str)
    assert msg == f"确认删除记忆 {hostile[:8]}…?此操作不可撤销。"
    # action 里的 id 仍然完整可用(百分号编码形式)
    assert parser.form["action"] == f"/mem/{quote(hostile, safe='')}/delete"
    assert unquote(parser.form["action"][len("/mem/"):-len("/delete")]) == hostile


def test_delete_redirect_url_encodes_id(web_srv):
    """#7:Location 是 URL 上下文,id 里的 & 必须编码,不能用 HTML 转义。"""
    base, web = web_srv
    web._client.import_data(json.dumps([{"id": "a&b", "content": "带 & 的 id"}]))
    host = base.split("//")[1]
    status, headers = _raw(base, "POST", "/mem/a&b/delete",
                           {"Origin": base, "Host": host})
    assert status == 303
    loc = headers["Location"]
    assert "id=a%26b" in loc, loc
    assert "&amp;" not in loc, "HTML 实体不该出现在 URL 里"
    # 编码正确的话 id 参数解析回来仍是原值
    assert parse_qs(urlparse(loc).query)["id"] == ["a&b"]
    assert parse_qs(urlparse(loc).query)["deleted"] == ["1"]


def test_web_version_matches_package(web_srv):
    """#10:web 不再自己维护版本号,避免 UI 显示 0.3.0 而包是 0.6.x。"""
    base, _ = web_srv
    import lm_mem
    _, body = _req("GET", f"{base}/version")
    assert json.loads(body)["version"] == lm_mem.__version__
    _, page = _req("GET", f"{base}/")
    assert f"v{lm_mem.__version__}" in page


@pytest.mark.parametrize("mem_id", [
    "a&b",              # & 会被当成查询串分隔符
    "with space",
    "pct%2Fslash",      # 本身含 % 的 id
    "quote'and\"both",
    "中文-id",
])
def test_special_char_ids_are_viewable_and_deletable(web_srv, mem_id):
    """#14:id 不保证是 uuid(import 可指定),Web 台必须能打开并删除它们。

    修复前:生成的链接没做百分号编码、服务端也没解码,这类记忆在列表里
    看得见,点进去 404,删也删不掉。
    """
    base, web = web_srv
    content = f"内容 {mem_id}"
    web._client.import_data(json.dumps([{"id": mem_id, "content": content}]))
    quoted = quote(mem_id, safe="")

    # 列表页给出的链接必须是编码后的(quote 之后已无 HTML 特殊字符)
    _, page = _req("GET", f"{base}/")
    assert f'href="/mem/{quoted}"' in page

    # 详情页打得开(页面里的内容是 HTML 转义过的)
    code, body = _req("GET", f"{base}/mem/{quoted}")
    assert code == 200, f"详情页打不开 {mem_id!r}"
    assert html.escape(content) in body, f"详情页没渲染出内容 {mem_id!r}"

    # JSON 详情也对得上
    _, api = _req("GET", f"{base}/api/mem/{quoted}")
    assert json.loads(api)["id"] == mem_id

    # 删得掉
    host = base.split("//")[1]
    code, body = _req("DELETE", f"{base}/api/mem/{quoted}",
                      headers={"Origin": base, "Host": host})
    assert code == 200 and json.loads(body)["ok"], f"删不掉 {mem_id!r}"
    assert web._get_one(mem_id) is None


