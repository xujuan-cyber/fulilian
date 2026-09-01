"""CTF solver tools — verify_flag, submit_flag, git_auto_commit, checkpoint, generate_writeup.

Registered in the ``ctf_solve`` toolset.
- Phase 1: verify_flag (三重校验门), submit_flag（声明式提交）, git_auto_commit.
- Phase 2/3: checkpoint（续接）, generate_writeup（自动报告）.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
from pathlib import Path

from tools.registry import registry

FLAG_FILENAME = "FLAG"


def _unpack(handler):
    """适配 registry.dispatch 的调用约定。

    dispatch 调用 ``handler(args_dict, **context_kwargs)``（task_id /
    session_id / user_task 等运行时上下文走 kwargs），而本模块的 impl 均
    为命名参数风格。此适配器把 args_dict 解包为命名参数，只传 impl 声明过
    的键——模型多传的键（如习惯性带上 task_id）与上下文 kwargs 一并丢弃，
    避免 TypeError 使校验门/提交门整体失效。
    """
    accepted = set(inspect.signature(handler).parameters)

    def wrapper(args, **context_kw):
        values = {k: v for k, v in (args or {}).items() if k in accepted}
        values.update({k: v for k, v in context_kw.items() if k in accepted})
        return handler(**values)

    return wrapper


# ── 工具实现 ─────────────────────────────────────────────────────────

def _llm_negator(candidate: str, evidence: str, parent_agent) -> bool:
    """Ask a leaf skeptic; fail closed unless it explicitly supports the flag."""
    from tools.delegate_tool import delegate_task

    response = delegate_task(
        goal=(
            "Act as a skeptical CTF flag verifier. Decide whether the candidate "
            "is genuinely supported by the evidence. Return exactly PASS or REBUT, "
            "with a brief reason. Do not run tools."
        ),
        context=f"Candidate: {candidate}\nEvidence:\n{evidence}",
        role="leaf",
        background=False,
        parent_agent=parent_agent,
    )
    text = response if isinstance(response, str) else json.dumps(response)
    upper = text.upper()
    if "REBUT" in upper or "REJECT" in upper or "HALLUCIN" in upper:
        return True
    return not any(token in upper for token in ("PASS", "CONFIRMED", "SUPPORTED"))


def _verify_flag_impl(candidate: str, evidence: str = "", parent_agent=None) -> str:
    """Verify a flag candidate through the triple-verification gate."""
    from fulilian_ctf.verify import VerificationResult, verify_flag

    negator = None
    if parent_agent is not None:
        negator = lambda c, e: _llm_negator(c, e, parent_agent)
    result = verify_flag(candidate, evidence, negator=negator)
    return f"verify_flag: candidate={candidate!r} → {result.value}"


def _submit_flag_impl(work_dir: str) -> str:
    """声明式提交：只提交 FLAG 文件中的候选，提交前走三重校验门。

    Agent 必须先在工作区写入 FLAG 文件，本工具才会读取并提交。
    """
    try:
        flag_file = Path(work_dir) / FLAG_FILENAME
    except (TypeError, ValueError):
        return "submit_flag: invalid work_dir"

    if not flag_file.exists():
        return (
            f"No FLAG file found at {flag_file}. "
            "Agent must write the flag to the FLAG file first."
        )

    try:
        candidate = flag_file.read_text(encoding="utf-8").strip()
    except OSError as e:
        return f"submit_flag: failed to read FLAG file: {e}"

    if not candidate:
        return "FLAG file is empty."

    # 走三重校验门（声明式提交路径：无工具输出作证据，require_grounding=False）
    from fulilian_ctf.verify import VerificationResult, verify_flag

    result = verify_flag(candidate, evidence="", require_grounding=False)
    if result == VerificationResult.CONFIRMED:
        return f"Flag submitted: {candidate}"
    return f"Flag rejected by verification gate: {result.value}"


def _record_fact_impl(work_dir: str, content: str, tags: str = "") -> str:
    """把已确认/已推翻的发现发布到黑板（solver 间共享，Stigmergy）。

    黑板是止损（无产出维度）与跨 solver 协同（死路免疫）的数据源：
    agent 每得到一个 CONFIRMED/REFUTED 的发现就发布一条 Fact。
    同内容幂等（重复发布忽略），失败不抛异常（工具返回错误文本）。
    """
    content = (content or "").strip()
    if not work_dir or not content:
        return "record_fact: work_dir and content are required"
    try:
        from fulilian_ctf.blackboard import (
            BLACKBOARD_FILENAME,
            Blackboard,
            Fact,
            load_blackboard,
            save_blackboard,
        )

        board_path = Path(work_dir) / BLACKBOARD_FILENAME
        board = load_blackboard(board_path) or Blackboard()
        existing = {f.content for f in board.get_facts()}
        if content in existing:
            return "record_fact: duplicate content already on blackboard (ignored)"
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        board.add_fact(Fact(content=content, source="agent", tags=tag_list))
        save_blackboard(board, board_path)
        return f"record_fact: published — {content[:80]}"
    except Exception as e:  # noqa: BLE001 — 黑板写入失败不中断 agent 流程
        return f"record_fact failed: {e}"


def _git_auto_commit_impl(work_dir: str, message: str) -> str:
    """自动提交解题进度到 git（每个步骤一个 commit，便于回滚与追踪）。"""
    if not work_dir:
        return "git_auto_commit: work_dir is required"
    try:
        work_path = Path(work_dir)
        work_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"git_auto_commit: cannot create work_dir: {e}"

    try:
        # 初始化 git 仓库（如果不存在）
        if not (work_path / ".git").exists():
            init = subprocess.run(
                ["git", "init"], cwd=str(work_path), capture_output=True, text=True
            )
            if init.returncode != 0:
                return f"git_auto_commit: git init failed: {init.stderr.strip()}"

        # 配置本地身份（无全局配置时避免 commit 失败）
        for key, value in (("user.email", "fulilian@local"), ("user.name", "fulilian")):
            subprocess.run(
                ["git", "config", key, value],
                cwd=str(work_path), capture_output=True, text=True,
            )

        # 添加所有文件
        subprocess.run(
            ["git", "add", "-A"], cwd=str(work_path), capture_output=True, text=True
        )

        # 提交
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(work_path),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Auto-committed: {message}"
        stderr = result.stderr.strip()
        if "nothing to commit" in stderr or "no changes added" in stderr:
            return "Auto-commit skipped: no changes to commit"
        return f"Auto-commit skipped: {stderr}"

    except FileNotFoundError:
        return "git_auto_commit: git executable not found on PATH"
    except Exception as e:  # noqa: BLE001
        return f"git_auto_commit failed: {e}"


def _checkpoint_impl(state: str = "") -> str:
    """Save the current solve state to a checkpoint (Phase 2 stub)."""
    return f"checkpoint: state={state!r} (Phase 2 stub)"


def _generate_writeup_impl(challenge_id: str = "") -> str:
    """Auto-generate a CTF writeup from session history (Phase 3 stub)."""
    return f"generate_writeup: challenge_id={challenge_id!r} (Phase 3 stub)"


# ── 工具注册 ─────────────────────────────────────────────────────────

registry.register(
    name="verify_flag",
    toolset="ctf_solve",
    schema={
        "type": "function",
        "function": {
            "name": "verify_flag",
            "description": "Verify a flag candidate against collected evidence through the "
                           "triple-verification gate. Returns CONFIRMED / HALLUCINATION / "
                           "REJECTED / PENDING.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate": {
                        "type": "string",
                        "description": "The flag candidate string to verify",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "The command output / evidence that produced the candidate",
                    },
                },
                "required": ["candidate"],
            },
        },
    },
    handler=_unpack(_verify_flag_impl),
    description="Verify a flag candidate against evidence",
)

registry.register(
    name="submit_flag",
    toolset="ctf_solve",
    schema={
        "type": "function",
        "function": {
            "name": "submit_flag",
            "description": "Declarative commit: read the FLAG file in the challenge workspace and "
                           "submit it through the verification gate. The agent MUST write the "
                           "candidate flag to the FLAG file first; only FLAG file contents are "
                           "submitted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_dir": {
                        "type": "string",
                        "description": "Challenge workspace directory containing the FLAG file",
                    },
                },
                "required": ["work_dir"],
            },
        },
    },
    handler=_unpack(_submit_flag_impl),
    description="Submit the flag from the workspace FLAG file",
)

registry.register(
    name="record_fact",
    toolset="ctf_solve",
    schema={
        "type": "function",
        "function": {
            "name": "record_fact",
            "description": "Publish a confirmed or refuted finding to the challenge blackboard "
                           "(shared across solvers). Call this whenever a hypothesis is "
                           "CONFIRMED (e.g. port open, version identified, vuln exists) or "
                           "REFUTED (e.g. 'CVE-X not exploitable — 404'), including the minimal "
                           "reproduction command when available. Duplicate content is ignored.",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_dir": {
                        "type": "string",
                        "description": "Challenge workspace directory containing blackboard.json",
                    },
                    "content": {
                        "type": "string",
                        "description": "Objective finding, e.g. 'port 80 open, Apache 2.4.49 "
                                       "(curl -v http://$TARGET)'",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Optional comma-separated tags, e.g. 'web,recon'",
                    },
                },
                "required": ["work_dir", "content"],
            },
        },
    },
    handler=_unpack(_record_fact_impl),
    description="Publish a confirmed/refuted finding to the blackboard",
)

registry.register(
    name="git_auto_commit",
    toolset="ctf_solve",
    schema={
        "type": "function",
        "function": {
            "name": "git_auto_commit",
            "description": "Auto-commit the current solve progress to git in the challenge "
                           "workspace. Initializes a repo if needed. Use after meaningful steps "
                           "so progress can be rolled back or replayed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_dir": {
                        "type": "string",
                        "description": "Challenge workspace directory",
                    },
                    "message": {
                        "type": "string",
                        "description": "Commit message describing this step",
                    },
                },
                "required": ["work_dir", "message"],
            },
        },
    },
    handler=_unpack(_git_auto_commit_impl),
    description="Auto-commit solve progress to git",
)

registry.register(
    name="checkpoint",
    toolset="ctf_solve",
    schema={
        "type": "function",
        "function": {
            "name": "checkpoint",
            "description": "Save the current solve state to the persistent checkpoint. "
                           "Useful for long-running solves so progress is not lost on crash.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {
                        "type": "string",
                        "description": "JSON-encoded state summary to checkpoint",
                    },
                },
                "required": [],
            },
        },
    },
    handler=_unpack(_checkpoint_impl),
    description="Save current solve state checkpoint",
)


def _compile_check_impl(source_file: str = "", language: str = "") -> str:
    """编译诊断（F4-008）：gcc/g++ -fsyntax-only / cargo check，报错喂回 agent。"""
    if not source_file:
        return "compile_check: source_file is required"
    from fulilian_ctf.lsp_bridge import diagnostics_summary

    return diagnostics_summary(source_file, language or _guess_language(source_file))


def _guess_language(source_file: str) -> str:
    suffix = Path(source_file).suffix.lower()
    return {".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
            ".hpp": "cpp", ".rs": "rust"}.get(suffix, "")


registry.register(
    name="compile_check",
    toolset="ctf_solve",
    schema={
        "type": "function",
        "function": {
            "name": "compile_check",
            "description": "Compile/syntax-check an exploit or helper source file "
                           "(c/cpp/rust) and return the compiler diagnostics so you can "
                           "fix errors before running it. Use after writing a Pwn exploit "
                           "with gcc/g++; rust uses cargo check.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_file": {
                        "type": "string",
                        "description": "Path to the source file to check",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language: c / cpp / rust (inferred from suffix if omitted)",
                    },
                },
                "required": ["source_file"],
            },
        },
    },
    handler=_unpack(_compile_check_impl),
    description="Syntax-check a source file and return compiler diagnostics",
)

registry.register(
    name="generate_writeup",
    toolset="ctf_solve",
    schema={
        "type": "function",
        "function": {
            "name": "generate_writeup",
            "description": "Auto-generate a CTF writeup from the current session's "
                           "solution trajectory. Returns a structured writeup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "challenge_id": {
                        "type": "string",
                        "description": "Challenge ID for the writeup",
                    },
                },
                "required": [],
            },
        },
    },
    handler=_unpack(_generate_writeup_impl),
    description="Auto-generate CTF writeup from session",
)