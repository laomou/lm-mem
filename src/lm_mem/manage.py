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

PYTHON = os.environ.get("LM_MEM_PYTHON") or sys.executable


def _resolve_chroma() -> str:
    """chroma 可执行文件路径。

    chromadb 是 lm-mem 的依赖,`chroma` 一定和 sys.executable 装在同一个 venv 的
    bin 目录。优先用那个绝对路径 —— 这样即使没激活 venv、用绝对路径调 lm-mem、
    或 PATH 里根本没有那个 bin 目录(uvx 等场景),也能起后端。找不到再退回裸
    "chroma" 靠 PATH。LM_MEM_CHROMA 可显式覆盖(如指向系统级/容器内的 chroma)。

    (web.py 已经用 sys.executable 起 web 进程,这里对 chroma 做同样的事。)
    """
    if cmd := os.environ.get("LM_MEM_CHROMA"):
        return cmd
    bindir = Path(sys.executable).parent
    for name in ("chroma", "chroma.exe"):
        if (bindir / name).exists():
            return str(bindir / name)
    return "chroma"


_CHROMA_CMD = _resolve_chroma()
_DATA_ROOT = os.environ.get("LM_MEM_DATA_DIR") or str(Path.home() / ".lm-mem")
PID_DIR = Path(_DATA_ROOT) / "pids"
PID_DIR.mkdir(parents=True, exist_ok=True)
BACKEND_PID_FILE = PID_DIR / "backend.pid"
WEB_PID_FILE = PID_DIR / "web.pid"

