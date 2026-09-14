"""单题 solve 路径经验落库接线 + cards-sync verified 门槛测试（P1-4）。

覆盖：
- cli._record_single_solve_experience：黑板 fact 提取、flag 检测链
  （read_flag_file → check_output_for_flag）、category 兜底、异常静默
- handle_solve_command 两个分支（oneshot / 交互式）在退出前调用落库，
  且落库失败不改变退出码
- _knowledge_cards_sync：基于「成功」入选的 technique 须有 verified=True
  的 entry 支撑；旧数据（无 verified 字段）按 False；纯失败不受限

所有测试通过 tmp_path + monkeypatch 覆盖 el.LEARNING_FILE / el.TRACES_DIR，
不读写真实的 ~/.fulilian/learning.json 与 traces 目录。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import fulilian_ctf.cli as cli
import fulilian_ctf.experiential_learning as el
from fulilian_ctf.blackboard import (
    BLACKBOARD_FILENAME,
    Blackboard,
    Fact,
    State,
    save_blackboard,
)


@pytest.fixture(autouse=True)
def _isolated_learning_env(tmp_path, monkeypatch):
    """每个测试使用独立 tmp 学习文件与轨迹目录，绝不触碰真实数据。"""
    monkeypatch.setattr(el, "LEARNING_FILE", tmp_path / "learning.json")
    monkeypatch.setattr(el, "TRACES_DIR", tmp_path / "traces")
    yield


def _make_work_dir(tmp_path: Path, with_flag: bool = True) -> Path:
    """构造含黑板 + FLAG 文件的题目工作目录。"""
    work_dir = tmp_path / "web-01"
    work_dir.mkdir()
    board = Blackboard(challenge_id="web-01")
    board.add_fact(Fact(id="f1", content="nmap scan found port 80 open",
                        state=State.CONFIRMED))
    board.add_fact(Fact(id="f2", content="admin panel uses default creds",
                        state=State.CONFIRMED))
    board.add_fact(Fact(id="f3", content="union injection blocked by WAF",
                        state=State.REFUTED))
    board.add_fact(Fact(id="f4", content="dir /backup maybe exists",
                        state=State.OPEN))  # OPEN fact 不提取
    save_blackboard(board, work_dir / BLACKBOARD_FILENAME)
    if with_flag:
        (work_dir / "FLAG").write_text("flag{abc123}\n", encoding="utf-8")
    return work_dir


def _make_project(challenge_id: str = "web-01", category: str = ""):
    return SimpleNamespace(
        challenge_id=challenge_id, category=category, challenge_dir="",
        flag="",
    )


# ── 1. 落库辅助函数 ──────────────────────────────────────────────────────


class TestRecordSingleSolveExperience:
    def test_records_flag_and_blackboard_facts(self, tmp_path):
        work_dir = _make_work_dir(tmp_path)
        cli._record_single_solve_experience(_make_project(), work_dir)

        entries = el.load_learnings()["entries"]
        assert entries, "解出 flag 后应有经验落库"
        # flag 检测链命中 → success + verified 均为 True
        assert all(e["success"] is True for e in entries)
        assert all(e["verified"] is True for e in entries)
        # 只提取 CONFIRMED/REFUTED fact，OPEN fact 不入库
        techniques = {e["technique"] for e in entries}
        assert "nmap scan found port 80 open" in techniques
        assert "union injection blocked by WAF" in techniques
        assert not any("maybe exists" in t for t in techniques)

    def test_category_fallback_from_id(self, tmp_path):
        """project.category 为空时用 _guess_category_from_id 兜底。"""
        work_dir = _make_work_dir(tmp_path)
        cli._record_single_solve_experience(_make_project(), work_dir)
        entries = el.load_learnings()["entries"]
        assert entries and all(e["category"] == "web" for e in entries)

    def test_no_flag_records_failure_unverified(self, tmp_path):
        """没解出时落负知识，verified=False。"""
        work_dir = _make_work_dir(tmp_path, with_flag=False)
        cli._record_single_solve_experience(_make_project(), work_dir)
        entries = el.load_learnings()["entries"]
        assert entries
        assert all(e["success"] is False for e in entries)
        assert all(e["verified"] is False for e in entries)

    def test_swallows_exceptions_silently(self, tmp_path, monkeypatch):
        """落库链路抛异常时静默吞掉，不影响调用方（退出码不变的前提）。"""

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(el, "record_solve_outcome", _boom)
        work_dir = _make_work_dir(tmp_path)
        # 不抛出即通过
        cli._record_single_solve_experience(_make_project(), work_dir)
        assert el.load_learnings()["entries"] == []

    def test_missing_work_dir_does_not_raise(self, tmp_path):
        """work_dir 为 None（清单文件形态）时静默跳过黑板/flag 检测。"""
        monkeypatch_chdir = tmp_path / "empty"
        monkeypatch_chdir.mkdir()
        import os

        old = os.getcwd()
        os.chdir(monkeypatch_chdir)
        try:
            cli._record_single_solve_experience(_make_project(), None)
        finally:
            os.chdir(old)
        # 空目录无 flag → 落失败负知识（或无黑板则 key_commands 为空）
        entries = el.load_learnings()["entries"]
        assert all(e["success"] is False for e in entries)


# ── 2. handle_solve_command 接线 ─────────────────────────────────────────


def _fake_run_agent_module(monkeypatch):
    fake = types.ModuleType("run_agent")
    fake.main = lambda **kwargs: 0
    monkeypatch.setitem(sys.modules, "run_agent", fake)
    return fake


def _patch_solve_commons(monkeypatch, tmp_path, recorder):
    """把 solve 命令的外围依赖全部 mock 成最小闭环。"""
    work_dir = tmp_path / "web-01"
    work_dir.mkdir(exist_ok=True)  # 交互式分支会 chdir 进该目录
    project = SimpleNamespace(
        challenge_id="web-01", category="web",
        challenge_dir=str(work_dir), flag="",
    )
    monkeypatch.setattr(cli, "_validate_solve_target",
                        lambda cid: str(work_dir))
    monkeypatch.setattr(cli, "_resolve_project", lambda cid: project)
    monkeypatch.setattr(cli, "_prepare_work_dir",
                        lambda p, cid: work_dir)
    monkeypatch.setattr(cli, "_record_single_solve_experience", recorder)
    # 知识注入 mock 掉，避免读真实知识库 / learning.json
    # （真实签名：inject_ctf_context(category, prompt, query=None)）
    import fulilian_ctf.knowledge as knowledge

    monkeypatch.setattr(knowledge, "inject_ctf_context",
                        lambda category, system_prompt, query=None: system_prompt)
    return project, work_dir


def _make_args(**overrides) -> SimpleNamespace:
    base = dict(
        id="web-01", rpc=False, race=False, boomerang=False,
        multi_agent=False, model="test-model", oneshot=False, json=False,
        architect_model="", executor_model="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestSolveCommandWiring:
    def test_interactive_branch_records_before_exit(self, tmp_path, monkeypatch):
        recorder = _RecordingMock()
        _patch_solve_commons(monkeypatch, tmp_path, recorder)
        _fake_run_agent_module(monkeypatch)

        with pytest.raises(SystemExit) as excinfo:
            cli.handle_solve_command(_make_args())

        assert excinfo.value.code == 0
        assert recorder.calls, "交互式 solve 退出前应调用经验落库"
        project_arg, work_dir_arg = recorder.calls[0]
        assert project_arg.challenge_id == "web-01"
        assert work_dir_arg == tmp_path / "web-01"

    def test_oneshot_branch_records_before_exit(self, tmp_path, monkeypatch):
        recorder = _RecordingMock()
        project, work_dir = _patch_solve_commons(monkeypatch, tmp_path, recorder)
        monkeypatch.setattr(
            cli, "_run_solve_once",
            lambda *a, **k: 1,  # 模拟失败退出码
        )

        with pytest.raises(SystemExit) as excinfo:
            cli.handle_solve_command(_make_args(oneshot=True))

        assert excinfo.value.code == 1
        assert recorder.calls, "oneshot solve 退出前应调用经验落库"
        project_arg, work_dir_arg = recorder.calls[0]
        assert project_arg is project
        assert work_dir_arg == work_dir

    def test_recorder_exception_does_not_change_exit_code(
        self, tmp_path, monkeypatch,
    ):
        """落库辅助函数内部异常被吞掉，退出码保持 solve 本身的结果。"""
        recorder = _RecordingMock(raise_on_call=RuntimeError("boom"))
        _patch_solve_commons(monkeypatch, tmp_path, recorder)
        _fake_run_agent_module(monkeypatch)

        with pytest.raises(SystemExit) as excinfo:
            cli.handle_solve_command(_make_args())

        # 交互式分支 solve 本身 exit 0；落库函数异常被内部吞掉不改变退出码
        assert excinfo.value.code == 0


class _RecordingMock:
    """记录调用参数的可选抛异常 stub（避免对 mock 库的依赖假设）。"""

    def __init__(self, raise_on_call: Exception | None = None):
        self.calls: list[tuple] = []
        self._raise = raise_on_call

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        if self._raise is not None:
            raise self._raise
        return None


# ── 3. cards-sync verified 门槛 ──────────────────────────────────────────


class TestCardsSyncVerifiedGate:
    """cards-sync 生成模式的 verified 门槛（行为：写候选文件而非打印 stdout）。"""

    def _invoke(self, tmp_path: Path, capsys) -> Path:
        out_file = tmp_path / "candidates.md"
        cli._knowledge_cards_sync(SimpleNamespace(apply=False, out=str(out_file)))
        capsys.readouterr()  # 摘要打到 stdout，不作为断言载体
        return out_file

    def test_success_without_verified_is_filtered(self, tmp_path, capsys):
        """高成功率但无 verified=True entry 的技巧不入候选文件。"""
        el.record_lesson("web-01", "web", "未验证技巧", success=True)
        el.record_lesson("web-02", "web", "已验证技巧", success=True,
                         verified=True)
        text = self._invoke(tmp_path, capsys).read_text(encoding="utf-8")
        assert "已验证技巧" in text
        assert "未验证技巧" not in text

    def test_pure_failure_not_restricted(self, tmp_path, capsys):
        """纯失败教训（success=0）不受 verified 门槛限制。"""
        el.record_lesson("web-01", "web", "纯失败教训", success=False)
        el.record_lesson("web-02", "web", "纯失败教训", success=False)
        text = self._invoke(tmp_path, capsys).read_text(encoding="utf-8")
        assert "纯失败教训" in text

    def test_legacy_entries_without_verified_field_treated_false(
        self, tmp_path, capsys,
    ):
        """索引/entries 无 verified 字段的旧数据按 False 处理。"""
        el.save_learnings({
            "entries": [{
                "challenge_id": "web-01", "category": "web",
                "technique": "旧技巧", "success": True,
                "timestamp": "2026-01-01T00:00:00",
            }],
            "index": {"web::旧技巧": {"success": 1, "fail": 0}},
        })
        text = self._invoke(tmp_path, capsys).read_text(encoding="utf-8")
        assert "旧技巧" not in text

    def test_mixed_entries_need_at_least_one_verified(self, tmp_path, capsys):
        """同技巧多条 entry 中只要有任一条 verified=True 即可入选。"""
        el.record_lesson("web-01", "web", "混合技巧", success=True)
        el.record_lesson("web-02", "web", "混合技巧", success=True,
                         verified=True)
        text = self._invoke(tmp_path, capsys).read_text(encoding="utf-8")
        assert "混合技巧" in text
