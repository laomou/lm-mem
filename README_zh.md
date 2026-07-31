# lm-mem

[English](README.md)

本地语义记忆 MCP Server — 跨会话持久化,语义检索。

给 AI agent 一块能跨会话读写的记忆:保存用户偏好 / 项目决策 / 历史结论,之后按语义检索回来。数据全部落在本地。

## 安装

```bash
pip install lm-mem      # 或 uvx lm-mem <命令>
```

## 使用

```bash
lm-mem backend start    # 1. 启动常驻后端(存储 + 向量检索)
lm-mem mcp              # 2. 以 MCP Server(stdio)运行,供 agent 连接
lm-mem web start        # (可选)浏览器里查看/检索/删除记忆,默认 http://127.0.0.1:7531
```

`mcp` 是纯客户端,连的是 `backend start` 起的后端 —— 所以**先起 backend**。后端以独立
会话常驻,终端关掉也不受影响;停用 `lm-mem backend stop`。

> 不想单独起后端?设 `LM_MEM_EMBEDDED=1`,MCP 进程直接读写本地数据库,省掉 `backend
> start`。仅适合单进程访问;要并发访问(如 MCP + web 同时开)请用默认的后端模式。

## 接入 agent(MCP 客户端配置)

在 MCP 客户端(如 Claude Code)的配置里加:

```json
{
  "mcpServers": {
    "memory": {
      "command": "uvx",
      "args": ["lm-mem", "mcp"],
      "env": { "LM_MEM_BACKEND_URL": "http://127.0.0.1:8901" }
    }
  }
}
```

再用 `lm-mem skill install` 把一段常驻触发规则写进已安装 agent 的规则文件,让它知道
**何时**该调用记忆工具(完整策略见随插件分发的 SKILL.md)。自动检测 Claude Code /
Codex / opencode / OpenClaw,装了几个写几个;`--platform claude`(可重复)只装指定的。

```bash
lm-mem skill install      # 幂等,可重复执行以同步最新版本
lm-mem skill status       # 查看安装状态
lm-mem skill uninstall    # 移除
```

## 作为库使用

```python
from lm_mem import MemoryClient

client = MemoryClient()                 # 连共享后端(由 LM_MEM_BACKEND_URL 决定)

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

## 配置

常用环境变量:

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LM_MEM_BACKEND_URL` | `http://127.0.0.1:8901` | 后端地址,MCP 客户端连它 |
| `LM_MEM_EMBEDDED` | (关) | `=1` 进程内嵌存储,不需要常驻后端 |
| `LM_MEM_DATA_DIR` | `~/.lm-mem` | 数据根目录 |

改端口用 `LM_MEM_BACKEND_PORT`(backend / web / mcp 三方共用,别只给 `--port`)。
完整变量列表见 `lm-mem <命令> --help` 与源码。

后端已随 `backend start` 常驻,但**不会崩溃/开机自动拉起**;需要自愈就把 chroma 进程
交给 systemd / supervisor 监管(`Restart=on-failure`)。
