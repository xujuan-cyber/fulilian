"""Phase 0 配置口径契约测试（覆盖 4 个漂移点）。

背景：默认值在代码、文档、注释、用户可见提示里有四种说法，历史上已经漂移过
（文档写 3 / 2，代码是 10 / 1，schema 注释写 3，CLI tips 对用户说"up to 3"）。
本测试把四处**全部**钉到 ``tools/delegate_tool.py`` 的常量上：

| 来源 | 内容 | 期望 |
|---|---|---|
| ``AGENTS.md`` | ``max_concurrent_children (default N)`` | == ``_DEFAULT_MAX_CONCURRENT_CHILDREN`` |
| ``AGENTS.md`` | ``max_spawn_depth (default N)`` | == ``MAX_DEPTH`` |
| ``tools/delegate_tool.py`` | schema 注释 ``max_concurrent_children (default N)`` | == ``_DEFAULT_MAX_CONCURRENT_CHILDREN`` |
| ``fulilian_cli/tips.py`` | 用户提示 ``spawns up to N concurrent sub-agents`` | == ``_DEFAULT_MAX_CONCURRENT_CHILDREN`` |

设计要点：
- 值是从各文件**正文正则解析**出来的，不是从常量回填的；每个解析器都配一条
  反向自检（喂一个被改坏的样本，断言解析结果跟着变），否则这组断言就是自证。
- 除常量外，还断言运行期解析函数（``_get_max_concurrent_children`` /
  ``_get_max_spawn_depth``）在无配置时返回同一个数，堵住"常量对了但取值
  路径另写默认值"的二次漂移。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools import delegate_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD_PATH = REPO_ROOT / "AGENTS.md"
DELEGATE_TOOL_PATH = REPO_ROOT / "tools" / "delegate_tool.py"
TIPS_PATH = REPO_ROOT / "fulilian_cli" / "tips.py"
CONTRACTS_PATH = REPO_ROOT / "agent" / "orchestration" / "contracts.py"

# AGENTS.md："`delegation.max_concurrent_children` (default 10)."
_AGENTS_CONCURRENT_RE = re.compile(r"max_concurrent_children`\s*\(default\s+(\d+)\)")
_AGENTS_SPAWN_DEPTH_RE = re.compile(r"max_spawn_depth`\s*\(default\s+(\d+)\)")
# delegate_tool.py schema 注释："# delegation.max_concurrent_children (default 10) and"
_DELEGATE_CONCURRENT_RE = re.compile(r"max_concurrent_children \(default (\d+)\)")
# tips.py："delegate_task spawns up to 10 concurrent sub-agents by default"
_TIPS_CONCURRENT_RE = re.compile(r"spawns up to (\d+) concurrent sub-agents")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse(text: str, pattern: re.Pattern[str], label: str) -> int:
    """取出唯一一处默认值声明。

    要求恰好命中一次：0 次说明措辞变了/被删了，多次说明自相矛盾——两者都应
    让契约测试失败，而不是随便挑一个。
    """
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise AssertionError(
            f"{label} 的默认值声明应恰好出现 1 次，实际 {len(matches)} 次。"
            f" 匹配模式：{pattern.pattern!r}"
        )
    return int(matches[0])


def _agents_concurrent() -> int:
    return _parse(_read(AGENTS_MD_PATH), _AGENTS_CONCURRENT_RE, "AGENTS.md/max_concurrent_children")


def _agents_spawn_depth() -> int:
    return _parse(_read(AGENTS_MD_PATH), _AGENTS_SPAWN_DEPTH_RE, "AGENTS.md/max_spawn_depth")


def _delegate_schema_comment() -> int:
    return _parse(
        _read(DELEGATE_TOOL_PATH),
        _DELEGATE_CONCURRENT_RE,
        "delegate_tool.py/max_concurrent_children",
    )


def _tips_concurrent() -> int:
    return _parse(_read(TIPS_PATH), _TIPS_CONCURRENT_RE, "tips.py/up to N concurrent")


# ── 来源存在性 / 可解析性 ────────────────────────────────────────────────────


def test_all_drift_sources_exist() -> None:
    assert AGENTS_MD_PATH.is_file()
    assert DELEGATE_TOOL_PATH.is_file()
    assert TIPS_PATH.is_file()


def test_every_source_declares_a_positive_default() -> None:
    assert _agents_concurrent() > 0
    assert _agents_spawn_depth() >= 0
    assert _delegate_schema_comment() > 0
    assert _tips_concurrent() > 0


# ── 四个漂移点 == 代码常量 ──────────────────────────────────────────────────


def test_agents_md_concurrent_default_matches_code_constant() -> None:
    documented = _agents_concurrent()
    assert documented == delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN, (
        "AGENTS.md 写的 max_concurrent_children 默认值与 "
        "delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN 不一致："
        f"文档 {documented} != 代码 {delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN}"
    )


def test_agents_md_spawn_depth_matches_code_constant() -> None:
    documented = _agents_spawn_depth()
    assert documented == delegate_tool.MAX_DEPTH, (
        "AGENTS.md 写的 max_spawn_depth 默认值与 delegate_tool.MAX_DEPTH 不一致："
        f"文档 {documented} != 代码 {delegate_tool.MAX_DEPTH}"
    )


def test_delegate_tool_schema_comment_matches_code_constant() -> None:
    documented = _delegate_schema_comment()
    assert documented == delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN, (
        "delegate_tool.py 的 schema 注释与常量不一致："
        f"注释 {documented} != 代码 {delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN}"
    )


def test_tips_text_matches_code_constant() -> None:
    documented = _tips_concurrent()
    assert documented == delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN, (
        "fulilian_cli/tips.py 给用户的提示与常量不一致："
        f"提示 {documented} != 代码 {delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN}"
    )


def test_all_four_sources_agree() -> None:
    values = {
        "AGENTS.md/max_concurrent_children": _agents_concurrent(),
        "delegate_tool.py/schema_comment": _delegate_schema_comment(),
        "tips.py/up_to_n": _tips_concurrent(),
        "delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN": (
            delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN
        ),
    }
    assert len(set(values.values())) == 1, f"四处口径不一致：{values}"


# ── 文档 == 运行期解析结果（无配置时的默认路径） ─────────────────────────────


def test_runtime_default_concurrent_children_matches_doc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: {})
    monkeypatch.delenv("DELEGATION_MAX_CONCURRENT_CHILDREN", raising=False)
    assert delegate_tool._get_max_concurrent_children() == _agents_concurrent()


def test_runtime_default_spawn_depth_matches_doc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: {})
    assert delegate_tool._get_max_spawn_depth() == _agents_spawn_depth()


# ── 代码内注释口径（第三、第四处说法） ───────────────────────────────────────


def test_delegate_tool_comment_uses_single_depth_default() -> None:
    source = _read(DELEGATE_TOOL_PATH)
    assert "default 1, matching MAX_DEPTH." in source
    assert "default 2 for parity with the original MAX_DEPTH constant." not in source


def test_contracts_terminal_states_comment_does_not_claim_no_outgoing_edges() -> None:
    """评审 H5 / M6：``FAILED``/``INTERRUPTED`` 仍可开新 attempt。

    ``TERMINAL_STATES`` 的语义是"本次执行已终结"，**不是**"状态图无出边"。
    这条注释曾写成"终态：进入后不再有出边"，与重试/恢复路径直接冲突；
    这里把两件事钉死：旧说法不许回退，新说法必须在。
    """
    source = _read(CONTRACTS_PATH)
    assert "进入后不再有出边" not in source, (
        "contracts.py 的 TERMINAL_STATES 注释又把'本次执行终结'写成了'无出边'；"
        "FAILED->QUEUED（重试）与 INTERRUPTED->QUEUED（恢复）会因此被误判为非法。"
    )
    assert "终结 ≠ 状态图无出边" in source


# ── 反向验证：解析器确实在读文件，而不是复述常量 ────────────────────────────


def test_parser_reports_drifted_agents_md() -> None:
    drifted = (
        "- **Batch (parallel):** Concurrency is capped by\n"
        "  `delegation.max_concurrent_children` (default 3).\n"
        '- `role="orchestrator"` — bounded by `delegation.max_spawn_depth` (default 2).\n'
    )
    assert _parse(drifted, _AGENTS_CONCURRENT_RE, "x") == 3
    assert _parse(drifted, _AGENTS_SPAWN_DEPTH_RE, "y") == 2
    assert _parse(drifted, _AGENTS_CONCURRENT_RE, "x") != (
        delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN
    )
    assert _parse(drifted, _AGENTS_SPAWN_DEPTH_RE, "y") != delegate_tool.MAX_DEPTH


def test_parser_reports_drifted_schema_comment() -> None:
    drifted = "# delegation.max_concurrent_children (default 3) and\n"
    assert _parse(drifted, _DELEGATE_CONCURRENT_RE, "x") == 3
    assert _parse(drifted, _DELEGATE_CONCURRENT_RE, "x") != (
        delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN
    )


def test_parser_reports_drifted_tips_text() -> None:
    drifted = (
        '    "delegate_task spawns up to 3 concurrent sub-agents by default '
        '(delegation.max_concurrent_children) ...",\n'
    )
    assert _parse(drifted, _TIPS_CONCURRENT_RE, "x") == 3
    assert _parse(drifted, _TIPS_CONCURRENT_RE, "x") != (
        delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN
    )


def test_parser_rejects_missing_declaration() -> None:
    with pytest.raises(AssertionError, match="恰好出现 1 次"):
        _parse("no knobs here", _AGENTS_CONCURRENT_RE, "AGENTS.md/max_concurrent_children")


def test_parser_rejects_ambiguous_declaration() -> None:
    ambiguous = (
        "`delegation.max_concurrent_children` (default 10).\n"
        "`delegation.max_concurrent_children` (default 3).\n"
    )
    with pytest.raises(AssertionError, match="恰好出现 1 次"):
        _parse(ambiguous, _AGENTS_CONCURRENT_RE, "AGENTS.md/max_concurrent_children")


# ── 常量自身的类型 ──────────────────────────────────────────────────────────


def test_code_constants_are_positive_ints() -> None:
    assert isinstance(delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN, int)
    assert isinstance(delegate_tool.MAX_DEPTH, int)
    assert delegate_tool._DEFAULT_MAX_CONCURRENT_CHILDREN >= 1
    assert delegate_tool.MAX_DEPTH >= 1
