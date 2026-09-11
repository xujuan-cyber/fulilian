"""CTFd 平台对接（F3-011 / F3-012）。

对应实施指南 09-P3-高级功能.md §9.5。三块能力：

1. **CTFdAdapter** — CTFd API 封装（list/get/submit），指南原样实现
   （``/api/v1/challenges`` 系列端点，``Token`` 认证）。
2. **新题同步与轮询（F3-011）** — ``sync_challenges`` 把 CTFd 题目导出为
   步骤 05 调度引擎可消费的 manifest（``registry.load_challenges`` 兼容
   格式，``fulilian solve-all <dir>`` 直接可跑）；``poll_new_challenges``
   检测新题；``create_poll_job`` 复用 Fulilian cron 创建定时任务
   （``cron.jobs.create_job``，"every 5m" 间隔），到点自动轮询 + spawn
   solver——指南的 ``fulilian cron create --schedule "every 5m"`` 通路。
3. **MCP 对接（F3-012）** — 自包含的 stdio MCP server（JSON-RPC 2.0：
   initialize / tools/list / tools/call），暴露 ctfd_list_challenges /
   ctfd_get_challenge / ctfd_submit_flag 三个 tool。不依赖原生 MCP
   客户端栈，避免与 Fulilian 的 mcp 子系统冲突；任何 MCP client
   （``fulilian mcp add``）均可按 stdio 协议接入。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import requests

# MCP server 的默认配置来源（环境变量）
ENV_CTFD_BASE_URL = "CTFD_BASE_URL"
ENV_CTFD_API_KEY = "CTFD_API_KEY"


class CTFdError(RuntimeError):
    """CTFd API 错误（非 2xx / 响应格式异常）。"""


class CTFdAdapter:
    """CTFd API 封装（指南 §9.5 原样 + 超时与错误信息增强）。"""

    def __init__(self, base_url: str, api_key: str = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = float(timeout)
        self.session = requests.Session()
        if api_key:
            self.session.headers["Authorization"] = f"Token {api_key}"

    def list_challenges(self) -> list[dict]:
        """获取题目列表。"""
        resp = self.session.get(
            f"{self.base_url}/api/v1/challenges", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def get_challenge(self, challenge_id: int) -> dict:
        """获取题目详情。"""
        resp = self.session.get(
            f"{self.base_url}/api/v1/challenges/{challenge_id}",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    def submit_flag(self, challenge_id: int, flag: str) -> dict:
        """提交 flag。"""
        resp = self.session.post(
            f"{self.base_url}/api/v1/challenges/attempt",
            json={"challenge_id": challenge_id, "submission": flag},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


# ── manifest 同步（对接 Phase 2 调度引擎）────────────────────────────────


def _as_int(value, default: int = 0) -> int:
    """尽力把 CTFd 字段转 int（转不动就退回默认值）。

    CTFd 的 ``value`` 是选手可填的字符串：``"100"`` 正常，但 ``"100 分"``、
    ``"N/A"``、``"1000.0"`` 都出现过。裸 ``int()`` 遇上一个就把整个 sync
    打挂（一道烂题废掉整场比赛的同步），而分值本来就是可选信息 ——
    宁可退回默认值。
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default


def _entry_from_ctfd(item: dict, detail: dict = None) -> dict:
    """CTFd 题目 → registry.load_challenges 兼容条目。

    registry 规范：id 必填、difficulty/score/target_port 数值化。
    连接信息从 detail 的 connection_info 解析（host:port）。
    """
    detail = detail or {}
    entry = {
        "id": f"ctfd-{item.get('id', '')}",
        "title": str(item.get("name") or detail.get("name") or ""),
        "category": str(item.get("category") or detail.get("category") or "misc").lower(),
        "score": _as_int(item.get("value") or detail.get("value") or 0),
        "description": str(detail.get("description") or ""),
    }
    # 难度映射：CTFd 无难度字段，按分值粗分（与 DIFFICULTY_FACTORS 对齐）
    score = entry["score"]
    entry["difficulty"] = "easy" if score <= 100 else ("medium" if score <= 500 else "hard")

    conn = str(detail.get("connection_info") or "")
    m = None
    import re

    m = re.search(r"([a-zA-Z0-9._-]+):(\d+)", conn)
    if m:
        entry["target_host"] = m.group(1)
        entry["target_port"] = int(m.group(2))
    return entry


