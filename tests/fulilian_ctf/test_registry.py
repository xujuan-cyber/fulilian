"""题目注册表（solve-all 数据入口）单元测试。"""

from __future__ import annotations

import json

import pytest

from fulilian_ctf.registry import load_challenges


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_scan_challenge_subdirs(tmp_path):
    """目录 + 子目录 challenge.json → 自动扫描。"""
    _write_json(
        tmp_path / "web-01" / "challenge.json",
        {"id": "web-01", "difficulty": "easy", "score": 100},
    )
    _write_json(
        tmp_path / "crypto-01" / "challenge.json",
        {"id": "crypto-01", "difficulty": "hard"},
    )
    entries = load_challenges(tmp_path)
    assert [e["id"] for e in entries] == ["crypto-01", "web-01"]  # 按目录名排序
    assert entries[0]["difficulty"] == "hard"
    assert entries[1]["difficulty"] == "easy"
    # challenge_dir 自动指向子目录
    assert entries[1]["challenge_dir"] == str(tmp_path / "web-01")


def test_platform_manifest(tmp_path):
    """platform.json 清单 + 相对 dir。"""
    _write_json(
        tmp_path / "platform.json",
        {
            "name": "demo",
            "challenges": [
                {"id": "a", "dir": "chals/a", "difficulty": "easy", "score": 100},
                {"id": "b", "dir": "chals/b"},
            ],
        },
    )
    entries = load_challenges(tmp_path)
    assert [e["id"] for e in entries] == ["a", "b"]
    assert entries[0]["difficulty"] == "easy"
    assert entries[0]["score"] == 100
    assert entries[1]["difficulty"] == "medium"  # 缺省


def test_manifest_file_direct(tmp_path):
    """直接传清单文件路径。"""
    mf = tmp_path / "list.json"
    _write_json(mf, {"challenges": [{"id": "x"}]})
    entries = load_challenges(mf)
    assert entries[0]["id"] == "x"


def test_defaults_applied(tmp_path):
    _write_json(tmp_path / "challenge.json", {"id": "only"})
    entries = load_challenges(tmp_path)
    e = entries[0]
    assert e["difficulty"] == "medium"
    assert e["score"] == 0
    assert e["target_host"] == ""
    assert e["target_port"] == 0


def test_duplicate_id_rejected(tmp_path):
    _write_json(
        tmp_path / "platform.json",
        {"challenges": [{"id": "a"}, {"id": "a"}]},
    )
    with pytest.raises(ValueError, match="duplicate challenge id"):
        load_challenges(tmp_path)


def test_missing_id_rejected(tmp_path):
    _write_json(tmp_path / "challenge.json", {"title": "no id"})
    with pytest.raises(ValueError, match="missing 'id'"):
        load_challenges(tmp_path)


def test_empty_dir_rejected(tmp_path):
    with pytest.raises(ValueError, match="no challenges found"):
        load_challenges(tmp_path)


def test_missing_platform_rejected(tmp_path):
    with pytest.raises(ValueError, match="platform not found"):
        load_challenges(tmp_path / "nope")


def test_invalid_json_rejected(tmp_path):
    (tmp_path / "challenge.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_challenges(tmp_path)


def test_challenge_to_project(tmp_path):
    """dict → Project 转换（相对 dir 解析）。"""
    from fulilian_ctf.dispatcher import Project
    from fulilian_ctf.registry import challenge_to_project

    _write_json(
        tmp_path / "chals" / "web-01" / "challenge.json",
        {
            "id": "web-01",
            "title": "t",
            "category": "Web",
            "difficulty": "EASY",
            "score": 100,
            "target_host": "10.0.0.5",
            "target_port": 80,
        },
    )
    entries = load_challenges(tmp_path / "chals")
    proj: Project = challenge_to_project(entries[0], base_dir=tmp_path / "chals")
    assert proj.challenge_id == "web-01"
    assert proj.difficulty == "easy"  # 归一化小写
    assert proj.category == "web"
    assert proj.score == 100
    assert proj.target_host == "10.0.0.5"
    assert proj.target_port == 80
    assert proj.challenge_dir == str(tmp_path / "chals" / "web-01")
