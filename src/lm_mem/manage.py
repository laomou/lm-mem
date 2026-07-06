#!/usr/bin/env python3
"""lm-mem 统一管理脚本。

用法:
  python manage.py backend start|stop|restart|status [--host HOST] [--port PORT]
  python manage.py web     start|stop|restart|status [--host HOST] [--port PORT]
  python manage.py mcp
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent.parent  # src/lm_mem/ → project root
PYTHON = os.environ.get("LM_MEM_PYTHON") or sys.executable
_CHROMA_CMD = os.environ.get("LM_MEM_CHROMA") or "chroma"
_DATA_ROOT = os.environ.get("LM_MEM_DATA_DIR") or str(Path.home() / ".lm-mem")
PID_DIR = Path(_DATA_ROOT) / "pids"
PID_DIR.mkdir(parents=True, exist_ok=True)
BACKEND_PID_FILE = PID_DIR / "backend.pid"
WEB_PID_FILE = PID_DIR / "web.pid"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8901
WEB_HOST = os.environ.get("LM_MEM_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("LM_MEM_WEB_PORT", "7531"))


def _w(s):
    print(s, file=sys.stderr)


# ── 进程托管:backend / web ────────────────────────────
#
# 两者都是"托管的外部进程":起一个子进程、写 PID、轮询就绪、
# 停时先 SIGTERM 再 pkill 兜底。差异只有 5 个维度,收敛进 _Service。


def _get_db_path():
    return os.environ.get("LM_MEM_DB_PATH", str(Path(_DATA_ROOT) / "chroma"))


def _backend_spawn(host, port):
    argv = [str(_CHROMA_CMD), "run", "--path", _get_db_path(),
            "--host", host, "--port", str(port)]
    return argv, None  # 无需额外 env


def _web_spawn(host, port):
    argv = [str(PYTHON), str(Path(__file__).parent / "web.py")]
    env = os.environ.copy()
    env["LM_MEM_BACKEND_URL"] = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    env["LM_MEM_WEB_HOST"] = host
    env["LM_MEM_WEB_PORT"] = str(port)
    return argv, env


@dataclass(frozen=True)
class _Service:
    """一个可托管进程的规格。start/stop/status 的差异全在这里。"""
    name: str                      # 展示名
    pid_file: Path                 # PID 落盘路径
    defaults: tuple                # (host, port) 缺省
    probe: "Callable[[str, int], str]"   # host,port -> 就绪探测 URL
    spawn: "Callable[[str, int], tuple]"  # host,port -> (argv, env)
    pkill: "Callable[[str, int], str]"    # host,port -> pkill -f 模式串
    wait_ticks: int                # 就绪轮询次数(每次 0.5s)


BACKEND = _Service(
    name="后端",
    pid_file=BACKEND_PID_FILE,
    defaults=(BACKEND_HOST, BACKEND_PORT),
    probe=lambda h, p: f"http://{h}:{p}/api/v2/heartbeat",
    spawn=_backend_spawn,
    pkill=lambda h, p: f"chroma.*run.*--port {p}",
    wait_ticks=60,
)

WEB = _Service(
    name="Web UI",
    pid_file=WEB_PID_FILE,
    defaults=(WEB_HOST, WEB_PORT),
    probe=lambda h, p: f"http://{h}:{p}/version",
    spawn=_web_spawn,
    pkill=lambda h, p: "python.*web.py",
    wait_ticks=30,
)


def _resolve(svc, host, port):
    return host or svc.defaults[0], port or svc.defaults[1]


def _running(svc, host, port):
    try:
        urllib.request.urlopen(svc.probe(host, port), timeout=2)
        return True
    except Exception:
        return False


def _start(svc, host=None, port=None):
    host, port = _resolve(svc, host, port)
    if _running(svc, host, port):
        _w(f"{svc.name}已在运行:http://{host}:{port}")
        return
    _w(f"启动{svc.name} → http://{host}:{port}")
    argv, env = svc.spawn(host, port)
    proc = subprocess.Popen(
        argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True, env=env,
    )
    svc.pid_file.write_text(str(proc.pid))
    for _ in range(svc.wait_ticks):
        if _running(svc, host, port):
            _w(f"{svc.name}已就绪 (pid={proc.pid})")
            return
        time.sleep(0.5)
    _w(f"{svc.name}启动超时")
    sys.exit(1)


def _stop(svc, host=None, port=None):
    host, port = _resolve(svc, host, port)
    if svc.pid_file.exists():
        pid = int(svc.pid_file.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            _w(f"{svc.name}已停止 (pid={pid})")
            svc.pid_file.unlink(missing_ok=True)
            return
        except ProcessLookupError:
            svc.pid_file.unlink(missing_ok=True)
    p = subprocess.run(["pkill", "-f", svc.pkill(host, port)], capture_output=True)
    _w(f"{svc.name}已停止" if p.returncode == 0 else f"{svc.name}未运行")


def _status(svc, host=None, port=None):
    host, port = _resolve(svc, host, port)
    if _running(svc, host, port):
        _w(f"{svc.name}运行中:http://{host}:{port}")
    else:
        _w(f"{svc.name}未运行")



# ── mcp ──────────────────────────────────────────────


def _mcp_run():
    """在当前进程内加载并运行 MCP server(stdio 模式)。"""
    backend_host = os.environ.get("LM_MEM_BACKEND_HOST", BACKEND_HOST)
    backend_port = os.environ.get("LM_MEM_BACKEND_PORT", str(BACKEND_PORT))
    os.environ.setdefault(
        "LM_MEM_BACKEND_URL",
        f"http://{backend_host}:{backend_port}",
    )
    from lm_mem.mcp_tools import mcp
    mcp.run()


# ── CLI ──────────────────────────────────────────────


def _build_parser():
    p = argparse.ArgumentParser(description="lm-mem 统一管理脚本")
    conn = argparse.ArgumentParser(add_help=False)
    conn.add_argument("--host", default=None, help="绑定地址或连接地址")
    conn.add_argument("--port", type=int, default=None, help="绑定端口或连接端口")

    sub = p.add_subparsers(dest="entity", required=True)
    sub.add_parser("mcp", help="前台运行 MCP server")

    for entity in ("backend", "web"):
        ep = sub.add_parser(entity, parents=[conn], help=f"{entity} 管理")
        ep.add_argument("action", nargs="?", default="status",
                        choices=["start", "stop", "restart", "status"])
    return p


# 可托管的外部服务:entity 名 → 规格。mcp 不在此列(它是前台运行,见 _run)。
_SERVICES = {"backend": BACKEND, "web": WEB}
_ACTIONS = {"start": _start, "stop": _stop, "status": _status}


def _run(entity, action, host, port):
    # mcp:自身即进程,前台阻塞运行,不走进程托管
    if entity == "mcp":
        _mcp_run()
        return
    svc = _SERVICES.get(entity)
    if svc is None:
        _w(f"未知实体:{entity}")
        sys.exit(1)
    if action == "restart":
        _stop(svc, host, port)
        time.sleep(1)
        _start(svc, host, port)
    else:
        _ACTIONS[action](svc, host, port)


def main():
    p = _build_parser()
    args = p.parse_args()
    _run(args.entity, getattr(args, "action", ""),
         getattr(args, "host", None), getattr(args, "port", None))


if __name__ == "__main__":
    main()