def sync_challenges(
    adapter: CTFdAdapter, out_dir: str | Path
) -> list[dict]:
    """把 CTFd 全部题目同步为本地 manifest（供 ``fulilian solve-all``）。

    产出结构（registry.load_challenges 目录模式兼容）：
        out_dir/manifest.json          # {"challenges": [...]}
        out_dir/challenges/<id>/challenge.json

    Returns:
        list[dict]: 写入 manifest 的条目
    """
    out_dir = Path(out_dir)
    entries: list[dict] = []
    for item in adapter.list_challenges():
        cid = item.get("id")
        detail = {}
        try:
            detail = adapter.get_challenge(int(cid))
        except (requests.RequestException, ValueError, CTFdError):
            detail = {}  # 详情拉取失败降级为列表信息
        entries.append(_entry_from_ctfd(item, detail))

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(
        json.dumps({"challenges": entries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    ch_dir = out_dir / "challenges"
    ch_dir.mkdir(exist_ok=True)
    for e in entries:
        d = ch_dir / str(e["id"])
        d.mkdir(exist_ok=True)
        (d / "challenge.json").write_text(
            json.dumps(e, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return entries


# ── 新题轮询（F3-011）─────────────────────────────────────────────────────


def poll_new_challenges(
    adapter: CTFdAdapter, state_file: str | Path
) -> list[dict]:
    """检测 CTFd 新题（相对上次记录），返回新题并更新状态文件。

    状态文件记录已见题目 ID（JSON 列表）；首次运行视为「全为新题」。
    """
    state_file = Path(state_file)
    seen: set[str] = set()
    if state_file.is_file():
        try:
            seen = set(json.loads(state_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            seen = set()

    items = adapter.list_challenges()
    new = [
        item
        for item in items
        if str(item.get("id", "")) not in seen
    ]
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(
                sorted(seen | {str(i.get("id", "")) for i in items}),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
    return new


def create_poll_job(
    base_url: str,
    api_key: str,
    platform_dir: str | Path,
    schedule: str = "every 5m",
    name: str = "ctfd-poll",
) -> dict:
    """创建 CTFd 轮询 cron 任务（复用 Fulilian cron，F3-011）。

    任务 prompt 自包含：轮询新题 → 有新题则同步 manifest → 批量求解。
    需 gateway 进程在运行（cron ticker 由 gateway 驱动）。

    Returns:
        dict: create_job 返回的任务（含 id/next_run_at）
    """
    from cron.jobs import create_job

    platform_dir = str(Path(platform_dir).expanduser())
    prompt = (
        f"CTFd 轮询：用环境变量 CTFD_BASE_URL={base_url} 的 CTFdAdapter 检测新题"
        f"（状态文件 {platform_dir}/poll-state.json）。"
        f"若有新题：同步 manifest 到 {platform_dir} 后执行 "
        f"`fulilian solve-all {platform_dir}`；无新题则结束。"
    )
    return create_job(
        prompt=prompt,
        schedule=schedule,
        name=name,
        repeat=None,       # 永久循环
        deliver="local",
    )


# ── MCP server（F3-012）───────────────────────────────────────────────────

_MCP_PROTOCOL_VERSION = "2024-11-05"

_MCP_TOOLS = [
    {
        "name": "ctfd_list_challenges",
        "description": "List all challenges from a CTFd platform",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "ctfd_get_challenge",
        "description": "Get details of one CTFd challenge",
        "inputSchema": {
            "type": "object",
            "properties": {
                "challenge_id": {"type": "integer", "description": "CTFd challenge ID"}
            },
            "required": ["challenge_id"],
        },
    },
    {
        "name": "ctfd_submit_flag",
        "description": "Submit a flag to a CTFd challenge",
        "inputSchema": {
            "type": "object",
            "properties": {
                "challenge_id": {"type": "integer"},
                "flag": {"type": "string"},
            },
            "required": ["challenge_id", "flag"],
        },
    },
]


def _adapter_from_env() -> CTFdAdapter:
    import os

    base_url = os.environ.get(ENV_CTFD_BASE_URL, "").strip()
    if not base_url:
        raise CTFdError(
            f"MCP ctfd server requires {ENV_CTFD_BASE_URL} (and optionally "
            f"{ENV_CTFD_API_KEY}) environment variables"
        )
    return CTFdAdapter(base_url, os.environ.get(ENV_CTFD_API_KEY) or None)


def mcp_call_tool(name: str, arguments: dict, adapter: Optional[CTFdAdapter] = None) -> dict:
    """执行一个 MCP tool 调用（独立函数，可单测）。

    网络/API 异常包装为 CTFdError（MCP 层以 isError=true 的 tool 结果
    返回，而不是协议级错误）。
    """
    adapter = adapter or _adapter_from_env()
    try:
        if name == "ctfd_list_challenges":
            return {"challenges": adapter.list_challenges()}
        if name == "ctfd_get_challenge":
            return {"challenge": adapter.get_challenge(int(arguments["challenge_id"]))}
        if name == "ctfd_submit_flag":
            return {
                "result": adapter.submit_flag(
                    int(arguments["challenge_id"]), str(arguments["flag"])
                )
            }
    except (KeyError, ValueError) as e:
        raise CTFdError(f"invalid arguments for {name}: {e}") from e
    except requests.RequestException as e:
        raise CTFdError(f"ctfd api error: {e}") from e
    raise CTFdError(f"unknown tool: {name}")


def _handle_rpc_request(msg: dict, adapter: Optional[CTFdAdapter] = None) -> Optional[dict]:
    """处理一条 JSON-RPC 请求（MCP stdio 协议核心，独立函数可单测）。"""
    method = msg.get("method", "")
    msg_id = msg.get("id")

    def _ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _err(code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    try:
        if method == "initialize":
            return _ok(
                {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fulilian-ctfd", "version": "0.1.0"},
                }
            )
        if method == "notifications/initialized":
            return None  # notification：不回复
        if method == "tools/list":
            return _ok({"tools": _MCP_TOOLS})
        if method == "tools/call":
            params = msg.get("params") or {}
            name = str(params.get("name", ""))
            arguments = params.get("arguments") or {}
            try:
                data = mcp_call_tool(name, arguments, adapter=adapter)
            except CTFdError as e:
                return _ok(
                    {
                        "content": [{"type": "text", "text": str(e)}],
                        "isError": True,
                    }
                )
            return _ok(
                {
                    "content": [
                        {"type": "text", "text": json.dumps(data, ensure_ascii=False)}
                    ]
                }
            )
        if method == "ping":
            return _ok({})
        return _err(-32601, f"method not found: {method}")
    except Exception as e:  # noqa: BLE001 — 任何异常都返回 JSON-RPC error
        return _err(-32603, f"internal error: {type(e).__name__}: {e}")


def serve_mcp(adapter: Optional[CTFdAdapter] = None) -> int:
    """stdio MCP server 主循环（F3-012 入口）。

    每行一个 JSON-RPC 消息；EOF 正常退出。与 ``fulilian mcp add`` 的
    stdio server 约定兼容（stdout 只输出协议消息，日志走 stderr）。
    """
    print("fulilian-ctfd MCP server ready (stdio)", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"parse error: {e}"},
            }
        else:
            resp = _handle_rpc_request(msg, adapter=adapter)
        if resp is not None:
            print(json.dumps(resp, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(serve_mcp())


__all__ = [
    "CTFdAdapter",
    "CTFdError",
    "create_poll_job",
    "mcp_call_tool",
    "poll_new_challenges",
    "serve_mcp",
    "sync_challenges",
]
