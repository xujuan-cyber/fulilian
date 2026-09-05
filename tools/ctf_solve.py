"""CTF solver tools — verify_flag, submit_flag, record_fact, git_auto_commit, compile_check, http_session.

Registered in the ``ctf_solve`` toolset.
- Phase 1: verify_flag (flag 校验门), submit_flag（声明式提交）, record_fact, git_auto_commit.
- F4-008: compile_check（编译诊断）.
- P2-3(部分): http_session（web 题跨调用 HTTP 会话保持）.
"""

from __future__ import annotations

import inspect
import json
import os
import re
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

def _bound_work_dir(work_dir: str) -> str | None:
    """统一 work_dir 边界校验（H-2）。

    返回规范化后的合法路径；非法/越界返回 None。
    FULILIAN_CTF_WORK_DIR 未绑定时只做基本合法性检查（保持单题直调兼容）。
    绑定时与规范化后的绑定路径**严格相等**才放行（子目录也拒绝，
    与 _git_auto_commit_impl 原实现语义一致，不许放松）。
    """
    if not work_dir or not isinstance(work_dir, str):
        return None
    resolved = Path(work_dir).expanduser().resolve()
    bound = os.environ.get("FULILIAN_CTF_WORK_DIR")
    if bound:
        allowed = Path(bound).expanduser().resolve()
        if resolved != allowed:
            return None
    return str(resolved)


def _llm_negator(candidate: str, evidence: str, parent_agent) -> bool:
    """Ask a leaf skeptic; fail closed unless it explicitly supports the flag."""
    import re
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
    # Only parse the first line (or first sentence), ignore subsequent explanations
    first_line = text.split("\n")[0].strip()
    first_sentence = re.split(r"(?<=[.!?])\s+", first_line)[0] if first_line else first_line
    upper = first_sentence.upper()
    # Use word-boundary matching to avoid substring false positives
    if re.search(r"\bREBUT\b", upper) or re.search(r"\bREJECT\b", upper) or re.search(r"\bHALLUCIN\b", upper):
        return True
    # Fail-closed: return True (reject) unless a clear PASS/CONFIRMED/SUPPORTED token is found
    return not (re.search(r"\bPASS\b", upper) or re.search(r"\bCONFIRMED\b", upper) or re.search(r"\bSUPPORTED\b", upper))


def _verify_flag_impl(candidate: str, evidence: str = "", parent_agent=None) -> str:
    """Verify a flag candidate through the triple-verification gate."""
    from fulilian_ctf.verify import VerificationResult, verify_flag

    negator = None
    if parent_agent is not None:
        negator = lambda c, e: _llm_negator(c, e, parent_agent)
    result = verify_flag(candidate, evidence, negator=negator)
    return f"verify_flag: candidate={candidate!r} → {result.value}"


def _submit_flag_impl(work_dir: str) -> str:
    """声明式提交：只提交 FLAG 文件中的候选，提交前走 flag 校验门。

    门语义（P2-5 诚实声明）：grounding + 规则对抗门 + 格式门；对抗门为
    规则实现（结构校验），LLM 怀疑者 negator 未接线（可选层，见
    fulilian_ctf/verify.py 模块 docstring）。

    Agent 必须先在工作区写入 FLAG 文件，本工具才会读取并提交。
    """
    work_dir = _bound_work_dir(work_dir)
    if work_dir is None:
        return "submit_flag: work_dir is outside the bound CTF workspace"

    flag_file = Path(work_dir) / FLAG_FILENAME

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

    # 走 flag 校验门（声明式提交路径：无工具输出作证据，require_grounding=False；
    # 对抗门为规则实现，LLM negator 未接线——见 P2-5）
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
    work_dir = _bound_work_dir(work_dir)
    if work_dir is None:
        return "record_fact: work_dir is outside the bound CTF workspace"
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
    bound = _bound_work_dir(work_dir)
    if bound is None:
        return "git_auto_commit: work_dir is outside the bound CTF workspace"
    work_dir = bound
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

            # 创建 .gitignore 排除大文件和不必要的构建产物
            gitignore_path = work_path / ".gitignore"
            if not gitignore_path.exists():
                gitignore_content = (
                    "solver.log\n"
                    "__pycache__/\n"
                    "*.pyc\n"
                    ".DS_Store\n"
                    ".http_sessions/\n"
                )
                gitignore_path.write_text(gitignore_content)

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


# ── 工具注册 ─────────────────────────────────────────────────────────
# M-5：原 checkpoint / generate_writeup 两个 stub 工具已移除——它们对真实
# 调用返回假成功文本（"(Phase 2/3 stub)"），浪费 agent 轮次。真实 checkpoint
# 能力在 tools/checkpoint_manager.py（接线属 P2 决策项）。

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


# ── http_session：web 题跨调用 HTTP 会话保持（P2-3 部分，ctf_solve 扩展）──
#
# 会话（cookies/自定义 headers）落盘到 work_dir/.http_sessions/<sid>.json，
# 跨工具调用保持登录态/会话连续性；进程重启不要求保留——文件在即续用，
# 删除即新会话。响应 body 截断到上限（FULILIAN_HTTP_BODY_LIMIT，默认 4000
# 字符），防止大响应爆上下文。work_dir 边界校验与 submit_flag 同口径（P0-4）。

HTTP_SESSION_DIR = ".http_sessions"
HTTP_DEFAULT_BODY_LIMIT = 4000


def _new_session():
    """requests.Session 工厂（单测 monkeypatch 点，不打真实网络的替换入口）。"""
    import requests

    return requests.Session()


