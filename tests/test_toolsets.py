"""Tests for toolsets.py — toolset resolution, validation, and composition."""

import toolsets as toolsets_mod
from tools.registry import ToolRegistry
from toolsets import (
    TOOLSETS,
    get_toolset,
    resolve_toolset,
    resolve_multiple_toolsets,
    get_all_toolsets,
    validate_toolset,
    create_custom_toolset,
    get_toolset_info,
)


def _dummy_handler(args, **kwargs):
    return "{}"


def _make_schema(name: str, description: str = "test tool"):
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": {}},
    }


class TestGetToolset:
    def test_known_toolset(self):
        ts = get_toolset("web")
        assert ts is not None
        assert "web_search" in ts["tools"]

    def test_x_search_toolset_marks_read_only_and_points_to_xurl(self):
        ts = get_toolset("x_search")
        assert ts is not None
        assert ts["tools"] == ["x_search"]
        description = ts["description"].lower()
        assert "read-only" in description
        assert "xurl" in description
        assert "authenticated" in description

    def test_merges_registry_tools_into_builtin_toolset(self, monkeypatch):
        reg = ToolRegistry()
        reg.register(
            name="web_search_plus",
            toolset="web",
            schema=_make_schema("web_search_plus", "Plugin web search"),
            handler=_dummy_handler,
        )

        monkeypatch.setattr("tools.registry.registry", reg)

        ts = get_toolset("web")
        assert ts is not None
        assert set(ts["tools"]) == {"web_search", "web_extract", "web_search_plus"}



class TestResolveToolset:
    def test_leaf_toolset(self):
        tools = resolve_toolset("web")
        assert set(tools) == {"web_search", "web_extract"}

    def test_composite_toolset(self):
        tools = resolve_toolset("debugging")
        assert "terminal" in tools
        assert "web_search" in tools
        assert "web_extract" in tools

    def test_cycle_detection(self):
        # Create a cycle: A includes B, B includes A
        TOOLSETS["_cycle_a"] = {"description": "test", "tools": ["t1"], "includes": ["_cycle_b"]}
        TOOLSETS["_cycle_b"] = {"description": "test", "tools": ["t2"], "includes": ["_cycle_a"]}
        try:
            tools = resolve_toolset("_cycle_a")
            # Should not infinite loop — cycle is detected
            assert "t1" in tools
            assert "t2" in tools
        finally:
            del TOOLSETS["_cycle_a"]
            del TOOLSETS["_cycle_b"]


    def test_plugin_toolset_uses_registry_snapshot(self, monkeypatch):
        reg = ToolRegistry()
        reg.register(
            name="plugin_b",
            toolset="plugin_example",
            schema=_make_schema("plugin_b", "B"),
            handler=_dummy_handler,
        )
        reg.register(
            name="plugin_a",
            toolset="plugin_example",
            schema=_make_schema("plugin_a", "A"),
            handler=_dummy_handler,
        )

        monkeypatch.setattr("tools.registry.registry", reg)

        assert resolve_toolset("plugin_example") == ["plugin_a", "plugin_b"]




class TestResolveMultipleToolsets:
    def test_combines_and_deduplicates(self):
        tools = resolve_multiple_toolsets(["web", "terminal"])
        assert "web_search" in tools
        assert "web_extract" in tools
        assert "terminal" in tools
        # No duplicates
        assert len(tools) == len(set(tools))



class TestValidateToolset:
    def test_valid(self):
        assert validate_toolset("web") is True
        assert validate_toolset("terminal") is True


    def test_invalid(self):
        assert validate_toolset("nonexistent") is False

    def test_mcp_alias_uses_live_registry(self, monkeypatch):
        reg = ToolRegistry()
        reg.register(
            name="mcp__dynserver__ping",
            toolset="mcp-dynserver",
            schema=_make_schema("mcp__dynserver__ping", "Ping"),
            handler=_dummy_handler,
        )
        reg.register_toolset_alias("dynserver", "mcp-dynserver")

        monkeypatch.setattr("tools.registry.registry", reg)

        assert validate_toolset("dynserver") is True
        assert validate_toolset("mcp-dynserver") is True
        assert "mcp__dynserver__ping" in resolve_toolset("dynserver")


