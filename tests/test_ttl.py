"""TTL、过期、清理相关。"""

from conftest import r, get_id, contents


def test_update_ttl_renew_and_clear(srv):
    mid = get_id(srv.add_memory(content="临时", user_id="u1", ttl_seconds=3600))
    # 清除过期 -> 变永久
    srv.update_memory(mid, ttl_seconds=-1)
    meta = srv._collection.get(ids=[mid], include=["metadatas"])["metadatas"][0]
    assert not meta.get("expires_at")
    assert not srv._is_expired(meta)
    # 重新续期
    srv.update_memory(mid, ttl_seconds=7200)
    meta = srv._collection.get(ids=[mid], include=["metadatas"])["metadatas"][0]
    assert meta["expires_at"] > 0
    # ttl_seconds=0 不动过期,但仍能改文本
    srv.update_memory(mid, content="改了文本")
    meta = srv._collection.get(ids=[mid], include=["metadatas"])["metadatas"][0]
    assert meta["expires_at"] > 0


def test_search_overfetch_past_expired(srv):
    # 即使前面挤了很多过期项,有效项仍能被返回
    for i in range(30):
        mid = get_id(srv.add_memory(content=f"过期便签 {i}", user_id="u1",
                                    force=True, ttl_seconds=3600))
        g = srv._collection.get(ids=[mid], include=["metadatas"])
        m = g["metadatas"][0]
        m["expires_at"] = 1.0
        srv._collection.update(ids=[mid], metadatas=[m])
    srv.add_memory(content="这是唯一有效的便签", user_id="u1", force=True)
    res = r(srv.search_memories(query="便签", user_id="u1", limit=5))
    cs = contents(res["items"])
    assert any("这是唯一有效的便签" in c for c in cs)
    assert not any("过期便签" in c for c in cs)


def test_ttl_and_purge(srv):
    mid = get_id(srv.add_memory(content="临时便签", user_id="u1", ttl_seconds=3600))
    got = srv._collection.get(ids=[mid], include=["metadatas"])
    assert got["metadatas"][0]["expires_at"] > 0
    # 模拟过期
    meta = got["metadatas"][0]
    meta["expires_at"] = 1.0
    srv._collection.update(ids=[mid], metadatas=[meta])
    srv.add_memory(content="长期偏好", user_id="u1", force=True)

    res = r(srv.search_memories(query="便签", user_id="u1"))
    assert not any("临时便签" in c for c in contents(res["items"]))
    listed = r(srv.get_memories(user_id="u1"))
    assert not any("临时便签" in c for c in contents(listed["items"]))
    purged = r(srv.purge_expired())
    assert purged["deleted"] == 1


def _expire(srv, mem_id):
    meta = srv._collection.get(ids=[mem_id], include=["metadatas"])["metadatas"][0]
    meta["expires_at"] = 1.0
    srv._collection.update(ids=[mem_id], metadatas=[meta])


def test_list_pagination_counts_only_live_records(srv):
    """#3:过期项不得占掉 limit/offset 配额。

    否则前排全是过期项时第一页会整页为空,而调用方(尤其 LLM)会把
    空的第一页读成"这个用户没有记忆",根本不会去翻第二页。
    """
    ids = [get_id(srv.add_memory(content=f"便签 {i}", user_id="u1", force=True))
           for i in range(5)]
    for mid in ids[:3]:
        _expire(srv, mid)

    page1 = contents(r(srv.get_memories(user_id="u1", limit=3, offset=0))["items"])
    assert len(page1) == 2, f"第一页应直接给出 2 条有效记忆,实际 {page1}"
    assert not any("便签 0" in c or "便签 1" in c or "便签 2" in c for c in page1)

    # offset 同样按有效记忆计数
    page2 = contents(r(srv.get_memories(user_id="u1", limit=1, offset=1))["items"])
    assert len(page2) == 1
    assert page2[0] == page1[1]
    # 越过末尾就该空
    assert r(srv.get_memories(user_id="u1", limit=3, offset=2))["items"] == []


def test_list_pagination_walks_all_live_records(srv):
    """逐页翻完能拿到全部有效记忆,不重不漏。"""
    for i in range(12):
        mid = get_id(srv.add_memory(content=f"条目 {i:02d}", user_id="u1", force=True))
        if i % 2 == 0:  # 一半过期,交错分布
            _expire(srv, mid)

    seen, offset = [], 0
    while True:
        page = r(srv.get_memories(user_id="u1", limit=2, offset=offset))["items"]
        if not page:
            break
        seen += contents(page)
        offset += len(page)
    assert len(seen) == 6, seen
    assert len(set(seen)) == 6, "翻页不得重复"
    assert all("条目" in c for c in seen)

