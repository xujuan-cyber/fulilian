"""对手 Agent 安全监控（F3-013）。

对应功能清单 Phase 3「对手 Agent 监控：监控工具调用，异常行为告警」。
实施指南 09 未给出代码细节，这里实现为纯函数 + 可嵌入的监控器，
供 multi_agent 的监督循环与后续 Guardrail 集成复用——不侵入原生
``agent/tool_guardrails.py``，避免与上游代码冲突。

监控对象：
- 工具调用参数（analyze_tool_call）：危险命令、flag 外传、资源破坏
- solver 日志流（scan_log_for_anomalies）：反弹 shell、凭据/flag 外泄、
  自我删除等对手/失控行为模式

告警输出为结构化 dict（level + pattern + excerpt），调用方决定打印 /
写黑板 Fact / 阻断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# (severity, compiled_pattern, label) — 命中即告警
_TOOL_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("high", re.compile(r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+[\"']?/(?!tmp\b)", re.I), "destructive-rm"),
    ("high", re.compile(r"\bmkfs\b|\bdd\s+if=/dev/(zero|urandom|random)\s+of=/dev/", re.I), "destructive-dd"),
    ("high", re.compile(r"\bchmod\s+(-R\s+)?777\s+/(?!tmp\b)", re.I), "chmod-root"),
    ("high", re.compile(r"\b(curl|wget|nc|ncat|netcat)\b[^|;&]*\b(FLAG|flag)\{", re.I), "flag-exfil"),
    ("high", re.compile(r"\b(curl|wget)[^|;&]*(-d|--data|--data-raw|-F)[^|;&]*\b(build|api|hook)[^|;&]*\b(token|key|flag)", re.I), "credential-exfil"),
    ("medium", re.compile(r"\b(bash|sh|zsh|python[0-9.]*)\s+-c\b[^;]*(/dev/tcp|socket\.socket|pty\.spawn)", re.I), "reverse-shell"),
    ("medium", re.compile(r"\bnc\s+-e\b|\bncat\s+-e\b", re.I), "nc-backconnect"),
    ("medium", re.compile(r"\bcurl\b[^|;&]*\|\s*(bash|sh|zsh)\b", re.I), "pipe-to-shell"),
    ("medium", re.compile(r"\b(history\s+-c|shred\s+/|wipefs\b)", re.I), "anti-forensics"),
    ("medium", re.compile(r"\b(ssh-keygen|sshpass|ssh)\b[^|;&]*@(?!localhost|127\.0\.0\.1)", re.I), "outbound-ssh"),
]

_LOG_PATTERNS: list[tuple[str, re.Pattern, str]] = _TOOL_PATTERNS + [
    ("medium", re.compile(r"\bflag\{[^}]{4,}\}.*(sent|posted|uploaded|submit).*(http|server)", re.I), "flag-exfil-log"),
    ("medium", re.compile(r"base64\s+-d\s*<<<\s*[A-Za-z0-9+/=]{200,}"), "obfuscated-payload"),
]


@dataclass
class Alert:
    """一条异常行为告警。"""

    level: str        # "high" | "medium"
    label: str        # 模式标签
    source: str = ""  # 来源（explorer-0 / tool:bash ...）
    excerpt: str = "" # 命中片段（截断）

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "label": self.label,
            "source": self.source,
            "excerpt": self.excerpt,
        }


@dataclass
class OpponentMonitor:
    """监控器：累计告警 + 可选回调（打印 / 写黑板）。"""

    source: str = ""
    alerts: list = field(default_factory=list)
    on_alert: object = None  # Optional[Callable[[Alert], None]]

    def check_text(self, text: str) -> list[Alert]:
        """检查一段文本（工具参数或日志），命中即记录并返回新告警。"""
        new = []
        for level, pattern, label in _LOG_PATTERNS:
            m = pattern.search(text)
            if m:
                alert = Alert(
                    level=level,
                    label=label,
                    source=self.source,
                    excerpt=m.group(0)[:200],
                )
                self.alerts.append(alert)
                new.append(alert)
        if new and self.on_alert:
            for a in new:
                try:
                    self.on_alert(a)
                except Exception:  # noqa: BLE001 — 告警回调不影响检查
                    pass
        return new


def analyze_tool_call(tool_name: str, args: str) -> list[Alert]:
    """分析一次工具调用（F3-013 主入口，可接 GuardrailController.after/before）。

    Args:
        tool_name: 工具名（如 "bash" / "write_file"）
        args: 参数文本（命令行 / 写入内容）

    Returns:
        list[Alert]: 告警（可能为空）
    """
    monitor = OpponentMonitor(source=f"tool:{tool_name}")
    return monitor.check_text(str(args or ""))


def scan_log_for_anomalies(text: str, source: str = "") -> list[Alert]:
    """扫描日志/输出中的异常行为模式。"""
    monitor = OpponentMonitor(source=source)
    return monitor.check_text(text or "")


__all__ = [
    "Alert",
    "OpponentMonitor",
    "analyze_tool_call",
    "scan_log_for_anomalies",
]
