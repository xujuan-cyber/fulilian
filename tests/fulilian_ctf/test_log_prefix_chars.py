"""FULILIAN_LOG_PREFIX_CHARS（镜像日志工具参数预览宽度）解析测试。

背景（⑤ A/B 观察缺口）：run_agent_main 默认 log_prefix_chars=20，
terminal 命令在镜像日志里全被截成 "cd /tmp..."（前缀碰撞），重复命令
计数不可用。跑批方需要设宽拿完整命令；不设则行为零变化。
"""

import sys

import fulilian_ctf.solver as solver


def test_unset_returns_default_20(monkeypatch):
    monkeypatch.delenv("FULILIAN_LOG_PREFIX_CHARS", raising=False)
    assert solver._log_prefix_chars_from_env() == 20


def test_set_wide(monkeypatch):
    monkeypatch.setenv("FULILIAN_LOG_PREFIX_CHARS", "400")
    assert solver._log_prefix_chars_from_env() == 400


def test_invalid_and_nonpositive_fall_back(monkeypatch):
    for bad in ("abc", "0", "-5"):
        monkeypatch.setenv("FULILIAN_LOG_PREFIX_CHARS", bad)
        assert solver._log_prefix_chars_from_env() == 20, bad


def test_solved_path_passes_env_value(monkeypatch, tmp_path):
    """接线锁：solve 主路径必须把 env 解析值传给 run_agent_main。"""
    import inspect
    src = inspect.getsource(solver)
    # 实现按函数体调用；这里锁住调用点参数名存在，防止未来重构裸奔回默认
    assert "log_prefix_chars=_log_prefix_chars_from_env()" in src
