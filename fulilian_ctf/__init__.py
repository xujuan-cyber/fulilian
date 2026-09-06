"""FuLiLian CTF 核心模块。

- Phase 1：三重校验门（verify）
- Phase 2（调度引擎，步骤 05）：timebox / probe / relay / registry / solver / dispatcher
- Phase 2（黑板架构，步骤 06）：blackboard（Fact/Intent/Hint + 父子黑板 + tags 信息素）
- Phase 2（止损与续接，步骤 07）：stopper（4 维止损 + 临门不弃）+ relay 续接编排
- Phase 3（知识层，步骤 08）：knowledge（知识卡注入）+ knowledge_retriever（FTS5 检索）
  + experiential_learning（跨题学习 + 自进化）
- Phase 3（高级功能，步骤 09）：racer（多模型竞速 + Coordinator）+ multi_agent
  （多 Agent 协作 + 共享记忆 + 幻觉检测）+ writeup（自动 Writeup）+ trace
  （追踪回放）+ ctfd_adapter（CTFd 对接 + 轮询 + MCP）+ monitor（对手监控）
- Phase 4（通用增强，步骤 10）：agents_md（F4-001）+ sandbox（F4-004 三档沙箱）
  + hooks（F4-003 危险命令/flag 检测）+ lsp_bridge（F4-008 编译诊断）
"""

from __future__ import annotations

from .agents_md import AGENTS_MD_FILENAME, ensure_agents_md, generate_agents_md
from .blackboard import (
    BLACKBOARD_FILENAME,
    Blackboard,
    Fact,
    Hint,
    Intent,
    State,
    load_blackboard,
    save_blackboard,
)
from .budget import BudgetConfig, BudgetTracker, ChallengeUsage, Difficulty
from .ctfd_adapter import (
    CTFdAdapter,
    CTFdError,
    create_poll_job,
    mcp_call_tool,
    poll_new_challenges,
    serve_mcp,
    sync_challenges,
)
from .monitor import Alert, OpponentMonitor, analyze_tool_call, scan_log_for_anomalies
from .multi_agent import (
    MultiAgentResult,
    SharedMemory,
    detect_hallucinations,
    run_multi_agent,
    run_multi_agent_for_challenge,
    run_boomerang,
)
from .racer import (
    COORDINATOR_INTERVAL,
    CoordinatorLoop,
    RaceResult,
    RacerResult,
    coordinator_advice,
    coordinator_analyze_traces,
    run_race,
    run_race_for_challenge,
)
from .trace import (
    Trace,
    TraceEntry,
    TraceStep,
    SolverTrace,
    build_trace,
    get_or_build_trace,
    load_trace,
    replay_trace,
    save_trace,
)
from .writeup import generate_writeup, save_writeup, writeup_to_format
from .dispatcher import ChallengeStatus, Dispatcher, Project
from .experiential_learning import (
    get_avoid_list,
    get_learning_stats,
    load_learnings,
    query_experience,
    query_index,
    record_lesson,
    record_solve_outcome,
    save_learnings,
    self_evolve,
)
from .knowledge import (
    CATEGORIES,
    SKILLS_DIR,
    get_knowledge_card,
    inject_ctf_context,
    inject_knowledge_card,
)
from .knowledge_retriever import (
    DB_PATH,
    KB_PATH,
    _guess_category,
    build_index,
    get_index_stats,
    list_categories,
    search,
    search_snippets,
    similar_by_technique,
)
from .probe import AutoPrompter, EnvInfo, FileInfo, NetworkInfo, ProbeResult, QuickScanResult, probe_challenge
from .specialists import (
    BaseSpecialist,
    SpecialistFactory,
    PwnSpecialist,
    RevSpecialist,
    WebSpecialist,
    CryptoSBeSpecialist,
    ForensicsSpecialist,
    MiscSpecialist,
)
from .reasoner import Plan, Reasoner, Task, TaskCategory, TaskResult
from .planner import ContextManager, Executor, Planner, Turn, TurnRole
from .registry import challenge_to_project, load_challenges
from .relay import (
    build_relay, parse_relay, read_relay_file, write_relay_file,
    # v2 结构化协议
    MessageType, Severity, RelayMessage, RelayBlock,
    RELAY_BLOCK_FILENAME, PROTOCOL_VERSION,
    make_achieved_message, make_dead_end_message, make_next_step_message,
    make_task_delegation, make_task_result, make_error_report,
    write_relay_block, read_relay_block,
)
from .sandbox import SandboxMode, enforce_sandbox
from .solver import (
    SolverResult,
    build_solve_query,
    resolve_default_model,
    solver_worker,
    switch_solver_model,
)
from .stopper import (
    DEFAULT_MAX_NO_OUTPUT_ROUNDS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_VARIANT_FAILURES,
    STOP_REASONS,
    Stopper,
    count_variant_failures,
    estimate_tokens_from_log,
)
from .timebox import (
    DIFFICULTY_BUDGETS,
    TIER_LABELS,
    TIER_THRESHOLDS,
    Timebox,
    difficulty_adjusted_budget,
)
from .verify import (
    ConfidenceLevel,
    DEFAULT_FLAG_PATTERNS,
    VerificationResult,
    check_output_for_flag,
    classify_confidence,
    extract_flag_candidates,
    is_flag_shaped,
    verify_flag,
    verify_flag_with_report,
)

