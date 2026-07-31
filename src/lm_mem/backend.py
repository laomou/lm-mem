"""lm-mem 存储后端客户端连接。

默认 MCP 进程只当纯客户端,连接外部常驻后端(由 manage.py 托管),
后端生命周期完全独立于 MCP。

两种模式:
- `LM_MEM_BACKEND_URL` 指向常驻后端(默认,生产用法)
- `LM_MEM_EMBEDDED=1` 进程内嵌 PersistentClient,直读 DB_PATH,不需要后端
  (单进程 / 库内嵌 / 测试隔离用)

注意:所有全局状态通过惰性初始化获取(get_collection()),
避免导入时即触发后端连接。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import chromadb

_data_root = os.environ.get("LM_MEM_DATA_DIR") or str(Path.home() / ".lm-mem")
DB_PATH = os.environ.get("LM_MEM_DB_PATH", str(Path(_data_root) / "chroma"))
# 不在 import 时 mkdir:纯客户端模式下 DB_PATH 根本用不到,建目录纯属副作用。
# 目录由 _embedded_client() 在真正要落盘时创建。

_collection: "chromadb.Collection | None" = None

_FALSEY = ("", "0", "false", "no", "off")


def _connect(host, port):
    """尝试连接后端;连不上返回 None(不抛异常)。"""
    try:
        import chromadb
        client = chromadb.HttpClient(host=host, port=port)
        client.heartbeat()
        return client
    except Exception:
        return None


def _embedded_enabled():
    """是否启用进程内嵌模式(LM_MEM_EMBEDDED)。"""
    return os.environ.get("LM_MEM_EMBEDDED", "").strip().lower() not in _FALSEY


def _embedded_client():
    import chromadb
    Path(DB_PATH).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=DB_PATH)


def _connect_or_raise(url):
    u = urlparse(url if "://" in url else f"http://{url}")
    host = u.hostname or "127.0.0.1"
    port = u.port or 8000
    client = _connect(host, port)
    if client is None:
        raise RuntimeError(
            f"后端 {host}:{port} 连接失败。"
            f"请先用 lm-mem backend start 启动后端。"
        )
    return client


def _init_client():
    """初始化 client。

    优先 LM_MEM_BACKEND_URL(纯客户端,连常驻后端,连不上直接报错);
    否则看 LM_MEM_EMBEDDED 是否要求进程内嵌;都没有则报错。
    """
    if url := os.environ.get("LM_MEM_BACKEND_URL", "").strip():
        return _connect_or_raise(url)
    if _embedded_enabled():
        return _embedded_client()
    raise RuntimeError(
        "未设置 LM_MEM_BACKEND_URL,无法连接后端。"
        "请在 .mcp.json 的 env 中添加 LM_MEM_BACKEND_URL=http://127.0.0.1:8901,"
        "或设 LM_MEM_EMBEDDED=1 走进程内嵌模式(不需要常驻后端)。"
    )


def _init_collection(client):
    """从 client 获取或创建 memories 集合。"""
    return client.get_or_create_collection(
        name="memories",
        metadata={
            "hnsw:space": "cosine",
            "hnsw:M": 4,
            "hnsw:construction_ef": 30,
            "hnsw:search_ef": 2,
            "hnsw:num_threads": 20,
        },
    )


def get_collection():
    """惰性获取 ChromaDB 集合(首次调用时初始化连接)。"""
    global _collection
    if _collection is None:
        _collection = _init_collection(_init_client())
    return _collection


def collection_for_url(url):
    """为指定后端 URL 构造集合(不走全局缓存,供 MemoryClient(url=...) 用)。"""
    return _init_collection(_connect_or_raise(url))