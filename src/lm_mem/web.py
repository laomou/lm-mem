"""lm-mem Web 记忆。

基于标准库 http.server,零额外依赖。默认只绑 127.0.0.1,用于在浏览器里
查看/检索已保存的记忆,**并可按 id 删除单条**(需二次确认 + 同源校验)。
注意:本服务可写,不是只读面板——开放到非本机地址前请自行评估。

启动:
    lm-mem web start   或   LM_MEM_WEB_PORT=8080 python -m lm_mem.web
    # 默认 http://127.0.0.1:7531

路由:
    /                  列表(支持 ?user_id=&agent_id=&app_id=&run_id=&q=&p=)
    /search?q=...      语义检索
    /mem/<id>          单条详情
    /api/...           上述各页面的 JSON 版本
    POST /mem/<id>/delete        删除单条(浏览器表单,303 跳回 /)
    POST /api/mem/<id>/delete    删除单条(JSON 返回)
    DELETE /api/mem/<id>         删除单条(JSON 返回)
"""

from __future__ import annotations

import html
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse, urlencode

from lm_mem import __version__ as _VERSION
from lm_mem import memory_utils as _hlp
from lm_mem import web_assets
from lm_mem.client import MemoryClient

# 复用 MemoryClient(单例),不再自建 Chroma 读写路径。
_client = MemoryClient()


def _delete_fn(mem_id):
    """删除单条记忆(委托 MemoryClient,统一数据路径)。"""
    try:
        _client.delete(mem_id)
    except ValueError:
        return {"ok": False, "message": f"未找到 id={mem_id} 的记忆。"}
    return {"ok": True, "id": mem_id, "message": f"已删除 id={mem_id}"}

_HOST = "127.0.0.1"
_PORT = 7531



def _fmt_ts(ts):
    if not ts:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return str(ts)


def _fmt_ts_short(ts):
    if not ts:
        return "—"
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(ts))
    except Exception:
        return str(ts)


def _list_records(user_id="", agent_id="", app_id="", run_id=""):
    # limit 取大值:Web 列表页自行分页,这里要拿到该作用域下的全部记录。
    res = _client.list(limit=1_000_000, user_id=user_id, agent_id=agent_id,
                       app_id=app_id, run_id=run_id)
    records = res["items"]
    # 新创建的靠前
    records.sort(key=lambda r: r["created_at"] or 0, reverse=True)
    return records


def _search_records(query, user_id="", agent_id="", app_id="", run_id="", limit=20):
    res = _client.search(query, limit=limit, user_id=user_id, agent_id=agent_id,
                        app_id=app_id, run_id=run_id)
    return res["items"]


def _esc(s):
    return html.escape(str(s) if s is not None else "")


def _mem_href(mem_id, suffix=""):
    """记忆 id 拼进 URL 路径。

    id 不保证是 uuid(import_memories 可指定任意字符串),含 / & % 空格时
    必须百分号编码,否则链接指向的路径和真实 id 对不上——服务端拿到的是
    未解码的原始路径段,结果是这条记忆在 Web 台上既打不开也删不掉。
    """
    return f"/mem/{quote(str(mem_id), safe='')}{suffix}"


def _del_form(mem_id, inline=False, confirm_msg=None):
    """删除单条的 POST 表单。浏览器提交,服务端 303 跳回 /。"""
    msg = confirm_msg or f"确认删除记忆 {mem_id[:8]}…?此操作不可撤销。"
    btn_cls = "del-inline" if inline else "danger"
    btn_txt = "🗑 删除" if inline else "🗑 删除这条记忆"
    # onsubmit 是 **JS 上下文**:必须先用 json.dumps 生成合法 JS 字面量,再整体
    # HTML 转义。只做 html.escape 是不够的——浏览器先解实体再解析 JS,`&#x27;`
    # 会还原成 `'` 并提前闭合字符串(id 可由 import_memories 指定,例如
    # `');x()//` 就能注入代码 / 让 onsubmit 编译失败从而跳过确认框)。
    confirm_js = _esc(json.dumps(msg, ensure_ascii=False))
    return (
        f'<form method="post" action="{_esc(_mem_href(mem_id, "/delete"))}" '
        f'class="{"actions" if not inline else ""}" '
        f'onsubmit="return confirm({confirm_js})">'
        f'<button type="submit" class="{btn_cls}">{btn_txt}</button>'
        f"</form>"
    )