class TestGetToolsetInfo:
    def test_leaf(self):
        info = get_toolset_info("web")
        assert info["name"] == "web"
        assert info["is_composite"] is False
        assert info["tool_count"] == 2

    def test_composite(self):
        info = get_toolset_info("debugging")
        assert info["is_composite"] is True
        assert info["tool_count"] > len(info["direct_tools"])



class TestCreateCustomToolset:
    def test_runtime_creation(self):
        create_custom_toolset(
            name="_test_custom",
            description="Test toolset",
            tools=["web_search"],
            includes=["terminal"],
        )
        try:
            tools = resolve_toolset("_test_custom")
            assert "web_search" in tools
            assert "terminal" in tools
            assert validate_toolset("_test_custom") is True
        finally:
            del TOOLSETS["_test_custom"]


class TestRegistryOwnedToolsets:
    def test_registry_membership_is_live(self, monkeypatch):
        reg = ToolRegistry()
        reg.register(
            name="test_live_toolset_tool",
            toolset="test-live-toolset",
            schema=_make_schema("test_live_toolset_tool", "Live"),
            handler=_dummy_handler,
        )

        monkeypatch.setattr("tools.registry.registry", reg)

        assert validate_toolset("test-live-toolset") is True
        assert get_toolset("test-live-toolset")["tools"] == ["test_live_toolset_tool"]
        assert resolve_toolset("test-live-toolset") == ["test_live_toolset_tool"]


class TestToolsetConsistency:
    """Verify structural integrity of the built-in TOOLSETS dict."""

    def test_all_toolsets_have_required_keys(self):
        for name, ts in TOOLSETS.items():
            assert "description" in ts, f"{name} missing description"
            assert "tools" in ts, f"{name} missing tools"
            assert "includes" in ts, f"{name} missing includes"


    def test_fulilian_platforms_share_core_tools(self):
        """All fulilian-* platform toolsets share the same core tools.

        Platform-specific additions (e.g. ``discord`` / ``discord_admin``
        on fulilian-discord, gated on DISCORD_BOT_TOKEN) are allowed on top —
        the invariant is that the core set is identical across platforms.
        """
        platforms = ["fulilian-cli", "fulilian-telegram", "fulilian-discord", "fulilian-whatsapp", "fulilian-slack", "fulilian-signal", "fulilian-homeassistant"]
        tool_sets = [set(TOOLSETS[p]["tools"]) for p in platforms]
        # All platforms must contain the shared core; platform-specific
        # extras are OK (subset check, not equality).
        core = set.intersection(*tool_sets)
        for name, ts in zip(platforms, tool_sets):
            assert core.issubset(ts), f"{name} is missing core tools: {core - ts}"
        # Sanity: the shared core must be non-trivial (i.e. we didn't
        # silently let a platform diverge so far that nothing is shared).
        assert len(core) > 20, f"Suspiciously small shared core: {len(core)} tools"


