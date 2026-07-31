"""`lm-mem skill install` —— 把 lm-mem 的常驻触发段落写入已检测到的 agent 规则文件。

设计:
- 触发文本作为包内资源(assets/trigger_rules.md)随 wheel 分发。
- 用 marker 块包裹写入,保证幂等:重复 install 是"就地更新"而非重复追加。
- 目标 agent 靠**配置目录是否存在**自动检测,装了几个就写几个;都没有则跳过。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

BEGIN = "<!-- lm-mem:begin (由 `lm-mem skill install` 管理,勿手改) -->"
END = "<!-- lm-mem:end -->"


@dataclass(frozen=True)
class Agent:
    key: str            # --platform 的取值
    label: str          # 展示名
    config_dir: Path    # 存在即视作"装了这个 agent"
    target: Path        # 规则文件写入路径


# --platform 可选值。与 _agents() 的 key 一一对应(有测试守着不漂移),
# 单独列出来是为了让 argparse 能用 choices= 直接校验并给出友好报错。
PLATFORMS = ("claude", "codex", "opencode", "openclaw")


# 已知 agent 注册表:配置目录 → 规则文件。新增 agent 只改这里(和 PLATFORMS)。
def _agents() -> list[Agent]:
    h = Path.home()
    return [
        Agent("claude", "Claude Code", h / ".claude", h / ".claude" / "CLAUDE.md"),
        Agent("codex", "Codex", h / ".codex", h / ".codex" / "AGENTS.md"),
        Agent("opencode", "opencode", h / ".config" / "opencode",
              h / ".config" / "opencode" / "AGENTS.md"),
        Agent("openclaw", "OpenClaw", h / ".openclaw", h / ".openclaw" / "AGENTS.md"),
    ]


def _w(s):
    print(s, file=sys.stderr)


def _snippet() -> str:
    """读取包内模板文本。"""
    return (files("lm_mem") / "assets" / "trigger_rules.md").read_text(
        encoding="utf-8"
    ).strip()


def _block() -> str:
    return f"{BEGIN}\n{_snippet()}\n{END}"


def _split(text: str) -> tuple[str, str, str]:
    """把现有内容按 marker 切成 (before, block, after)。未安装时 block 为空串。"""
    i = text.find(BEGIN)
    if i == -1:
        return text, "", ""
    j = text.find(END, i)
    if j == -1:  # 只有 begin 没有 end:视作损坏,吞掉从 begin 到结尾
        return text[:i], text[i:], ""
    return text[:i], text[i : j + len(END)], text[j + len(END) :]


def _detect() -> list[Agent]:
    """返回配置目录已存在的 agent(即"装了"的)。"""
    return [a for a in _agents() if a.config_dir.is_dir()]


def _install_one(target: Path) -> None:
    block = _block()
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(block + "\n", encoding="utf-8")
        _w(f"已创建 {target} 并写入 lm-mem 触发段落")
        return
    text = target.read_text(encoding="utf-8")
    before, existing, after = _split(text)
    if existing == block:
        _w(f"{target} 已是最新,无需改动")
        return
    if existing:  # 就地更新
        target.write_text(before + block + after, encoding="utf-8")
        _w(f"已更新 lm-mem 触发段落 → {target}")
    else:  # 追加到文件末尾(文件为空/纯空白时直接写,避免前导空行)
        body = text.rstrip("\n")
        target.write_text((body + "\n\n" if body else "") + block + "\n", encoding="utf-8")
        _w(f"已{'追加' if body else '写入'} lm-mem 触发段落 → {target}")


def _uninstall_one(target: Path) -> None:
    if not target.exists():
        _w(f"{target} 不存在,无需卸载")
        return
    text = target.read_text(encoding="utf-8")
    before, existing, after = _split(text)
    if not existing:
        _w(f"{target} 中未找到 lm-mem 段落")
        return
    new_text = (before.rstrip("\n") + "\n" + after.lstrip("\n")).strip("\n")
    target.write_text(new_text + "\n" if new_text else "", encoding="utf-8")
    _w(f"已从 {target} 移除 lm-mem 触发段落")


def _status_one(target: Path) -> None:
    if not target.exists():
        _w(f"{target}:不存在(未安装)")
        return
    _, existing, _ = _split(target.read_text(encoding="utf-8"))
    if not existing:
        _w(f"{target}:未安装")
    elif existing == _block():
        _w(f"{target}:已安装且为最新")
    else:
        _w(f"{target}:已安装,但与当前版本不一致(可重新 install 同步)")


def _select(platforms) -> tuple[list[Agent], bool]:
    """选出要操作的 agent,返回 (列表, 是否自动检测出来的)。

    platforms 为空 → 按配置目录自动检测(原行为)。
    显式给了 --platform → 只取这些,且**显式意图优先于检测**:即使配置目录还不
    存在也照写(可能是先配规则再装 agent),只是会提示一下新建了目录。
    """
    if not platforms:
        return _detect(), True
    by_key = {a.key: a for a in _agents()}
    # 去重但保持用户给出的顺序
    return [by_key[p] for p in dict.fromkeys(platforms) if p in by_key], False


def _each(fn, platforms=()) -> None:
    chosen, auto = _select(platforms)
    if not chosen:
        if auto:
            _w("未检测到任何已知 agent(" + "/".join(PLATFORMS) + "),跳过")
        return
    _w(("检测到:" if auto else "指定:") + "、".join(a.label for a in chosen))
    for a in chosen:
        if not auto and not a.config_dir.is_dir():
            _w(f"  注意:{a.config_dir} 不存在,将按你指定的 platform 新建")
        fn(a.target)


def install(platforms=()) -> None:
    _each(_install_one, platforms)


def uninstall(platforms=()) -> None:
    _each(_uninstall_one, platforms)


def status(platforms=()) -> None:
    _each(_status_one, platforms)
