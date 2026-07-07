"""lm-mem — 本地语义记忆,跨会话持久化。

作为 MCP Server 运行:
    uvx lm-mem-mcp

作为 CLI 管理:
    lm-mem backend start
    lm-mem web start

作为库使用:
    from lm_mem import MemoryClient

    client = MemoryClient()
    client.add("用户偏好 pytest", user_id="u1")
    results = client.search("测试框架", user_id="u1")
"""

__version__ = "0.6.0"

from lm_mem.client import MemoryClient

__all__ = ["MemoryClient"]