class TestCtfSolveToolset:
    """CTF 解题工具集：解题工具 + includes，**不带**回合后自省工具。

    这里曾锁着相反的不变量（memory / skill_manage 必须在 ctf_solve 里），
    理由是那两个名字是回合后自省 fork（agent/background_review.py）的触发
    前提，缺了则解题经验全部丢失。该理由在 CTF 路径上已被 A3 撤销：解题会话
    用 skip_background_review=True 关掉了这条 fork（run_agent.py
    _run_solver_turn），触发条件无人消费。实测 3 题 43 次工具调用里这两个
    工具调用 0 次，而 schema 合计 5,631 字符（14 个工具共 22,942 字符的
    24.5%），随每次 API 调用重发 ≈ 1,400 tokens，占全部 input token 的 8%。

    真正的约束不是"工具在不在"，而是**开关与工具集同进同出** ——
    见 test_solver_spawn_and_toolset_are_coupled。经验沉淀改为批次结束后
    统一做一次，不是每题一次。
    """

    def test_static_definition_keeps_solver_tools_and_drops_review_tools(self):
        tools = set(TOOLSETS["ctf_solve"]["tools"])
        # CTF 解题工具
        assert {"verify_flag", "checkpoint", "generate_writeup", "compile_check"} <= tools
        # 自省 fork 已关（A3），这两个工具是纯开销
        assert "memory" not in tools
        assert "skill_manage" not in tools

    def test_resolved_toolset_keeps_includes_without_review_tools(self):
        from tools.registry import discover_builtin_tools

        discover_builtin_tools()
        resolved = set(resolve_toolset("ctf_solve"))
        assert not ({"memory", "skill_manage"} & resolved)
        # includes（terminal / file / web / vision）不回归
        assert {"terminal", "process", "read_file", "write_file", "web_search"} <= resolved

    def test_registry_produces_schemas_for_solver_tools(self):
        """registry 必须实际产出解题工具的 schema（按真实构建路径断言）。

        工具名写错（或被 check_fn 过滤）时 registry 会静默丢弃，
        valid_tool_names 里就不会出现对应名字，解题门失效也不报错 ——
        所以这里走 model_tools 的构建路径，而不是只看静态定义。
        """
        from model_tools import get_tool_definitions

        defs = get_tool_definitions(
            enabled_toolsets=["ctf_solve"], quiet_mode=True,
            skip_tool_search_assembly=True,
        )
        names = {t["function"]["name"] for t in defs}
        assert {"verify_flag", "submit_flag"} <= names

    def test_solver_spawn_and_toolset_are_coupled(self):
        """自省开关与自省工具必须同进同出（回归锁，两个方向都拦）。

        memory / skill_manage 留在 ctf_solve 里的唯一用途是让回合后自省 fork
        能触发。_run_solver_turn 关掉了该 fork，所以工具被移除；反过来，若有人
        删掉那个开关却没把工具加回来，自省会**静默**失效 —— 不报错、不告警，
        只是解题经验不再沉淀。这里把耦合本身锁住，而不是锁单边。
        """
        import inspect

        import run_agent as ra

        review_disabled = "skip_background_review=True" in inspect.getsource(
            ra._run_solver_turn
        )
        review_tools = {"memory", "skill_manage"} & set(TOOLSETS["ctf_solve"]["tools"])

        if review_disabled:
            assert not review_tools, (
                "自省 fork 已关（skip_background_review=True），这两个工具是纯开销"
                "（5,631 字符 schema ≈ 1,400 tokens/次调用），不应留在 ctf_solve。"
                "若确实要重新开启 fork，请同时把它们加回 toolsets.py 并更新本测试。"
            )
        else:
            assert review_tools == {"memory", "skill_manage"}, (
                "自省 fork 开着，但 memory/skill_manage 不在 ctf_solve 里 —— "
                "fork 永不触发且静默，解题经验会全部丢失。"
            )


class TestPluginToolsets:
    def test_get_all_toolsets_includes_plugin_toolset(self, monkeypatch):
        reg = ToolRegistry()
        reg.register(
            name="plugin_tool",
            toolset="plugin_bundle",
            schema=_make_schema("plugin_tool", "Plugin tool"),
            handler=_dummy_handler,
        )

        monkeypatch.setattr("tools.registry.registry", reg)

        all_toolsets = get_all_toolsets()
        assert "plugin_bundle" in all_toolsets
        assert all_toolsets["plugin_bundle"]["tools"] == ["plugin_tool"]


class TestDefaultPlatformWebSearchCoverage:
    def test_fulilian_whatsapp_toolset_includes_web_search(self):
        assert "web_search" in resolve_toolset("fulilian-whatsapp")