_PAGE_SIZE = 30
# 搜索展示上限:语义检索是 top-N,取一个足够大的值,使列表页分页有意义、
# 顶部计数不被 20 静默截断(旧行为搜索最多 20 条、永远只有 1 页)。
_SEARCH_LIMIT = 200


def _scope_inputs(scope_vals):
    """带 label 的作用域输入,横向排列。"""
    return "".join(
        f'<div class="field"><label>{k}</label>'
        f'<input type="text" name="{k}" value="{_esc(scope_vals.get(k, ""))}" placeholder="—"></div>'
        for k in _hlp.SCOPE_KEYS
    )


def _pager(base_url, page, total_pages):
    if total_pages <= 1:
        return ""
    parts = []
    prev_cls = "" if page > 1 else ' style="visibility:hidden"'
    parts.append(f'<a{prev_cls} href="{base_url}&p={page-1}">‹ 上一页</a>')
    # 简洁页码:首页 + 当前附近 + 末页
    shown = {1, total_pages, page, page - 1, page + 1}
    last = 0
    for p in sorted(shown):
        if p < 1 or p > total_pages:
            continue
        if p - last > 1:
            parts.append('<span class="gap">…</span>')
        if p == page:
            parts.append(f'<span class="cur">{p}</span>')
        else:
            parts.append(f'<a href="{base_url}&p={p}">{p}</a>')
        last = p
    next_cls = "" if page < total_pages else ' style="visibility:hidden"'
    parts.append(f'<a{next_cls} href="{base_url}&p={page+1}">下一页 ›</a>')
    return f'<div class="pager">{"".join(parts)}</div>'


