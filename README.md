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

# Web 台(浏览器查看/检索/删除记忆,默认只绑 127.0.0.1)
lm-mem web start
```

## 装入 agent 规则文件

`lm-mem skill install` 把一段常驻触发规则写进已安装 agent 的规则文件，
让 agent 知道**何时**该调用记忆工具（完整策略见 skill 的 SKILL.md）。

自动检测下列 agent 的配置目录，装了几个写几个：

| agent | `--platform` 取值 | 检测目录 | 写入文件 |
|---|---|---|---|
| Claude Code | `claude` | `~/.claude/` | `CLAUDE.md` |
| Codex | `codex` | `~/.codex/` | `AGENTS.md` |
| opencode | `opencode` | `~/.config/opencode/` | `AGENTS.md` |
| OpenClaw | `openclaw` | `~/.openclaw/` | `AGENTS.md` |

```bash
lm-mem skill install      # 检测并写入(幂等，可重复执行以同步最新版本)
lm-mem skill status       # 查看各文件安装状态
lm-mem skill uninstall    # 移除写入的段落
```

只想操作某几个 agent 时用 `--platform`（可重复）：

```bash
lm-mem skill install --platform claude                     # 只写 Claude Code
lm-mem skill install --platform codex --platform openclaw  # 写这两个
lm-mem skill uninstall --platform claude                   # 只从 Claude 移除
```

显式指定的 platform **优先于自动检测** —— 配置目录还不存在也会照写并新建
（适合先把规则配好、之后再装那个 agent）。

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
| `LM_MEM_BACKEND_URL` | `http://$LM_MEM_BACKEND_HOST:$LM_MEM_BACKEND_PORT` | 后端地址;显式设置时优先于下面两项 |
| `LM_MEM_BACKEND_HOST` | `127.0.0.1` | 后端地址,`backend`/`web`/`mcp` 共用 |
| `LM_MEM_BACKEND_PORT` | `8901` | 后端端口,`backend`/`web`/`mcp` 共用 |
| `LM_MEM_EMBEDDED` | (关) | `=1` 时进程内嵌 Chroma 直读 `LM_MEM_DB_PATH`,不需要常驻后端 |
| `LM_MEM_AUTO_PURGE` | `1` | `lm-mem mcp` 启动时清一次过期记忆;`=0` 关闭(仍可手动调 `purge_expired`) |
| `LM_MEM_DATA_DIR` | `~/.lm-mem` | 数据根目录 |
| `LM_MEM_DB_PATH` | `$LM_MEM_DATA_DIR/chroma` | 数据库路径 |
| `LM_MEM_CHROMA` | (自动) | `backend start` 用的 chroma 可执行文件;默认取 `sys.executable` 同目录,找不到再靠 PATH。仅在 chroma 装在别处时才需显式指定 |
| `LM_MEM_WEB_HOST` | `127.0.0.1` | Web UI 绑定地址 |
| `LM_MEM_WEB_PORT` | `7531` | Web UI 端口 |

改后端端口要用环境变量(三个进程都得看到同一个值),别只给 `backend start --port`:

```bash
export LM_MEM_BACKEND_PORT=9000
lm-mem backend start && lm-mem web start   # web 会连到 9000
```

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