def _http_body_limit() -> int:
    try:
        return max(200, int(os.environ.get("FULILIAN_HTTP_BODY_LIMIT")
                            or HTTP_DEFAULT_BODY_LIMIT))
    except (TypeError, ValueError):
        return HTTP_DEFAULT_BODY_LIMIT


def _session_file(work_dir: str, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "default") or "default"
    return Path(work_dir) / HTTP_SESSION_DIR / f"{safe}.json"


def _load_session(path: Path):
    session = _new_session()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            session.headers.update(data.get("headers") or {})
            for c in data.get("cookies") or []:
                session.cookies.set(c["name"], c["value"],
                                    domain=c.get("domain") or "",
                                    path=c.get("path") or "/")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass  # 会话文件损坏 → 视为新建会话（不阻断求解）
    return session


def _save_session(path: Path, session) -> None:
    from fulilian_ctf.relay import atomic_write_text

    try:
        cookies = [
            {"name": c.name, "value": c.value,
             "domain": getattr(c, "domain", "") or "",
             "path": getattr(c, "path", "") or "/"}
            for c in session.cookies
        ]
        atomic_write_text(path, json.dumps(
            {"headers": dict(session.headers), "cookies": cookies},
            ensure_ascii=False, indent=2))
    except Exception:  # noqa: BLE001 — 会话落盘失败不阻断请求本身
        pass


def _parse_header_text(headers_text: str) -> dict:
    headers = {}
    for line in (headers_text or "").splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            if key.strip():
                headers[key.strip()] = value.strip()
    return headers


def _summarize_response_headers(headers) -> list:
    interesting = ("content-type", "location", "server", "set-cookie",
                   "www-authenticate")
    return [f"{k}: {str(v)[:200]}" for k, v in headers.items()
            if k.lower() in interesting]


def _http_session_impl(work_dir: str, action: str = "request",
                       session_id: str = "default", method: str = "GET",
                       url: str = "", headers: str = "", data: str = "",
                       timeout: int = 10, allow_redirects: bool = True) -> str:
    """web 题跨调用 HTTP 会话保持。

    action:
      - "request"（默认）：用命名会话发一次请求（会话不存在则惰性创建），
        响应 Set-Cookie 自动延续到后续调用并落盘。
      - "close"：丢弃该命名会话（删除落盘状态），下次 request 从新会话开始。
    """
    work_dir = _bound_work_dir(work_dir)
    if work_dir is None:
        return "http_session: work_dir is outside the bound CTF workspace"
    session_file = _session_file(work_dir, session_id)

    if action == "close":
        try:
            session_file.unlink(missing_ok=True)
        except OSError as e:
            return f"http_session: failed to close session: {e}"
        return f"http_session: session {session_id!r} closed"
    if action != "request":
        return f"http_session: unknown action {action!r} (use 'request' or 'close')"
    if not url:
        return "http_session: url is required for action='request'"

    session = _load_session(session_file)
    try:
        resp = session.request(
            method=(method or "GET").upper(), url=url,
            headers=_parse_header_text(headers) or None,
            data=data or None,
            timeout=max(1, int(timeout or 10)),
            allow_redirects=bool(allow_redirects),
        )
    except Exception as e:  # noqa: BLE001 — 网络失败返回错误文本，不抛
        _save_session(session_file, session)  # 已建立的会话状态仍保留
        return f"http_session: request failed: {e}"
    _save_session(session_file, session)

    limit = _http_body_limit()
    body = resp.text or ""
    truncated = len(body) > limit
    if truncated:
        body = body[:limit]
    lines = [f"status: {resp.status_code}", f"url: {resp.url}"]
    lines.extend(f"header: {h}" for h in _summarize_response_headers(resp.headers))
    lines.append(f"body{' (truncated at %d chars, use range/partial GET for more)' % limit
                 if truncated else ''}:")
    lines.append(body)
    return "\n".join(lines)


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
    name="http_session",
    toolset="ctf_solve",
    schema={
        "type": "function",
        "function": {
            "name": "http_session",
            "description": "Stateful HTTP client for web challenges: keeps cookies/session "
                           "across calls (persisted per challenge workspace). Use "
                           "action='request' with method/url (extra headers/data optional); "
                           "action='close' drops the session. Response body is truncated to a "
                           "cap (FULILIAN_HTTP_BODY_LIMIT, default 4000 chars) — use range "
                           "requests or targeted endpoints for large responses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_dir": {
                        "type": "string",
                        "description": "Challenge workspace directory (session state is "
                                       "persisted here)",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["request", "close"],
                        "description": "request (default) = send an HTTP request with the "
                                       "named session; close = drop the named session",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Named session (default 'default') — use separate ids "
                                       "to keep parallel logins apart",
                    },
                    "method": {
                        "type": "string",
                        "description": "HTTP method (default GET)",
                    },
                    "url": {
                        "type": "string",
                        "description": "Absolute URL to request (required for action=request)",
                    },
                    "headers": {
                        "type": "string",
                        "description": "Extra request headers, one 'Name: value' per line",
                    },
                    "data": {
                        "type": "string",
                        "description": "Raw request body (e.g. urlencoded or JSON text)",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Request timeout in seconds (default 10)",
                    },
                    "allow_redirects": {
                        "type": "boolean",
                        "description": "Follow redirects (default true)",
                    },
                },
                "required": ["work_dir"],
            },
        },
    },
    handler=_unpack(_http_session_impl),
    description="Persistent HTTP session for web challenges",
)