def _render_list(records, scope_vals, q="", page=1, notice=None):
    total = len(records)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * _PAGE_SIZE
    page_records = records[start:start + _PAGE_SIZE]

    q_field = (
        '<div class="field" style="flex:2;min-width:240px">'
        f'<label>关键词 / 语义检索</label>'
        f'<input type="text" class="grow" name="q" value="{_esc(q)}" placeholder="留空则按作用域列出"></div>'
    )
    rows = []
    for r in page_records:
        # 时间
        time_html = f'<td class="time">{_esc(_fmt_ts_short(r["created_at"]))}</td>'
        # 作用域(scope)
        ent = "".join(
            f'<span class="scope">{_esc(k)}={_esc(v)}</span>'
            for k, v in r["scope"].items()
        ) or '<span class="muted">—</span>'
        ent_html = f'<td class="entities">{ent}</td>'
        # 内容(点击进抽屉)
        content_html = (
            f'<td class="content"><a class="mem-link" data-mid="{_esc(r["id"])}" '
            f'href="{_esc(_mem_href(r["id"]))}">'
            f'{_esc(r["content"])}</a></td>'
        )
        # 分类(tags + metadata.category)
        cat = (r.get("metadata") or {}).get("category")
        if cat:
            cat_inner = f'<span class="tag cat">{_esc(cat)}</span>'
        else:
            cat_inner = '<span class="muted">—</span>'
        cat_html = f'<td class="categories">{cat_inner}</td>'
        rows.append(f'<tr data-mid="{_esc(r["id"])}">{time_html}{ent_html}{content_html}{cat_html}</tr>')

    if not rows:
        body = '<div class="empty"><div class="big">📭</div>没有匹配的记忆。</div>'
    else:
        body = (
            '<div class="table-wrap"><table class="mem-table">'
            '<thead><tr><th>时间</th><th>作用域</th><th>内容</th><th>分类</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
        )

    # query string 用 URL 编码(不是 HTML 转义),避免 scope 值/关键词含
    # & 空格 # = 时链接参数错位。href 属性再由模板整体转义。
    params = [(k, scope_vals.get(k, "") or "") for k in _hlp.SCOPE_KEYS]
    params.append(("q", q))
    base = "?" + urlencode(params)
    pager = _pager(base, page, total_pages)

    notice_html = ""
    if notice:
        notice_html = (
            f'<div class="confirm-bar"><span class="msg">{_esc(notice)}</span>'
            f'<a href="/" style="font-size:13px;color:var(--muted);text-decoration:none">×</a></div>'
        )

    has_filter = bool(q) or any(v for v in scope_vals.values())
    filter_dot = '<span class="filter-active" title="当前有筛选条件"></span>' if has_filter else ""
    filter_form_cls = "filters" + ("" if has_filter else " collapsed")

    return _page("记忆", f"""
        {notice_html}
        <div class="toolbar">
          <span class="count">共 {total} 条{f" · 第 {page}/{total_pages} 页" if total_pages>1 else ""}</span>
          <div class="tools-right">
            <button class="ghost icon" id="filter-toggle">筛选 <span id="filter-arrow">▾</span>{filter_dot}</button>
            <button class="ghost icon" onclick="location.reload()" title="重新加载">🔄 刷新</button>
            {pager if total_pages > 1 else ""}
          </div>
        </div>
        <form class="{filter_form_cls}" id="filters" method="get" action="/">
          {_scope_inputs(scope_vals)}
          {q_field}
          <button type="submit">筛选</button>
        </form>
        {body}
        {f'<div class="toolbar" style="justify-content:flex-end">{pager}</div>' if total_pages>1 else ""}
        <script>
        (function(){{
          var f=document.getElementById('filters'),b=document.getElementById('filter-toggle'),
              a=document.getElementById('filter-arrow');
          if(!f||!b||!a)return;
          b.addEventListener('click',function(){{
            var c=f.classList.toggle('collapsed');
            a.textContent=c?'▾':'▴';
          }});
        }})();
        </script>
    """)


def _render_detail(rec):
    if not rec:
        return _page("未找到", '<div class="empty"><div class="big">🔍</div>没有这条记忆。</div>')
    pre = html.escape(json.dumps(rec, ensure_ascii=False, indent=2))
    scope = " ".join(f"{k}={v}" for k, v in rec["scope"].items()) or "—"
    tags = "".join(
        f'<span class="tag">{_esc(t.strip())}</span>'
        for t in str(rec["tags"]).split(",") if t.strip()
    ) or '<span class="muted">—</span>'
    return _page(f"记忆 {rec['id'][:8]}", f"""
        <div class="card">
          <div class="top"><span class="id">{_esc(rec["id"])}</span></div>
          <div class="content">{_esc(rec["content"])}</div>
          <div class="meta">
            <span class="scope">{_esc(scope)}</span>
          </div>
        </div>
        <h2>属性</h2>
        <div class="card">
          <dl class="kv">
            <dt>标签</dt><dd>{tags}</dd>
            <dt>创建时间</dt><dd>{_esc(_fmt_ts(rec["created_at"]))}</dd>
            <dt>更新时间</dt><dd>{_esc(_fmt_ts(rec["updated_at"]))}</dd>
            <dt>过期时间</dt><dd>{_esc(_fmt_ts(rec["expires_at"]))}</dd>
          </dl>
        </div>
        {_del_form(rec["id"])}
        <h2>原始数据</h2>
        <pre>{pre}</pre>
    """)