__version__ = "0.5.0"

__all__ = [
    # verify (Phase 1)
    "ConfidenceLevel",
    "DEFAULT_FLAG_PATTERNS",
    "VerificationResult",
    "classify_confidence",
    "verify_flag",
    "verify_flag_with_report",
    "check_output_for_flag",
    "extract_flag_candidates",
    "is_flag_shaped",
    # timebox (F2-002 / F2-010)
    "TIER_THRESHOLDS",
    "TIER_LABELS",
    "DIFFICULTY_BUDGETS",
    "Timebox",
    "difficulty_adjusted_budget",
    # budget (统一预算控制层)
    "BudgetConfig",
    "BudgetTracker",
    "ChallengeUsage",
    "Difficulty",
    # probe (F2-003)
    "AutoPrompter",
    "EnvInfo",
    "FileInfo",
    "NetworkInfo",
    "ProbeResult",
    "QuickScanResult",
    "probe_challenge",
    # reasoner (F4-008)
    "Plan",
    "Reasoner",
    "Task",
    "TaskCategory",
    "TaskResult",
    # planner (F4-008)
    "ContextManager",
    "Executor",
    "Planner",
    "Turn",
    "TurnRole",
    # relay (F2-012 契约)
    "build_relay",
    "parse_relay",
    "read_relay_file",
    "write_relay_file",
    # v2 结构化协议
    "RELAY_BLOCK_FILENAME",
    "PROTOCOL_VERSION",
    "MessageType",
    "Severity",
    "RelayMessage",
    "RelayBlock",
    "make_achieved_message",
    "make_dead_end_message",
    "make_next_step_message",
    "make_task_delegation",
    "make_task_result",
    "make_error_report",
    "write_relay_block",
    "read_relay_block",
    # registry
    "load_challenges",
    "challenge_to_project",
    # solver
    "SolverResult",
    "build_solve_query",
    "solver_worker",
    "resolve_default_model",
    # stopper (F2-004 / F2-011，步骤 07)
    "STOP_REASONS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MAX_NO_OUTPUT_ROUNDS",
    "DEFAULT_MAX_VARIANT_FAILURES",
    "Stopper",
    "estimate_tokens_from_log",
    "count_variant_failures",
    # dispatcher (F2-001/007/008)
    "ChallengeStatus",
    "Project",
    "Dispatcher",
    # blackboard (F2-005/006/009)
    "State",
    "Fact",
    "Intent",
    "Hint",
    "Blackboard",
    "BLACKBOARD_FILENAME",
    "save_blackboard",
    "load_blackboard",
    # knowledge (Phase 3, F3-001)
    "CATEGORIES",
    "SKILLS_DIR",
    "get_knowledge_card",
    "inject_ctf_context",
    "inject_knowledge_card",
    # knowledge_retriever (Phase 3, F3-002)
    "KB_PATH",
    "DB_PATH",
    "build_index",
    "search",
    "search_snippets",
    "similar_by_technique",
    "get_index_stats",
    "list_categories",
    "_guess_category",
    # experiential_learning (Phase 3, F3-003/F3-004)
    "load_learnings",
    "save_learnings",
    "record_lesson",
    "query_experience",
    "query_index",
    "get_avoid_list",
    "self_evolve",
    "record_solve_outcome",
    "get_learning_stats",
    # racer (Phase 3, F3-005/F3-006 / F4-007)
    "COORDINATOR_INTERVAL",
    "CoordinatorLoop",
    "coordinator_advice",
    "coordinator_analyze_traces",
    "run_race",
    "run_race_for_challenge",
    # multi_agent (Phase 3, F3-007/008/009)
    "MultiAgentResult",
    "SharedMemory",
    "detect_hallucinations",
    "run_multi_agent",
    "run_multi_agent_for_challenge",
    "run_boomerang",
    # writeup (Phase 3, F3-010)
    "generate_writeup",
    "save_writeup",
    "writeup_to_format",
    # trace (Phase 3, F3-014 / F4-007)
    "Trace",
    "TraceEntry",
    "TraceStep",
    "SolverTrace",
    "build_trace",
    "get_or_build_trace",
    "load_trace",
    "replay_trace",
    "save_trace",
    # ctfd_adapter (Phase 3, F3-011/F3-012)
    "CTFdAdapter",
    "CTFdError",
    "create_poll_job",
    "mcp_call_tool",
    "poll_new_challenges",
    "serve_mcp",
    "sync_challenges",
    # monitor (Phase 3, F3-013)
    "Alert",
    "OpponentMonitor",
    "analyze_tool_call",
    "scan_log_for_anomalies",
    # specialists (Phase 2, 分类专家流水线)
    "BaseSpecialist",
    "SpecialistFactory",
    "PwnSpecialist",
    "RevSpecialist",
    "WebSpecialist",
    "CryptoSBeSpecialist",
    "ForensicsSpecialist",
    "MiscSpecialist",
    # Phase 4（通用增强，步骤 10）
    "AGENTS_MD_FILENAME",
    "ensure_agents_md",
    "generate_agents_md",
    "SandboxMode",
    "enforce_sandbox",
    "switch_solver_model",
    "__version__",
]
