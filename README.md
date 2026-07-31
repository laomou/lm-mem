# lm-mem

[中文](README_zh.md)

Local semantic memory MCP server — cross-session persistence, semantic retrieval.

Gives an AI agent a memory it can read and write across sessions: save user preferences, project decisions, and past conclusions, then retrieve them later by meaning. All data stays local.

## Install

```bash
pip install lm-mem      # or: uvx lm-mem <command>
```

## Usage

```bash
lm-mem backend start    # 1. start the resident backend (storage + vector search)
lm-mem mcp              # 2. run as an MCP server (stdio) for agents to connect
lm-mem web start        # (optional) browse/search/delete memories in a browser, default http://127.0.0.1:7531
```

`mcp` is a pure client — it connects to the backend started by `backend start`, so **start the backend first**. The backend runs in its own session and keeps running after you close the terminal; stop it with `lm-mem backend stop`.

> Don't want a separate backend process? Set `LM_MEM_EMBEDDED=1` and the MCP process reads/writes the local database directly, skipping `backend start`. Suitable only when a single process accesses the store — for concurrent access (e.g. MCP + web at once) use the default backend mode.

## Connect an agent (MCP client config)

Add this to your MCP client (e.g. Claude Code):

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

Then run `lm-mem skill install` to write a small resident trigger snippet into your agent's
rules file, so it knows **when** to call the memory tools (full policy lives in the SKILL.md
shipped with the plugin). It auto-detects Claude Code / Codex / opencode / OpenClaw and writes
to whichever are installed; `--platform claude` (repeatable) targets specific ones.

```bash
lm-mem skill install      # idempotent, re-run to sync the latest version
lm-mem skill status       # show install status
lm-mem skill uninstall    # remove
```

## Use as a library

```python
from lm_mem import MemoryClient

client = MemoryClient()                 # connects to the shared backend (via LM_MEM_BACKEND_URL)

# save (near-duplicate within the same scope is auto-detected; force=True skips the check)
client.add("用户偏好 pytest", user_id="u1")
client.add(messages=[{"role": "user", "content": "I like cats"}], user_id="u1")

# semantic search
for r in client.search("测试框架偏好", user_id="u1")["items"]:
    print(r["content"], r["similarity"])

# get / update / delete
client.get("mem-id-xxx")
client.update("mem-id-xxx", content="new content")
client.delete("mem-id-xxx")
```

## Configuration

Common environment variables:

| Variable | Default | Description |
|---|---|---|
| `LM_MEM_BACKEND_URL` | `http://127.0.0.1:8901` | backend address the MCP client connects to |
| `LM_MEM_EMBEDDED` | (off) | `=1` embeds storage in-process, no resident backend needed |
| `LM_MEM_DATA_DIR` | `~/.lm-mem` | data root directory |

Change the port with `LM_MEM_BACKEND_PORT` (shared by backend / web / mcp — don't just pass
`--port`). See `lm-mem <command> --help` and the source for the full list.

The backend started by `backend start` is already resident, but it is **not** auto-restarted on
crash or reboot. If you need that, hand the chroma process to a service manager (systemd /
supervisor, `Restart=on-failure`).
