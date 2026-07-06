"""lm-mem MCP 工具层:FastMCP + 14 个 @mcp.tool()。

业务逻辑全部委托给 MemoryClient(client.py),本层只负责:
- 声明 MCP 工具签名与 docstring(供 LLM 理解)
- 把 MemoryClient 返回的 dict 序列化成 JSON 字符串

## 返回值约定(MCP-native)

- **成功**:直接返回业务数据的 JSON 字符串,不包 `{ok, ...}` envelope
- **失败**:抛异常,MCP 协议层自动包装成 `isError: true` 返回给 LLM
- **业务分支**(如 add_memory 查重命中):返回带业务标识字段的 JSON(如 `duplicate_id`),不是错误

时间戳统一 Unix 秒(float),前端负责格式化。
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from lm_mem.client import MemoryClient

mcp = FastMCP("lm-mem")
_client = MemoryClient()


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


@mcp.tool()
def add_memory(
    content: str = "",
    messages: str = "",
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
    tags: str = "",
    metadata: str = "",
    ttl_seconds: int = 0,
    force: bool = False,
) -> str:
    """保存一条记忆(可绑定作用域、自定义元数据、过期时间)。

    输入(二选一):
        content: 要记住的文本。
        messages: 对话历史(JSON 数组,如 '[{"role":"user","content":"..."}]'),
                  未提供 content 时会自动拼成文本存储。

    Args:
        user_id / agent_id / app_id / run_id: 可选,记忆归属的实体(可多个)。
        tags: 可选,逗号分隔的标签。
        metadata: 可选,JSON 对象字符串,附加 category/importance/source 等自定义字段。
        ttl_seconds: 可选,>0 时记忆在该秒数后过期(检索自动忽略,可用 purge_expired 清理)。
        force: 默认 False。为 False 时,若同作用域内已有高度相似记忆,则不插入、
               直接返回疑似重复项交由调用方决策(更新/跳过/强制新增)。

    Returns:
        成功:`{"id": "..."}`
        查重命中:`{"duplicate_id": "...", "similarity": 0.95, "existing_content": "...", "hint": "..."}`
    Raises:
        ValueError: content 与 messages 均为空。
    """
    return _dumps(_client.add(
        content, messages=messages, user_id=user_id, agent_id=agent_id,
        app_id=app_id, run_id=run_id, tags=tags, metadata=metadata,
        ttl_seconds=ttl_seconds, force=force,
    ))


@mcp.tool()
def search_memories(
    query: str,
    limit: int = 5,
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
    metadata_filter: str = "",
) -> str:
    """按语义相似度检索记忆,可用作用域 / 自定义元数据过滤。

    Args:
        query: 检索问题/关键词(自然语言)。
        limit: 返回的最大条数,默认 5。
        user_id / agent_id / app_id / run_id: 可选,限定检索范围。
        metadata_filter: 可选,JSON 对象字符串,按自定义 metadata 精确过滤
                         (如 '{"category":"pref"}')。

    Returns:
        `{"items": [{id, content, similarity, scope, metadata, ...}]}`
    """
    return _dumps(_client.search(
        query, limit=limit, user_id=user_id, agent_id=agent_id,
        app_id=app_id, run_id=run_id, metadata_filter=metadata_filter,
    ))


@mcp.tool()
def get_memories(
    limit: int = 50,
    offset: int = 0,
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
    metadata_filter: str = "",
) -> str:
    """列出记忆,支持作用域 / 元数据过滤与分页。

    Args:
        limit: 每页条数,默认 50。
        offset: 偏移量,用于翻页,默认 0。
        user_id / agent_id / app_id / run_id: 可选,限定范围。
        metadata_filter: 可选,JSON 对象字符串,按自定义 metadata 过滤。

    Returns:
        `{"items": [...], "offset": 0}`
    """
    return _dumps(_client.list(
        limit=limit, offset=offset, user_id=user_id, agent_id=agent_id,
        app_id=app_id, run_id=run_id, metadata_filter=metadata_filter,
    ))


@mcp.tool()
def get_memory(mem_id: str) -> str:
    """按 id 获取单条记忆。

    Returns:
        `{"id": ..., "content": ..., ...}` — 单条记忆的完整字段
    Raises:
        ValueError: 未找到 mem_id。
    """
    return _dumps(_client.get(mem_id))


@mcp.tool()
def update_memory(
    mem_id: str,
    content: str = "",
    metadata: str = "",
    tags: str = "",
    ttl_seconds: int = 0,
) -> str:
    """按 id 更新记忆(保留原作用域;可同时改文本/元数据/标签/过期时间)。

    Args:
        mem_id: 记忆 id。
        content: 可选,新的文本内容(留空则不改文本)。
        metadata: 可选,JSON 对象字符串,合并进现有自定义元数据。
        tags: 可选,新的逗号分隔标签(留空则不改)。
        ttl_seconds: 可选。>0 从现在起续期该秒数;<0 立即清除过期时间(转为永久);
                     0(默认)不改动过期设置。

    Returns:
        `{"id": mem_id}`
    Raises:
        ValueError: 未找到 mem_id。
    """
    return _dumps(_client.update(
        mem_id, content=content, metadata=metadata, tags=tags, ttl_seconds=ttl_seconds,
    ))


@mcp.tool()
def delete_memory(mem_id: str) -> str:
    """按 id 删除单条记忆。

    Returns:
        `{"id": mem_id}`
    Raises:
        ValueError: 未找到 mem_id。
    """
    return _dumps(_client.delete(mem_id))


@mcp.tool()
def delete_all_memories(
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
) -> str:
    """批量删除作用域内的所有记忆。

    安全约束:必须至少提供一个作用域(user/agent/app/run),
    以避免误删整个记忆库。

    Returns:
        `{"deleted": N}` — 实际删除数量(0 表示该作用域内本就没记忆)
    Raises:
        ValueError: 未指定任何作用域。
    """
    return _dumps(_client.delete_all(
        user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id,
    ))


@mcp.tool()
def delete_entities(entity_type: str, entity_id: str) -> str:
    """删除某个实体及其所有记忆。

    Args:
        entity_type: 实体类型,取值 user / agent / app / run。
        entity_id: 实体标识。

    Returns:
        `{"deleted": N}`
    Raises:
        ValueError: entity_type 非法,或未找到实体。
    """
    return _dumps(_client.delete_entity(entity_type, entity_id))


@mcp.tool()
def list_entities(entity_type: str = "") -> str:
    """列出已存储的实体(users/agents/apps/runs)。

    Args:
        entity_type: 可选,只列某一类(user/agent/app/run);留空则全部。

    Returns:
        `{"entities": {"user_id": [...], "agent_id": [...], ...}}` — 统一按类型分组
    Raises:
        ValueError: entity_type 非法。
    """
    return _dumps(_client.list_entities(entity_type))


@mcp.tool()
def memory_stats(
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
) -> str:
    """统计记忆库:总数、按作用域/标签/自定义分类聚合、过期数量。

    Args:
        user_id / agent_id / app_id / run_id: 可选,只统计某作用域。

    Returns:
        `{"counts": {"total", "active", "expired"}, "scope": {...}, "tags": {...}, "categories": {...}}`
    """
    return _dumps(_client.stats(
        user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id,
    ))


@mcp.tool()
def export_memories(
    fmt: str = "json",
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
) -> str:
    """批量导出记忆为 JSON 或 CSV 文本。

    Args:
        fmt: 导出格式,json(默认)或 csv。
        user_id / agent_id / app_id / run_id: 可选,只导出某作用域。

    Returns:
        fmt=json: `{"records": [...]}`
        fmt=csv:  `{"csv": "..."}`
    Raises:
        ValueError: fmt 非法。
    """
    return _dumps(_client.export(
        fmt=fmt, user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id,
    ))


@mcp.tool()
def purge_expired() -> str:
    """清理所有已过期(超过 TTL)的记忆。

    Returns:
        `{"deleted": N}`
    """
    return _dumps(_client.purge_expired())


@mcp.tool()
def get_user_context(
    user_id: str = "",
    limit: int = 10,
) -> str:
    """获取用户的核心上下文:偏好、身份、环境等长期属性。

    LLM 应在**新会话第一轮涉及代码/行为决策时**主动调用一次,把结果吃进上下文,
    避免后续每轮都要 search_memories。返回结果按 importance:high 优先。

    Args:
        user_id: 可选,限定用户(推荐传入,以免拿到别人的偏好)。
        limit: 返回条数上限,默认 10。

    Returns:
        `{"items": [{id, content, category, importance, ...}]}` — 按 importance 排序。
    """
    return _dumps(_client.get_user_context(user_id=user_id, limit=limit))


@mcp.tool()
def import_memories(
    data: str,
    fmt: str = "json",
    overwrite: bool = False,
    new_ids: bool = False,
) -> str:
    """从导出数据批量导入记忆(对称 export_memories)。

    Args:
        data: JSON 数组字符串(fmt=json,与 export.records 同构) 或 CSV 字符串(fmt=csv,含 header)。
        fmt: 'json' 或 'csv',默认 json。
        overwrite: 遇到重复 id 时是否覆盖(默认 False,重复 id 会被 skip)。
        new_ids: 是否为每条生成新 uuid(默认 False 保留原 id)。overwrite 与 new_ids 互斥。

    Returns:
        `{"imported": N, "skipped": N, "overwritten": N}`
    Raises:
        ValueError: fmt 非法 / data 解析失败 / overwrite 与 new_ids 同时为 True。
    """
    return _dumps(_client.import_data(
        data, fmt=fmt, overwrite=overwrite, new_ids=new_ids,
    ))
