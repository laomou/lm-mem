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


# ── --platform 选择(默认仍是"全部检测到的") ─────────────


def test_platforms_constant_matches_registry(si):
    """PLATFORMS 与 _agents() 的 key 必须一一对应,别漂移。

    argparse 用 PLATFORMS 做 choices,注册表加了 agent 却忘了加进 PLATFORMS,
    那个 agent 就永远选不中 —— 而且不会报错。
    """
    mod, _ = si
    assert tuple(a.key for a in mod._agents()) == mod.PLATFORMS


def test_no_platform_still_writes_all_detected(si):
    """不传 --platform 时行为与从前一致(全部已检测到的)。"""
    mod, home = si
    _mk(home, ".claude", ".codex")
    mod.install()
    written = {p.relative_to(home).as_posix() for p in home.rglob("*.md")}
    assert written == {".claude/CLAUDE.md", ".codex/AGENTS.md"}


def test_platform_selects_single_agent(si):
    mod, home = si
    _mk(home, ".claude", ".codex", ".openclaw")
    mod.install(("claude",))
    written = {p.relative_to(home).as_posix() for p in home.rglob("*.md")}
    assert written == {".claude/CLAUDE.md"}, "只该写 Claude 那一份"


def test_platform_is_repeatable_and_deduped(si):
    mod, home = si
    _mk(home, ".claude", ".codex", ".openclaw")
    mod.install(("codex", "openclaw", "codex"))     # 重复的 codex 只算一次
    written = {p.relative_to(home).as_posix() for p in home.rglob("*.md")}
    assert written == {".codex/AGENTS.md", ".openclaw/AGENTS.md"}


def test_explicit_platform_writes_even_if_undetected(si):
    """显式指定的 platform 优先于自动检测:配置目录不存在也照写。

    场景:先把规则配好,之后再装那个 agent。
    """
    mod, home = si
    assert not (home / ".codex").exists()
    mod.install(("codex",))
    assert (home / ".codex" / "AGENTS.md").exists()
    assert mod.BEGIN in (home / ".codex" / "AGENTS.md").read_text()


def test_platform_scoped_uninstall_leaves_others(si):
    mod, home = si
    _mk(home, ".claude", ".codex")
    mod.install()
    mod.uninstall(("claude",))
    assert mod.BEGIN not in (home / ".claude" / "CLAUDE.md").read_text()
    assert mod.BEGIN in (home / ".codex" / "AGENTS.md").read_text(), "不该动 Codex"


def test_platform_scoped_status_only_reports_that_one(si, capsys):
    mod, home = si
    _mk(home, ".claude", ".codex")
    mod.install()
    capsys.readouterr()
    mod.status(("codex",))
    err = capsys.readouterr().err
    assert "AGENTS.md" in err and "CLAUDE.md" not in err
