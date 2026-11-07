"""Attribution contract for ``get_subagent_attribution``.

Pins the reason ``_active_subagents`` / ``_recent_subagents`` exist in
``tools.delegate_tool``: a subagent's background processes routinely outlive
the subagent itself (its ``npm ci`` with ``notify_on_complete=true`` finishes
after the child's summary was already delivered), and their completion
notifications must still resolve back to the delegation that started them.
``tools/process_registry.py`` is the caller.

State is built exclusively through the real lifecycle writers --
``_register_subagent`` for a running child and ``_unregister_subagent`` for a
finished one -- never by assigning into the dicts directly.  A direct dict
poke would only prove the dict is readable; the contract under test is that
the lifecycle functions actually *write* it.
"""

import pytest

from tools import delegate_tool
from tools.delegate_tool import (
    _register_subagent,
    _unregister_subagent,
    get_subagent_attribution,
)


@pytest.fixture(autouse=True)
def _isolated_registries():
    """Snapshot and restore both registries around each test.

    This is teardown hygiene only.  Every assertion below is constructed by
    calling the real lifecycle writers; the restore exists so a stray id can
    never leak into another test file's run.
    """
    with delegate_tool._active_subagents_lock:
        active = dict(delegate_tool._active_subagents)
        recent = dict(delegate_tool._recent_subagents)
    try:
        yield
    finally:
        with delegate_tool._active_subagents_lock:
            delegate_tool._active_subagents.clear()
            delegate_tool._active_subagents.update(active)
            delegate_tool._recent_subagents.clear()
            delegate_tool._recent_subagents.update(recent)


def _spawn_record(subagent_id: str, goal: str, delegation_id: str) -> dict:
    """The record shape ``_run_single_child`` hands to ``_register_subagent``."""
    return {
        "subagent_id": subagent_id,
        "parent_id": "sess-parent-p7",
        "depth": 0,
        "goal": goal,
        "model": "test-model",
        "started_at": 1000.0,
        "status": "running",
        "tool_count": 0,
        "delegation_id": delegation_id,
        "owner_agent_session_id": "sess-parent-p7",
        "agent": None,
    }


def test_attribution_finds_running_subagent():
    """A child that is still running resolves out of ``_active_subagents``."""
    sid = "sa-0-p7run0001"
    _register_subagent(_spawn_record(sid, "迁移 npm 依赖", "deleg_p7_run"))

    info = get_subagent_attribution(sid)

    assert info == {
        "subagent_id": sid,
        "goal": "迁移 npm 依赖",
        "delegation_id": "deleg_p7_run",
    }


def test_attribution_finds_recently_finished_subagent():
    """After the child finishes, attribution must survive out of
    ``_recent_subagents`` -- its background processes outlive it.

    The finished state is produced by the real unregister path, which is the
    only code that populates the retained stub.
    """
    sid = "sa-0-p7done0001"
    _register_subagent(_spawn_record(sid, "跑 npm ci 并通知", "deleg_p7_done"))

    _unregister_subagent(sid)

    # Proves the child left the live table through the lifecycle path, so the
    # assertion below can only be satisfied by the retained stub.
    assert sid not in delegate_tool._active_subagents

    info = get_subagent_attribution(sid)

    assert info is not None
    assert info["subagent_id"] == sid
    assert info["goal"] == "跑 npm ci 并通知"
    assert info["delegation_id"] == "deleg_p7_done"


def test_attribution_returns_none_for_unknown_task_id():
    """A well-formed subagent id that was never registered has no owner."""
    assert get_subagent_attribution("sa-0-p7never0001") is None


def test_attribution_returns_none_for_non_subagent_id():
    """Ordinary process task ids must not be attributed to a delegation."""
    assert get_subagent_attribution("proc-7f3a9c") is None
    assert get_subagent_attribution("") is None
    assert get_subagent_attribution(None) is None
