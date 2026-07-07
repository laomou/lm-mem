# lm-mem

本地语义记忆 MCP Server — 跨会话持久化,语义检索。

## 安装

```bash
pip install lm-mem
```

## 使用

```bash
# 启动后端
lm-mem backend start

# MCP Server (stdio)
lm-mem mcp

# Web 台(只读,浏览器查看/检索记忆)
lm-mem web start
```

## 装入 agent 规则文件

`lm-mem skill install` 把一段常驻触发规则写进已安装 agent 的规则文件，
让 agent 知道**何时**该调用记忆工具（完整策略见 skill 的 SKILL.md）。

自动检测下列 agent 的配置目录，装了几个写几个：

| agent | 检测目录 | 写入文件 |
|---|---|---|
| Claude Code | `~/.claude/` | `CLAUDE.md` |
| Codex | `~/.codex/` | `AGENTS.md` |
| opencode | `~/.config/opencode/` | `AGENTS.md` |
| OpenClaw | `~/.openclaw/` | `AGENTS.md` |

```bash
lm-mem skill install      # 检测并写入(幂等，可重复执行以同步最新版本)
lm-mem skill status       # 查看各文件安装状态
lm-mem skill uninstall    # 移除写入的段落
```

写入内容用 `<!-- lm-mem:begin -->…<!-- lm-mem:end -->` 包裹，不影响文件其余部分。

## MCP 客户端配置

```json
{
  "mcpServers": {
    "memory": {
      "command": "uvx",
      "args": ["lm-mem", "mcp"],
      "env": {
        "LM_MEM_BACKEND_URL": "http://127.0.0.1:8901"
      }
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
from lm_mem import MemoryClient

client = MemoryClient()                 # 用共享后端(由 LM_MEM_BACKEND_URL 决定)
# client = MemoryClient(url="http://127.0.0.1:8901")  # 或显式指定后端

# 保存(同作用域内内容高度相似会自动查重;force=True 跳过)
client.add("用户偏好 pytest", user_id="u1")
client.add(messages=[{"role": "user", "content": "I like cats"}], user_id="u1")

# 语义检索
for r in client.search("测试框架偏好", user_id="u1")["items"]:
    print(r["content"], r["similarity"])

# 查看 / 更新 / 删除
client.get("mem-id-xxx")
client.update("mem-id-xxx", content="新内容")
client.delete("mem-id-xxx")
```