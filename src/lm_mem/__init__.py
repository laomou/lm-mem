"""lm-mem — 本地语义记忆,跨会话持久化。

作为 MCP Server 运行:
    uvx lm-mem-mcp

作为 CLI 管理:
    lm-mem backend start
    lm-mem web start

作为库使用:
    from lm_mem import add, search
"""

__version__ = "0.4.0"