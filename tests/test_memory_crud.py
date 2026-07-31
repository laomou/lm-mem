"""增删改查 + not_found 异常。"""

import json
import pytest

from conftest import r, get_id


def test_add_and_get(srv):
    mem_id = get_id(srv.add_memory(content="用户喜欢简洁的回答", user_id="u1"))
    got = r(srv.get_memory(mem_id))
    assert got["content"] == "用户喜欢简洁的回答"
    assert got["scope"]["user_id"] == "u1"


def test_dedup_blocks_similar(srv):
    srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1")
    dup = r(srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1"))
    # 查重命中是业务分支,不抛异常
    assert "duplicate_id" in dup
    assert dup["similarity"] >= 0.85
    # force 可强制新增
    forced = r(srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1", force=True))
    assert "id" in forced


def test_dedup_scoped_per_user(srv):
    srv.add_memory(content="喜欢深色主题", user_id="u1")
    other = r(srv.add_memory(content="喜欢深色主题", user_id="u2"))
    assert "id" in other


def test_scope_not_duplicated(srv):
    srv.add_memory(content="共享记忆", user_id="u1", agent_id="a1")
    from_u = r(srv.get_memories(user_id="u1"))
    from_a = r(srv.get_memories(agent_id="a1"))
    from conftest import contents as _contents
    assert any("共享记忆" in c for c in _contents(from_u["items"]))
    assert any("共享记忆" in c for c in _contents(from_a["items"]))
    assert srv._collection.count() == 1


def test_update_content_and_metadata(srv):
    mid = get_id(srv.add_memory(content="旧内容", user_id="u1",
                                metadata=json.dumps({"category": "a"})))
    r(srv.update_memory(mid, content="新内容", metadata=json.dumps({"importance": "low"})))
    got = r(srv.get_memory(mid))
    assert got["content"] == "新内容"
    assert got["metadata"]["importance"] == "low"
    assert got["metadata"]["category"] == "a"  # 原有 metadata 保留


def test_get_memory_not_found_raises(srv):
    with pytest.raises(ValueError, match="未找到"):
        srv.get_memory("nonexistent-id")


def test_delete_memory_not_found_raises(srv):
    with pytest.raises(ValueError, match="未找到"):
        srv.delete_memory("nonexistent-id")


def test_delete_all_requires_scope(srv):
    with pytest.raises(ValueError, match="作用域"):
        srv.delete_all_memories()


def test_empty_input_rejected(srv):
    with pytest.raises(ValueError, match="content|messages"):
        srv.add_memory()


def test_bad_metadata_rejected(srv):
    with pytest.raises(ValueError):
        srv.add_memory(content="x", metadata="not-json")
    with pytest.raises(ValueError):
        srv.add_memory(content="x", metadata="[1,2,3]")  # 非对象


# ── entities ─────────────────────────────────────────


def test_list_entities_groups_by_scope(srv):
    srv.add_memory(content="a", user_id="u1")
    srv.add_memory(content="b", user_id="u2", force=True)
    srv.add_memory(content="c", app_id="proj1", force=True)
    ents = r(srv.list_entities())["entities"]
    assert set(ents["user_id"]) == {"u1", "u2"}
    assert ents["app_id"] == ["proj1"]
    # 只取一类
    only = r(srv.list_entities("user"))["entities"]
    assert set(only["user_id"]) == {"u1", "u2"}
    assert "app_id" not in only


def test_list_entities_bad_type_raises(srv):
    with pytest.raises(ValueError):
        srv.list_entities("bogus")


def test_delete_entities_removes_and_validates(srv):
    srv.add_memory(content="a", user_id="u1")
    srv.add_memory(content="b", user_id="u1", force=True)
    out = r(srv.delete_entities("user", "u1"))
    assert out["deleted"] == 2
    # 非法 entity_type
    with pytest.raises(ValueError):
        srv.delete_entities("bogus", "u1")
    # 未找到实体
    with pytest.raises(ValueError, match="未找到"):
        srv.delete_entities("user", "ghost")


# ── messages 严格校验 ─────────────────────────────────


def test_messages_must_be_array(srv):
    with pytest.raises(ValueError, match="数组|JSON"):
        srv.add_memory(messages=json.dumps({"role": "user", "content": "x"}))  # 对象非数组


def test_messages_element_missing_field(srv):
    with pytest.raises(ValueError, match="role|content"):
        srv.add_memory(messages=json.dumps([{"role": "user"}]))  # 缺 content


def test_messages_element_not_dict(srv):
    with pytest.raises(ValueError, match="对象"):
        srv.add_memory(messages=json.dumps(["just a string"]))


# ── tags 清空(#5) ─────────────────────────────────────


def test_update_can_clear_tags(srv):
    """tags="" 应能清空标签。

    修复前:"" 被当作"不改",而 tags="   " 反而能清空(先判真再 strip)——
    想清空得传空格,行为不可发现。现在 None=不改 / ""=清空。
    """
    mid = get_id(srv.add_memory(content="有标签", user_id="u1", tags="a,b"))
    assert r(srv.get_memory(mid))["tags"] == "a,b"

    srv.update_memory(mid, tags="")                      # 显式清空
    assert r(srv.get_memory(mid))["tags"] == ""

    srv.update_memory(mid, tags="x,y")                   # 再整体替换
    assert r(srv.get_memory(mid))["tags"] == "x,y"

    srv.update_memory(mid, content="只改文本")            # 不传 tags → 不动
    got = r(srv.get_memory(mid))
    assert got["tags"] == "x,y" and got["content"] == "只改文本"
