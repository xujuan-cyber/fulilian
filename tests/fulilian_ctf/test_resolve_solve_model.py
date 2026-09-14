"""resolve_solve_model（计划书 P6 模型路由）回归测试。

设计约束（与 A3/A9 的假对照教训同源）：
- 优先级链：显式 ``--model`` > env ``FULILIAN_CTF_MODEL`` >
  config ``ctf.solve_model`` > config ``model.default``。
- 关键字 ``strong`` 解析为 config ``ctf.strong_model`` —— 跑批方用一个词
  把难题子集拨到最强模型，不必在脚本里写具体模型名。
- ``strong`` 被请求但 ``ctf.strong_model`` 未配置时**大声降级**并落回下一级
  ——「以为在用强模型其实在用默认」必须看得见，不许静默。
- 解析失败不抛异常：路由不该挡住解题。
"""

from __future__ import annotations

import pytest

import fulilian_ctf.solver as solver


@pytest.fixture()
def patch_config(monkeypatch):
    """把 fulilian_cli.config.load_config 替换为受控字典。

    resolve_solve_model / resolve_default_model 都在函数体内
    ``from fulilian_cli.config import load_config``，所以 patch 模块属性即可。
    """

    def _set(cfg: dict) -> None:
        monkeypatch.setattr(
            "fulilian_cli.config.load_config", lambda: cfg
        )

    return _set


def test_explicit_model_wins_over_everything(monkeypatch, patch_config):
    monkeypatch.setenv("FULILIAN_CTF_MODEL", "env-model")
    patch_config({"ctf": {"solve_model": "cfg-model"},
                  "model": {"default": "default-model"}})
    assert solver.resolve_solve_model("cli-model") == ("cli-model", "--model")


def test_env_plain_model(monkeypatch, patch_config):
    monkeypatch.setenv("FULILIAN_CTF_MODEL", "env-model")
    patch_config({"model": {"default": "default-model"}})
    model, source = solver.resolve_solve_model("")
    assert model == "env-model"
    assert "FULILIAN_CTF_MODEL" in source


def test_env_strong_keyword_resolves_to_strong_model(monkeypatch, patch_config):
    monkeypatch.setenv("FULILIAN_CTF_MODEL", "strong")
    patch_config({"ctf": {"strong_model": "the-strong-one"},
                  "model": {"default": "default-model"}})
    model, source = solver.resolve_solve_model("")
    assert model == "the-strong-one"
    assert "strong_model" in source


def test_strong_unconfigured_loudly_falls_through(monkeypatch, patch_config, capsys):
    """strong 被请求但 ctf.strong_model 未配置 → 报警 + 落回下一级，绝不静默。"""
    monkeypatch.setenv("FULILIAN_CTF_MODEL", "strong")
    patch_config({"model": {"default": "default-model"}})
    model, source = solver.resolve_solve_model("")
    err = capsys.readouterr().err
    assert "strong_model is not set" in err
    assert model == "default-model"
    assert source == "config model.default"


def test_config_solve_model(monkeypatch, patch_config):
    monkeypatch.delenv("FULILIAN_CTF_MODEL", raising=False)
    patch_config({"ctf": {"solve_model": "cfg-model"},
                  "model": {"default": "default-model"}})
    model, source = solver.resolve_solve_model("")
    assert model == "cfg-model"
    assert "ctf.solve_model" in source


def test_default_fallback(monkeypatch, patch_config):
    monkeypatch.delenv("FULILIAN_CTF_MODEL", raising=False)
    patch_config({"model": {"default": "default-model"}})
    model, source = solver.resolve_solve_model("")
    assert (model, source) == ("default-model", "config model.default")


def test_config_read_failure_returns_empty_not_raise(monkeypatch):
    """配置读不了 → 空串（与 resolve_default_model 的空串语义一致），不挡解题。"""
    monkeypatch.setenv("FULILIAN_CTF_MODEL", "strong")
    monkeypatch.setattr(
        "fulilian_cli.config.load_config",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    model, source = solver.resolve_solve_model("")
    assert model == ""
    assert source == "config model.default"
