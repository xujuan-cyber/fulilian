"""cards-sync 三步流程测试：生成候选文件 → 人工编辑确认 → --apply 回灌。

覆盖：
- 生成模式：verified 门槛复用（详见 test_solve_experience_record.py）、
  id 稳定性（同数据重跑生成 id 不变）、摘要不刷屏
- apply 模式：合并进卡 +「实战经验沉淀」标题创建、technique 去重 skipped、
  删块 = 放弃、残缺块容错（不配对 / 缺元数据）、知识卡缺失 skipped
- 消费语义：apply 后候选文件重置为仅含标题与说明

所有测试通过 tmp_path + monkeypatch 覆盖 el.LEARNING_FILE / el.TRACES_DIR
与 knowledge.SKILLS_DIR，绝不读写真实的 ~/.fulilian/learning.json 与
skills/ctf-knowledge 卡。
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import fulilian_ctf.cli as cli
import fulilian_ctf.experiential_learning as el
import fulilian_ctf.knowledge as knowledge


# ── Fixture ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """学习文件 / 轨迹目录 / 知识卡目录全部指向 tmp，绝不触碰真实数据。"""
    monkeypatch.setattr(el, "LEARNING_FILE", tmp_path / "learning.json")
    monkeypatch.setattr(el, "TRACES_DIR", tmp_path / "traces")
    skills_dir = tmp_path / "skills" / "ctf-knowledge"
    skills_dir.mkdir(parents=True)
    monkeypatch.setattr(knowledge, "SKILLS_DIR", skills_dir)
    yield skills_dir


def _make_args(out: Path, apply: bool = False) -> SimpleNamespace:
    return SimpleNamespace(apply=apply, out=str(out))


def _gen(out: Path, capsys) -> str:
    """跑一次生成模式，返回 stdout 摘要。"""
    cli._knowledge_cards_sync(_make_args(out))
    return capsys.readouterr().out


def _apply(out: Path, capsys) -> str:
    """跑一次 apply 模式，返回 stdout 报告。"""
    cli._knowledge_cards_sync(_make_args(out, apply=True))
    return capsys.readouterr().out


def _write_card(skills_dir: Path, name: str = "web.md", content: str = "") -> Path:
    card = skills_dir / name
    card.write_text(content, encoding="utf-8")
    return card


# 候选块开标记（id=日期-序号）
_CAND_OPEN_RE = re.compile(r"<!-- candidate id=(?P<id>\d{8}-\d+) ")


# ── 1. 生成模式 ──────────────────────────────────────────────────────────


class TestGenerateMode:
    def test_generates_candidate_file_with_block_structure(self, tmp_path, capsys):
        el.record_lesson("web-01", "web", "SQL注入绕过WAF", success=True,
                         command="sqlmap -u 'http://target?id=1'",
                         verified=True)
        el.record_lesson("web-02", "web", "SQL注入绕过WAF", success=True,
                         command="sqlmap -u 'http://target?id=1'",
                         verified=True)
        out = tmp_path / "cand.md"
        summary = _gen(out, capsys)

        text = out.read_text(encoding="utf-8")
        # 顶部固定标题 + 使用说明
        assert text.startswith("# CTF 知识卡候选")
        assert "--apply" in text and "删掉" in text
        # 候选块：自包含结构
        m = _CAND_OPEN_RE.search(text)
        assert m, "应有 id=日期-序号 形式的候选块开标记"
        assert "### [web] SQL注入绕过WAF" in text
        assert "- 目标卡: skills/ctf-knowledge/web.md" in text
        assert "成功 2 / 失败 0（含 verified 通过）" in text
        assert "来源: web-01, web-02" in text
        assert "SQL注入绕过WAF（关键命令: sqlmap" in text
        assert "<!-- /candidate -->" in text
        # stdout 只打摘要，不刷全部候选
        assert "candidate technique(s)" in summary
        assert str(out) in summary
        assert "### [web]" not in summary

    def test_command_missing_writes_technique_only(self, tmp_path, capsys):
        """entry 无 command 时拟写入要点只含 technique。"""
        el.record_lesson("misc-01", "misc", "纯失败教训", success=False)
        el.record_lesson("misc-02", "misc", "纯失败教训", success=False)
        out = tmp_path / "cand.md"
        _gen(out, capsys)
        text = out.read_text(encoding="utf-8")
        assert "### [misc] 纯失败教训" in text
        assert "（关键命令:" not in text

    def test_id_stable_across_regenerations(self, tmp_path, capsys):
        """同数据重跑生成（全量重建）id 保持稳定。"""
        el.record_lesson("web-01", "web", "技巧A", success=True, verified=True)
        el.record_lesson("web-02", "web", "技巧A", success=True, verified=True)
        el.record_lesson("pwn-01", "pwn", "技巧B", success=False)
        el.record_lesson("pwn-02", "pwn", "技巧B", success=False)
        out = tmp_path / "cand.md"
        _gen(out, capsys)
        ids_first = _CAND_OPEN_RE.findall(out.read_text(encoding="utf-8"))
        _gen(out, capsys)
        ids_second = _CAND_OPEN_RE.findall(out.read_text(encoding="utf-8"))
        assert ids_first == ids_second
        assert len(set(ids_first)) == len(ids_first), "id 不应重复"

    def test_empty_learning_json_writes_nothing(self, tmp_path, capsys):
        el.save_learnings({"entries": [], "index": {}})
        out = tmp_path / "cand.md"
        summary = _gen(out, capsys)
        assert not out.exists()
        assert "暂无可同步的技巧" in summary


# ── 2. apply 模式 ────────────────────────────────────────────────────────


class TestApplyMode:
    def test_apply_merges_into_card_and_creates_section(
        self, tmp_path, capsys, _isolated_env,
    ):
        """目标卡无「实战经验沉淀」标题时自动创建，条目追加在该标题下。"""
        card = _write_card(_isolated_env, "web.md", "# Web 知识卡\n\n一些旧内容\n")
        el.record_lesson("web-01", "web", "SQL注入绕过WAF", success=True,
                         command="sqlmap -u 'http://target?id=1'",
                         verified=True)
        el.record_lesson("web-02", "web", "SQL注入绕过WAF", success=True,
                         command="sqlmap -u 'http://target?id=1'",
                         verified=True)
        out = tmp_path / "cand.md"
        _gen(out, capsys)
        report = _apply(out, capsys)

        card_text = card.read_text(encoding="utf-8")
        assert "## 实战经验沉淀" in card_text
        # 条目行 = 拟写入要点 + 来源题 id
        assert ("- SQL注入绕过WAF（关键命令: sqlmap -u 'http://target?id=1'）"
                "（来源: web-01, web-02）") in card_text
        # 标题在文件中位于条目之前
        assert card_text.index("## 实战经验沉淀") < card_text.index("- SQL注入绕过WAF")
        assert "applied=1" in report

    def test_apply_dedupes_against_existing_technique(
        self, tmp_path, capsys, _isolated_env,
    ):
        """目标卡已含相同 technique 文本 → skipped，卡片不重复追加。"""
        card = _write_card(
            _isolated_env, "web.md",
            "# Web\n\n## 实战经验沉淀\n\n- SQL注入绕过WAF（旧条目）\n",
        )
        el.record_lesson("web-01", "web", "SQL注入绕过WAF", success=True,
                         verified=True)
        el.record_lesson("web-02", "web", "SQL注入绕过WAF", success=True,
                         verified=True)
        out = tmp_path / "cand.md"
        _gen(out, capsys)
        report = _apply(out, capsys)

        assert "skipped=1" in report and "已含相同技巧" in report
        card_text = card.read_text(encoding="utf-8")
        assert card_text.count("SQL注入绕过WAF") == 1, "不应重复追加"

    def test_deleted_block_is_abandoned(self, tmp_path, capsys, _isolated_env):
        """用户删掉的候选块 = 放弃，静默跳过不回灌。"""
        card = _write_card(_isolated_env, "web.md", "# Web\n")
        el.record_lesson("web-01", "web", "想要的技巧", success=True,
                         verified=True)
        el.record_lesson("web-02", "web", "想要的技巧", success=True,
                         verified=True)
        el.record_lesson("web-01", "web", "不要的技巧", success=True,
                         verified=True)
        el.record_lesson("web-02", "web", "不要的技巧", success=True,
                         verified=True)
        out = tmp_path / "cand.md"
        _gen(out, capsys)

        # 人工编辑：删掉「不要的技巧」所在块
        text = out.read_text(encoding="utf-8")
        blocks = re.findall(
            r"<!-- candidate .*?<!-- /candidate -->", text, re.DOTALL,
        )
        kept = [b for b in blocks if "不要的技巧" not in b]
        assert len(kept) == len(blocks) - 1
        out.write_text(
            cli._CARDS_SYNC_HEADER + "\n" + "\n\n".join(kept) + "\n",
            encoding="utf-8",
        )

        report = _apply(out, capsys)
        card_text = card.read_text(encoding="utf-8")
        assert "想要的技巧" in card_text
        assert "不要的技巧" not in card_text
        assert "applied=1" in report
        # 消费语义：文件被重置为仅含标题与说明
        assert out.read_text(encoding="utf-8") == cli._CARDS_SYNC_HEADER

    def test_malformed_blocks_are_skipped_with_warning(
        self, tmp_path, capsys, _isolated_env,
    ):
        """标记不配对 / 缺元数据的残缺块：跳过并告警，绝不抛异常。"""
        card = _write_card(_isolated_env, "web.md", "")
        out = tmp_path / "cand.md"
        out.write_text(
            cli._CARDS_SYNC_HEADER
            + "\n"
            # 残缺块 1：缺少闭标记
            + '<!-- candidate id=20990101-1 category="web" technique="孤儿块" -->\n'
            "### [web] 孤儿块\n"
            + "\n"
            # 残缺块 2：缺 technique 元数据
            + '<!-- candidate id=20990101-2 category="web" -->\n'
            "### [web] 没有元数据的块\n"
            "<!-- /candidate -->\n"
            # 完整块：应正常回灌
            + '<!-- candidate id=20990101-3 category="web" '
            'technique="完整技巧" sources="web-01" -->\n'
            "### [web] 完整技巧\n"
            "- 拟写入:\n  - 完整技巧\n"
            "<!-- /candidate -->\n",
            encoding="utf-8",
        )
        report = _apply(out, capsys)  # 不抛异常即通过容错要求

        assert "警告" in report
        assert "孤儿块" in report
        assert "applied=1" in report
        assert "skipped=2" in report
        card_text = card.read_text(encoding="utf-8")
        assert "完整技巧" in card_text
        assert "孤儿块" not in card_text
        assert "没有元数据的块" not in card_text
        # 残缺文件也被消费重置
        assert out.read_text(encoding="utf-8") == cli._CARDS_SYNC_HEADER

    def test_missing_card_reports_skipped_and_does_not_create(
        self, tmp_path, capsys, _isolated_env,
    ):
        """SKILLS_DIR 下无该分类卡：报 skipped 并说明，不自动建卡。"""
        el.record_lesson("crypto-01", "crypto", "RSA低指数攻击", success=True,
                         verified=True)
        el.record_lesson("crypto-02", "crypto", "RSA低指数攻击", success=True,
                         verified=True)
        out = tmp_path / "cand.md"
        _gen(out, capsys)
        report = _apply(out, capsys)

        assert "skipped=1" in report and "知识卡缺失" in report
        assert not (_isolated_env / "crypto.md").exists(), "不应自动建卡"

    def test_apply_without_candidate_file(self, tmp_path, capsys):
        out = tmp_path / "not-exists.md"
        report = _apply(out, capsys)
        assert "候选文件不存在" in report

    def test_user_edited_bullet_is_respected(
        self, tmp_path, capsys, _isolated_env,
    ):
        """人工改写「拟写入」要点后，回灌的是编辑后的文本。"""
        card = _write_card(_isolated_env, "web.md", "# Web\n")
        el.record_lesson("web-01", "web", "原始技巧名", success=True,
                         verified=True)
        el.record_lesson("web-02", "web", "原始技巧名", success=True,
                         verified=True)
        out = tmp_path / "cand.md"
        _gen(out, capsys)
        text = out.read_text(encoding="utf-8")
        out.write_text(
            text.replace("  - 原始技巧名", "  - 人工润色后的要点"),
            encoding="utf-8",
        )
        _apply(out, capsys)
        card_text = card.read_text(encoding="utf-8")
        assert "人工润色后的要点" in card_text
        assert "- 原始技巧名" not in card_text