# 后端地址:backend / web / mcp 三方必须看到同一个值,否则 web 会去连一个
# 没人监听的端口。改端口用 LM_MEM_BACKEND_PORT(或直接给 LM_MEM_BACKEND_URL);
# `--port` 只作用于本次调用。
BACKEND_HOST = os.environ.get("LM_MEM_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.environ.get("LM_MEM_BACKEND_PORT", "8901"))
WEB_HOST = os.environ.get("LM_MEM_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("LM_MEM_WEB_PORT", "7531"))


def _backend_url(host=None, port=None):
    """后端 URL。显式给的 LM_MEM_BACKEND_URL 优先,其次 host/port。"""
    if url := os.environ.get("LM_MEM_BACKEND_URL", "").strip():
        return url
    return f"http://{host or BACKEND_HOST}:{port or BACKEND_PORT}"


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
    # argv 末尾附一个纯标记(web.main 从 env 读配置、不解析 argv),
    # 使进程 cmdline 里带端口,pkill / pid 身份校验都能精确识别本服务。
    argv = [str(PYTHON), str(Path(__file__).parent / "web.py"),
            f"--lm-mem-web-port={port}"]
    env = os.environ.copy()
    env["LM_MEM_BACKEND_URL"] = _backend_url()
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
    pkill=lambda h, p: f"web.py --lm-mem-web-port={p}",
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


def _pid_is(svc, pid, host, port):
    """校验 pid 当前确实是本服务(防 pid 被系统复用后误杀)。

    读 /proc/<pid>/cmdline,匹配该服务 pkill 特征串的关键片段。
    读不到(非 Linux / 无 procfs)时返回 True,退回原有信任 PID 文件的行为。
    """
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False
    except OSError:
        return True  # 无 procfs,无法校验,退回信任
    # pkill 模式里的端口特征就是最可靠的身份标记
    return f"--lm-mem-web-port={port}" in cmdline if svc is WEB else f"--port {port}" in cmdline


def _await_exit(pid, timeout=10.0):
    """等 pid 真正退出;超时未退则 SIGKILL 兜底。返回是否已确认退出。

    SIGTERM 是异步的:chroma 收到后可能还在 flush 索引,进程不会立刻消失。
    发完信号就报"已停止"会误导用户,更会让紧随其后的 restart 撞上"旧进程还占着
    端口"。用 os.kill(pid, 0) 轮询存活(不真正发信号,只探测),给 chroma 一个
    干净落盘的窗口;实在不退再 SIGKILL。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)          # 只探测:进程还在则成功返回
        except ProcessLookupError:
            return True              # 已退出
        except PermissionError:
            return True              # 存在但非本用户(不该发生),当作已处理
        time.sleep(0.2)
    # 超时仍在 → 强杀兜底
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return False


def _stop(svc, host=None, port=None):
    host, port = _resolve(svc, host, port)
    if svc.pid_file.exists():
        # PID 文件可能是空的/被写坏的(进程被 kill -9、磁盘满……)。
        # 这种情况必须继续走下面的 pkill 兜底,而不是抛 ValueError 出去。
        try:
            pid = int(svc.pid_file.read_text().strip())
        except (ValueError, OSError):
            pid = 0
        if pid and _pid_is(svc, pid, host, port):
            try:
                os.kill(pid, signal.SIGTERM)
                # 等它真的退出再报成功,否则 restart 会撞上旧进程占端口
                if _await_exit(pid):
                    _w(f"{svc.name}已停止 (pid={pid})")
                else:
                    _w(f"{svc.name}未在超时内退出,已强制杀死 (pid={pid})")
                svc.pid_file.unlink(missing_ok=True)
                return
            except ProcessLookupError:
                pass
        svc.pid_file.unlink(missing_ok=True)  # pid 已失效或身份不符,清掉陈旧 PID 文件
    p = subprocess.run(["pkill", "-f", svc.pkill(host, port)], capture_output=True)
    _w(f"{svc.name}已停止" if p.returncode == 0 else f"{svc.name}未运行")


def _status(svc, host=None, port=None):
    host, port = _resolve(svc, host, port)
    if _running(svc, host, port):
        _w(f"{svc.name}运行中:http://{host}:{port}")
    else:
        _w(f"{svc.name}未运行")



# ── mcp ──────────────────────────────────────────────


def _auto_purge():
    """启动时清一次过期记忆。

    TTL 到期的记忆此前只是"检索时被忽略",行一直留在库里 —— 没有任何东西会
    自动删它们,于是 DB 单调增长、memory_stats.total 越来越虚高。这里在 MCP
    启动时做一次清理,给 TTL 一个真正的回收点。

    best-effort:后端连不上等任何异常都只警告,绝不阻断 MCP 启动。
    设 LM_MEM_AUTO_PURGE=0 可关闭。
    """
    if os.environ.get("LM_MEM_AUTO_PURGE", "1").strip().lower() in ("0", "false", "no", "off"):
        return
    try:
        from lm_mem.client import MemoryClient
        n = MemoryClient().purge_expired()["deleted"]
        if n:
            _w(f"已清理 {n} 条过期记忆")
    except Exception as exc:  # noqa: BLE001 —— 清理失败不该拖垮启动
        _w(f"跳过过期清理({type(exc).__name__})")


def _mcp_run():
    """在当前进程内加载并运行 MCP server(stdio 模式)。"""
    os.environ.setdefault("LM_MEM_BACKEND_URL", _backend_url())
    _auto_purge()
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

    skill = sub.add_parser(
        "skill", help="把 lm-mem 触发段落写入 agent 规则文件(默认自动检测)")
    skill.add_argument("action", nargs="?", default="status",
                       choices=["install", "uninstall", "status"])
    # 默认对所有检测到的 agent 生效;--platform 可只针对指定的(可重复)。
    # choices 交给 argparse 校验,拼错时它会直接给出可选值列表。
    from lm_mem.skill_install import PLATFORMS
    skill.add_argument("--platform", action="append", choices=PLATFORMS, default=None,
                       metavar="NAME",
                       help="只操作指定 agent(可重复);留空则全部已检测到的。"
                            f"可选:{'/'.join(PLATFORMS)}")
    return p


# 可托管的外部服务:entity 名 → 规格。mcp 不在此列(它是前台运行,见 _run)。
_SERVICES = {"backend": BACKEND, "web": WEB}
_ACTIONS = {"start": _start, "stop": _stop, "status": _status}


def _run(entity, action, host, port, platforms=()):
    # mcp:自身即进程,前台阻塞运行,不走进程托管
    if entity == "mcp":
        _mcp_run()
        return
    if entity == "skill":
        from lm_mem import skill_install
        {"install": skill_install.install,
         "uninstall": skill_install.uninstall,
         "status": skill_install.status}[action](platforms)
        return
    svc = _SERVICES.get(entity)
    if svc is None:
        _w(f"未知实体:{entity}")
        sys.exit(1)
    if action == "restart":
        _stop(svc, host, port)   # 现在会等进程真正退出,不再需要 sleep 猜时间
        _start(svc, host, port)  # _start 自带就绪轮询,能容忍端口释放的毫秒级延迟
    else:
        _ACTIONS[action](svc, host, port)


def main():
    p = _build_parser()
    args = p.parse_args()
    _run(args.entity, getattr(args, "action", ""),
         getattr(args, "host", None), getattr(args, "port", None),
         tuple(getattr(args, "platform", None) or ()))


if __name__ == "__main__":
    main()