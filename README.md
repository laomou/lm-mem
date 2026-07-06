# lm-mem

本地语义记忆 MCP Server — 跨会话持久化,语义检索。

## 安装

```bash
pip install lm-mem
# 或
uvx lm-mem-mcp
```

## 使用

```bash
# 启动后端
lm-mem backend start

# 启动 Web UI (http://127.0.0.1:7531)
lm-mem web start

# MCP Server (stdio)
lm-mem-mcp
# 或
uvx lm-mem-mcp
```

## MCP 客户端配置

```json
{
  "mcpServers": {
    "memory": {
      "command": "uvx",
      "args": ["lm-mem-mcp"]
    }
  }
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LM_MEM_BACKEND_URL` | `http://127.0.0.1:8901` | 后端地址 |
| `LM_MEM_BACKEND_PORT` | `8901` | 后端端口(仅 `_run` / `manage.py` 用) |
| `LM_MEM_DATA_DIR` | `~/.lm-mem` | 数据根目录 |
| `LM_MEM_DB_PATH` | `$LM_MEM_DATA_DIR/chroma` | 数据库路径 |
| `LM_MEM_WEB_HOST` | `127.0.0.1` | Web UI 绑定地址 |
| `LM_MEM_WEB_PORT` | `7531` | Web UI 端口 |

## 作为库使用

```python
from lm_mem.backend import _collection
from lm_mem.memory_utils import _hits_to_records, _scope_where
from lm_mem.mcp_tools import search_memories, add_memory
```