class TestResolveToolsetIncludeRegistry:
    """include_registry flag exposes the static (pre-registry-merge) view used
    by platform reverse-mapping. Regression harness for issue #49622."""

    def test_include_registry_false_excludes_registry_tools(self):
        from tools.registry import discover_builtin_tools, registry
        discover_builtin_tools()

        # Register a tool into `terminal` at runtime, the way plugins and MCP
        # servers do, so the split is exercised on the mechanism rather than on
        # whichever built-in currently happens to live where.
        registry.register(
            name="__probe_registry_only_tool__",
            toolset="terminal",
            schema={"name": "__probe_registry_only_tool__", "parameters": {"type": "object", "properties": {}}},
            handler=lambda args, **kw: "",
        )
        try:
            merged = set(resolve_toolset("terminal"))
            static = set(resolve_toolset("terminal", include_registry=False))
        finally:
            registry.deregister("__probe_registry_only_tool__")

        assert static == {"terminal", "process"}, static
        # Registered into 'terminal' but not part of the static definition — it
        # must only appear in the merged view.
        assert "__probe_registry_only_tool__" in merged
        assert "__probe_registry_only_tool__" not in static


    def test_static_view_threads_through_includes(self):
        # 'debugging' has direct tools [terminal, process] and includes [web, file]
        static = set(resolve_toolset("debugging", include_registry=False))
        assert {"terminal", "process"} <= static
        assert "web_search" in static
        assert "read_file" in static


    def test_registry_only_toolset_static_view_is_empty(self):
        assert resolve_toolset("__definitely_not_a_real_toolset__", include_registry=False) == []


class TestResolveToolsetMemo:
    """Measured-work pins for the generation-keyed resolution memo."""

    def test_second_resolution_is_cached(self, monkeypatch):
        """Repeated resolves of the same toolset must not re-walk the registry.

        resolve_toolset is called dozens of times per _get_platform_tools()
        (every /tools completion keystroke). The memo keyed on the registry
        generation makes repeat calls a dict lookup instead of a full
        includes-walk + registry snapshot.
        """
        from tools.registry import registry

        toolsets_mod._resolve_toolset_memo.clear()
        get_toolset_calls = {"n": 0}

        orig_get_toolset = toolsets_mod.get_toolset

        def counting_get_toolset(name, *, include_registry=True):
            get_toolset_calls["n"] += 1
            return orig_get_toolset(name, include_registry=include_registry)

        monkeypatch.setattr(toolsets_mod, "get_toolset", counting_get_toolset)

        registry_id = id(registry)
        generation = registry._generation

        first = resolve_toolset("fulilian-cli")
        second = resolve_toolset("fulilian-cli")

        assert first == second
        assert get_toolset_calls["n"] == 1, (
            "second resolution must be a memo hit (no get_toolset re-walk), "
            f"got {get_toolset_calls['n']} calls"
        )
        assert (
            "fulilian-cli", True, registry_id, generation
        ) in toolsets_mod._resolve_toolset_memo

    def test_generation_bump_invalidates_memo(self, monkeypatch):
        """A registry mutation (generation bump) must force a fresh resolve."""
        from tools.registry import registry

        toolsets_mod._resolve_toolset_memo.clear()
        get_toolset_calls = {"n": 0}

        orig_get_toolset = toolsets_mod.get_toolset

        def counting_get_toolset(name, *, include_registry=True):
            get_toolset_calls["n"] += 1
            return orig_get_toolset(name, include_registry=include_registry)

        monkeypatch.setattr(toolsets_mod, "get_toolset", counting_get_toolset)

        resolve_toolset("fulilian-cli")
        assert get_toolset_calls["n"] == 1

        # Simulate a registry mutation bumping the generation.
        registry._generation += 1
        resolve_toolset("fulilian-cli")
        assert get_toolset_calls["n"] == 2, (
            "generation bump must invalidate the memo and re-resolve"
        )

    def test_memo_result_matches_fresh_resolution(self):
        """The memo must never change the resolved result."""
        toolsets_mod._resolve_toolset_memo.clear()
        first = resolve_toolset("fulilian-cli", include_registry=False)
        second = resolve_toolset("fulilian-cli", include_registry=False)
        assert first == second
        assert first  # non-empty sanity