def _render_search(records, q):
    if not records:
        body = '<div class="empty"><div class="big">🔍</div>没有匹配的记忆。</div>'
    else:
        rows = "".join(
            f'<tr><td><span class="sim" style="display:inline-block">{r["similarity"]:.2f}</span></td>'
            f'<td><a href="{_esc(_mem_href(r["id"]))}">{_esc(r["content"][:80])}</a></td>'
            f'<td><span class="scope">{_esc(" ".join(f"{k}={v}" for k,v in r["scope"].items()) or "—")}</span></td></tr>'
            for r in records
        )
        body = f'<table><thead><tr><th>相似度</th><th>内容</th><th>作用域</th></tr></thead><tbody>{rows}</tbody></table>'
    return _page(f"搜索: {q}", f"""
        <form class="filters" method="get" action="/search">
          <div class="field" style="flex:1;min-width:260px">
            <label>语义检索</label>
            <input type="text" class="grow" name="q" value="{_esc(q)}" placeholder="输入关键词">
          </div>
          <button type="submit">搜索</button>
        </form>
        {body}
    """)




def _page(title, body):
    return (
        "<!doctype html><html lang='zh-CN'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(title)} · lm-mem</title>"
        f"<style>{web_assets.PAGE_CSS}</style></head>"
        f"<body><header class='topbar'><div class='topbar-inner'>"
        f"<h1>🧠 lm-mem<span class='ver'>v{_VERSION}</span></h1>"
        f"</div></header><div class='wrap'>{body}</div>"
        "<div class='overlay' id='ov'></div>"
        "<aside class='drawer' id='dr' aria-hidden='true'>"
        "<header><span class='title' id='dr-title'>—</span>"
        "<button class='close' id='dr-close' aria-label='关闭'>×</button></header>"
        "<div class='body' id='dr-body'></div>"
        "<footer id='dr-foot' hidden></footer>"
        "</aside>"
        "<script>"
        + web_assets.DRAWER_JS
        + "</script>"
        "</body></html>"
    )

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默默认日志
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _scope_from_qs(self, qs):
        return {k: (qs.get(k, [""])[0]) for k in _hlp.SCOPE_KEYS}

    def _local_origin_ok(self):
        """同源校验:仅允许本机 origin 的写请求,挡掉跨站 CSRF。

        解析 Origin/Referer 的 host:port 与本机 Host **精确相等**才放行,
        避免 http://<host>.evil.com 这类子串绕过。两者都空时(如 curl)
        放行——工具本就是本机脚本可用。
        """
        host = self.headers.get("Host", "")
        for header in ("Origin", "Referer"):
            val = (self.headers.get(header) or "").strip()
            if not val:
                continue
            netloc = urlparse(val).netloc
            if netloc != host:
                return False
        return True

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/mem/") and path.endswith("/delete"):
            mid = unquote(path[len("/api/mem/"):-len("/delete")])
        elif path.startswith("/api/mem/"):
            mid = unquote(path[len("/api/mem/"):])
        else:
            return self._send(404, json.dumps({"error": "not found"}),
                              "application/json; charset=utf-8")
        if not self._local_origin_ok():
            return self._send(403, json.dumps({"error": "forbidden origin"}),
                              "application/json; charset=utf-8")
        result = _delete_fn(mid)
        code = 200 if result["ok"] else 404
        return self._send(code, json.dumps(result, ensure_ascii=False),
                          "application/json; charset=utf-8")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        # 单条删除:/mem/<id>/delete  或  /api/mem/<id>/delete
        mid = None
        api = False
        if path.startswith("/mem/") and path.endswith("/delete"):
            mid = unquote(path[len("/mem/"):-len("/delete")])
        elif path.startswith("/api/mem/") and path.endswith("/delete"):
            mid = unquote(path[len("/api/mem/"):-len("/delete")])
            api = True
        if mid is None:
            return self._send(404, json.dumps({"error": "not found"}),
                              "application/json; charset=utf-8")
        if not self._local_origin_ok():
            return self._send(403, json.dumps({"error": "forbidden origin"}),
                              "application/json; charset=utf-8")
        result = _delete_fn(mid)
        ok = result["ok"]
        if api:
            return self._send(200 if ok else 404,
                              json.dumps(result, ensure_ascii=False),
                              "application/json; charset=utf-8")
        # 浏览器表单:跳回列表,带结果提示。查询串用 urlencode(不是 HTML 转义),
        # 否则 id 里的 & = # 会让参数错位。
        return self._redirect(
            "/?" + urlencode({"deleted": 1 if ok else 0, "id": mid[:8]})
        )

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/version" or path == "/api/version":
            return self._send(200, json.dumps({"version": _VERSION}, ensure_ascii=False),
                              "application/json; charset=utf-8")

        try:
            if path == "/api/list" or path == "/":
                sv = self._scope_from_qs(qs)
                q = qs.get("q", [""])[0].strip()
                records = (_search_records(q, limit=_SEARCH_LIMIT, **sv) if q
                           else _list_records(**sv))
                if path == "/api/list":
                    return self._send(200, json.dumps({"ok": True, "count": len(records),
                                      "items": records, "message": f"返回 {len(records)} 条"},
                                      ensure_ascii=False),
                                      "application/json; charset=utf-8")
                page = int(qs.get("p", ["1"])[0] or "1")
                notice = None
                if qs.get("deleted", [""])[0] == "1":
                    short = qs.get("id", [""])[0]
                    notice = f"✓ 已删除记忆 {short}…" if short else "✓ 已删除"
                elif qs.get("deleted", [""])[0] == "0":
                    notice = "✗ 删除失败:未找到该记忆"
                return self._send(200, _render_list(records, sv, q, page=page, notice=notice))

            if path == "/api/search":
                q = qs.get("q", [""])[0].strip()
                sv = self._scope_from_qs(qs)
                items = _search_records(q, limit=_SEARCH_LIMIT, **sv)
                return self._send(
                    200, json.dumps({"ok": True, "count": len(items),
                                     "items": items, "message": f"搜索到 {len(items)} 条"},
                                    ensure_ascii=False),
                    "application/json; charset=utf-8")

            if path == "/search":
                q = qs.get("q", [""])[0].strip()
                sv = self._scope_from_qs(qs)
                return self._send(200, _render_search(_search_records(q, limit=_SEARCH_LIMIT, **sv), q))

            if path.startswith("/api/mem/"):
                mid = unquote(path[len("/api/mem/"):])
                return self._send(200, json.dumps(_get_one(mid), ensure_ascii=False),
                                  "application/json; charset=utf-8")

            if path.startswith("/mem/"):
                mid = unquote(path[len("/mem/"):])
                return self._send(200, _render_detail(_get_one(mid)))

            return self._send(404, _page("404", '<div class="empty"><div class="big">🚫</div>没有这个页面。</div>'))
        except Exception as exc:  # noqa: BLE001
            return self._send(500, _page("出错", f'<div class="error-box"><pre>{_esc(exc)}</pre></div>'))


