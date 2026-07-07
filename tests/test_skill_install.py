"""`lm-mem skill install` —— 自动检测 agent 并幂等写入触发段落。

用 monkeypatch 把 HOME 指向临时目录,避免碰真实 ~/.claude 等。
"""
import importlib

import pytest


@pytest.fixture()
def si(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    import lm_mem.skill_install as _si
    return importlib.reload(_si), tmp_path


def _mk(root, *rel):
    for r in rel:
        (root / r).mkdir(parents=True, exist_ok=True)


def test_no_agent_detected_writes_nothing(si):
    mod, home = si
    mod.install()
    assert not list(home.rglob("*.md"))


def test_detects_and_writes_each_agent(si):
    mod, home = si
    _mk(home, ".claude", ".codex", ".config/opencode", ".openclaw")
    mod.install()
    written = {p.relative_to(home).as_posix() for p in home.rglob("*.md")}
    assert written == {
        ".claude/CLAUDE.md",
        ".codex/AGENTS.md",
        ".config/opencode/AGENTS.md",
        ".openclaw/AGENTS.md",
    }
    for p in home.rglob("*.md"):
        assert mod.BEGIN in p.read_text() and mod.END in p.read_text()


def test_install_is_idempotent(si):
    mod, home = si
    _mk(home, ".claude")
    mod.install()
    mod.install()
    text = (home / ".claude" / "CLAUDE.md").read_text()
    assert text.count(mod.BEGIN) == 1  # 未重复追加


def test_appends_to_existing_file(si):
    mod, home = si
    _mk(home, ".claude")
    target = home / ".claude" / "CLAUDE.md"
    target.write_text("# 我的规则\n\n某些已有内容\n")
    mod.install()
    text = target.read_text()
    assert "某些已有内容" in text and mod.BEGIN in text


def test_empty_file_has_no_leading_blank_lines(si):
    mod, home = si
    _mk(home, ".claude")
    target = home / ".claude" / "CLAUDE.md"
    target.write_text("\n\n")  # 空白文件不应留下前导空行
    mod.install()
    assert target.read_text().startswith(mod.BEGIN)


def test_uninstall_removes_block_keeps_rest(si):
    mod, home = si
    _mk(home, ".claude")
    target = home / ".claude" / "CLAUDE.md"
    target.write_text("# 我的规则\n\n某些已有内容\n")
    mod.install()
    mod.uninstall()
    text = target.read_text()
    assert mod.BEGIN not in text and "某些已有内容" in text
