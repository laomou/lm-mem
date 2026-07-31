"""lm-mem 纯函数层:作用域、元数据、格式化等工具函数。

零运行时依赖(chromadb / mcp),只依赖 Python 标准库。
"""
from __future__ import annotations

import json
import time

# 作用域字段:归属实体的维度。
SCOPE_KEYS = ("user_id", "agent_id", "app_id", "run_id")
# 用户自定义 metadata 的键前缀,避免与保留键冲突。
MD_PREFIX = "m:"
# 添加去重:语义相似度 >= 该阈值视为疑似重复。
DEDUP_THRESHOLD = 0.85
# 检索时的过取倍数:过期项要在 Python 侧剔除(Chroma 的 where 无法表达
# "expires_at 缺失或大于 now"),所以一次多取 limit*OVERFETCH 条候选,
# 让前排的过期项不至于把有效结果挤出 limit。取满 limit 即停,不再补取。
OVERFETCH = 3


def scope_meta(user_id, agent_id, app_id, run_id):
    """把作用域参数拼成 metadata(空值不写入,ChromaDB 不接受 None)。"""
    meta = {}
    for key, val in zip(SCOPE_KEYS, (user_id, agent_id, app_id, run_id)):
        if val:
            meta[key] = val
    return meta


def clauses(user_id, agent_id, app_id, run_id):
    """作用域参数 -> ChromaDB where 子句列表(每个是单键 dict)。"""
    return [
        {key: val}
        for key, val in zip(SCOPE_KEYS, (user_id, agent_id, app_id, run_id))
        if val
    ]


def combine(clauses):
    """把若干单键 where 子句合并成 ChromaDB where(0/1/多 分别处理)。"""
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def scope_where(user_id, agent_id, app_id, run_id):
    return combine(clauses(user_id, agent_id, app_id, run_id))


def coerce_scalar(val):
    """ChromaDB metadata 只接受标量;非标量转 JSON 字符串。"""
    if isinstance(val, (str, int, float, bool)):
        return val
    return json.dumps(val, ensure_ascii=False)


def parse_metadata(metadata):
    """解析用户传入的 metadata(JSON 对象字符串)-> 扁平 dict(加前缀)。"""
    if not metadata:
        return {}
    if isinstance(metadata, dict):
        obj = metadata
    else:
        try:
            obj = json.loads(metadata)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"metadata 不是合法的 JSON 对象:{exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("metadata 必须是 JSON 对象(键值对)。")
    return {f"{MD_PREFIX}{k}": coerce_scalar(v) for k, v in obj.items()}


def metadata_filter_clauses(metadata_filter):
    """解析 metadata_filter(JSON 对象字符串)-> where 子句列表(加前缀)。"""
    if not metadata_filter:
        return []
    if isinstance(metadata_filter, dict):
        obj = metadata_filter
    else:
        try:
            obj = json.loads(metadata_filter)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"metadata_filter 不是合法 JSON:{exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("metadata_filter 必须是 JSON 对象。")
    return [{f"{MD_PREFIX}{k}": coerce_scalar(v)} for k, v in obj.items()]


def messages_to_text(messages):
    """把对话历史(JSON 数组)拼成可读文本。"""
    if isinstance(messages, str):
        try:
            arr = json.loads(messages)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"messages 不是合法 JSON:{exc}") from exc
    else:
        arr = messages
    if not isinstance(arr, list):
        raise ValueError("messages 必须是 JSON 数组。")
    parts = []
    for i, m in enumerate(arr):
        if not isinstance(m, dict):
            raise ValueError(f"messages[{i}] 必须是对象(含 role 和 content)。")
        if "role" not in m or "content" not in m:
            raise ValueError(f"messages[{i}] 缺少 role 或 content 字段。")
        parts.append(f"{m['role']}: {m['content']}")
    return "\n".join(parts).strip()


def user_metadata(meta):
    """从存储的 metadata 里取出用户自定义部分(去前缀)。"""
    return {
        k[len(MD_PREFIX):]: v
        for k, v in (meta or {}).items()
        if k.startswith(MD_PREFIX)
    }


def is_expired(meta, now=None):
    exp = (meta or {}).get("expires_at")
    if not exp:
        return False
    return exp <= (now if now is not None else time.time())


def memory_to_record(mem_id, doc, meta):
    """把一条记忆转成结构化 dict(用于 JSON 输出)。"""
    meta = meta or {}
    return {
        "id": mem_id,
        "content": doc,
        "tags": meta.get("tags") or "",
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "expires_at": meta.get("expires_at"),
        "scope": {k: meta[k] for k in SCOPE_KEYS if meta.get(k)},
        "metadata": user_metadata(meta),
    }


def hits_to_records(res, limit, now=None):
    """把 query 结果转成 record 列表,附带 similarity,跳过过期项,最多 limit 条。"""
    ids = res["ids"][0] if res["ids"] else []
    if not ids:
        return []
    now = now if now is not None else time.time()
    out = []
    for mem_id, doc, meta, dist in zip(
        ids, res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        if is_expired(meta, now):
            continue
        rec = memory_to_record(mem_id, doc, meta)
        rec["similarity"] = round(1 - dist, 3)
        out.append(rec)
        if len(out) >= limit:
            break
    return out