def _get_one(mem_id):
    """取单条记忆;不存在或已过期返回 None(供详情页/JSON 用)。"""
    try:
        rec = _client.get(mem_id)
    except ValueError:
        return None
    if _hlp.is_expired({"expires_at": rec.get("expires_at")}):
        return None
    return rec


def main() -> None:
    host = os.environ.get("LM_MEM_WEB_HOST", _HOST).strip() or _HOST
    port = int(os.environ.get("LM_MEM_WEB_PORT", str(_PORT)))
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"lm-mem: http://{host}:{port}  (可查看/检索/删除, Ctrl+C 退出)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        httpd.server_close()


def start_web_thread(host=None, port=None):
    """在后台 daemon 线程启动 Web 台,端口被占则静默跳过(端口抢占单例)。"""
    import threading

    host = (host or os.environ.get("LM_MEM_WEB_HOST", _HOST)).strip() or _HOST
    port = port or int(os.environ.get("LM_MEM_WEB_PORT", str(_PORT)))
    try:
        httpd = ThreadingHTTPServer((host, port), _Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        import sys as _sys
        _sys.stderr.write(f"[lm-mem] Web 记忆: http://{host}:{port} (可查看/检索/删除)\n")
        _sys.stderr.flush()
    except OSError:
        pass  # 端口被占,说明已有实例起了 Web 台,静默跳过


if __name__ == "__main__":
    main()
