"""``fulilian_ctf.challenge_resolve`` 挑战目标定位测试。

``resolve_challenge_target`` 是 ``fulilian solve`` 前置校验的数据层：判定
「Challenge ID 或目录」能否定位到工作目录，不可定位返回 None（由调用方在
启动 agent 前快速报错退出）。全程纯只读，不 mkdir、不触碰真实 ~/.fulilian
（FULILIAN_HOME 统一隔离到 tmp_path）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fulilian_ctf.challenge_resolve import (
    load_historical_trace,
    looks_like_path,
    resolve_challenge_target,
)


@pytest.fixture(autouse=True)
def _isolate_fulilian_home(tmp_path, monkeypatch):
    """历史轨迹读取走 FULILIAN_HOME——统一隔离到 tmp_path，绝不碰真实数据。

    load_historical_trace 在调用时才从 fulilian_constants 取 FULILIAN_HOME，
    patch 模块属性即可生效（与 test_solve_validation.py 同一手法）。
    """
    import fulilian_constants

    monkeypatch.setattr(fulilian_constants, "FULILIAN_HOME", tmp_path / "home")


# ── 可定位：返回将要使用的 work_dir ─────────────────────────────────────────


def test_existing_plain_directory_resolves(tmp_path):
    """存在的真实目录 → 解析成功，work_dir 就是目录本身。"""
    d = tmp_path / "chal-a"
    d.mkdir()
    assert Path(resolve_challenge_target(str(d))) == d


def test_existing_directory_with_challenge_json_resolves(tmp_path):
    """含 challenge.json 的题目目录 → 按条目 dir 解析出同一工作目录。"""
    d = tmp_path / "platform" / "chal-b"
    d.mkdir(parents=True)
    (d / "challenge.json").write_text(
        json.dumps({"id": "chal-b", "dir": "chal-b"}), encoding="utf-8"
    )
    assert Path(resolve_challenge_target(str(d))) == d


def test_manifest_file_resolves_to_entry_dir(tmp_path, monkeypatch):
    """平台清单文件（ctfd sync 产物的单题用法）→ 按条目 dir 解析 work_dir。

    单题解析（_resolve_project）不传 base_dir：条目的相对 dir 按进程 cwd
    展开，故这里先 chdir 到 tmp_path 对齐实际求解语义。
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "web-01").mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"challenges": [{"id": "web-01", "dir": "web-01"}]}),
        encoding="utf-8",
    )
    assert Path(resolve_challenge_target(str(manifest))) == tmp_path / "web-01"


def test_manifest_entry_without_dir_resolves_to_cwd(tmp_path, monkeypatch):
    """清单条目无独立 dir → 在 cwd 求解（与 _prepare_work_dir 的降级一致）。"""
    monkeypatch.chdir(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"challenges": [{"id": "ctfd-5"}]}), encoding="utf-8"
    )
    assert Path(resolve_challenge_target(str(manifest))) == Path.cwd()


def test_bare_id_resolves_to_prospective_work_dir(tmp_path, monkeypatch):
    """裸相对 id（web-01 形态）→ 既有机制在 cwd 下建同名工作目录，放行。

    同时验证校验本身无副作用：不提前 mkdir。
    """
    monkeypatch.chdir(tmp_path)
    prospective = tmp_path / "web-01"
    result = resolve_challenge_target("web-01")
    assert Path(result) == prospective
    assert not prospective.exists()


def test_bare_id_with_historical_trace_resolves(tmp_path, monkeypatch):
    """纯名字的历史挑战（FULILIAN_HOME/traces/<id>.json）→ 与 writeup/replay 同源放行。"""
    monkeypatch.chdir(tmp_path)
    traces = tmp_path / "home" / "traces"
    traces.mkdir(parents=True)
    (traces / "chal-01.json").write_text(
        json.dumps({"challenge_id": "chal-01", "key_commands": []}),
        encoding="utf-8",
    )
    assert load_historical_trace("chal-01") == {
        "challenge_id": "chal-01",
        "key_commands": [],
    }
    assert Path(resolve_challenge_target("chal-01")) == tmp_path / "chal-01"


def test_bare_manifest_style_id_passes_through(tmp_path, monkeypatch):
    """solve-all 风格的裸挑战 id（ctfd-5）同样按裸 id 机制放行（cwd/<id>）。"""
    monkeypatch.chdir(tmp_path)
    assert Path(resolve_challenge_target("ctfd-5")) == tmp_path / "ctfd-5"


# ── 不可定位：返回 None（调用方快速报错退出）────────────────────────────────


def test_missing_absolute_path_returns_none(tmp_path):
    """核心 bug 场景：不存在的绝对路径 → None，且绝不偷偷 mkdir。"""
    target = tmp_path / "definitely-not-exist"
    assert resolve_challenge_target(str(target)) is None
    assert not target.exists()


def test_missing_relative_path_returns_none(tmp_path, monkeypatch):
    """带分隔符的相对路径不存在 → None（否则会在 cwd 下 mkdir 空目录）。"""
    monkeypatch.chdir(tmp_path)
    assert resolve_challenge_target("chals/missing-chal") is None
    assert not (tmp_path / "chals").exists()


def test_existing_regular_file_returns_none(tmp_path):
    """存在的普通文件（非清单）不是合法挑战目标 → None。"""
    notes = tmp_path / "notes.txt"
    notes.write_text("not a challenge", encoding="utf-8")
    assert resolve_challenge_target(str(notes)) is None


def test_corrupt_challenge_json_returns_none(tmp_path):
    """目录里有损坏的 challenge.json → 无法解析，None 而不是带着 agent 裸奔。"""
    d = tmp_path / "broken-chal"
    d.mkdir()
    (d / "challenge.json").write_text("{not-json", encoding="utf-8")
    assert resolve_challenge_target(str(d)) is None


def test_none_and_blank_return_none(tmp_path, monkeypatch):
    """None / 空串 / 纯空白 → 一律不可定位（None 按防御性输入处理）。"""
    monkeypatch.chdir(tmp_path)
    assert resolve_challenge_target(None) is None  # type: ignore[arg-type]
    assert resolve_challenge_target("") is None
    assert resolve_challenge_target("   ") is None


# ── 路径启发式 ──────────────────────────────────────────────────────────────


def test_looks_like_path_heuristic():
    """路径形态（分隔符 / ./ ~/ 前缀 / 后缀）与裸挑战 id 的区分。"""
    for path_like in ("/tmp/x", "a/b", "./x", "../x", "~/x", "notes.txt", ".."):
        assert looks_like_path(path_like), path_like
    for bare_id in ("web-01", "chal_02", "Crypto100", "ctfd-5", "misc"):
        assert not looks_like_path(bare_id), bare_id
