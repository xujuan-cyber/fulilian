"""调度层：档位判定、只读批量采样、退避。

冻结契约：``docs/design/orchestration-phase3b-worker-decisions.md`` §三（公开
API）+ W6/W7/W8（决议）。三条载重规则：

* **W6** —— :meth:`Dispatcher.choose_tier` 默认 ``EMBEDDED`` 而非 ``INLINE``：
  ``INLINE`` 同步阻塞会把调用方卡住，而现有 ``delegate_task`` 的默认行为就是
  后台跑。
* **W7** —— :meth:`Dispatcher.sample` **只读**，不 claim、不 UPDATE。采样是调度
  决策，claim 是执行动作（``Worker.run_once`` 的事）；两者混在一起会让"采了
  不跑"变成永久占用。
* **W8** —— :class:`Backoff` 先封顶再**向下**抖动，避免多 worker 在同一时刻
  同步醒来，同时保证 ``cap`` 是硬上界。

分层：本模块只 import ``contracts`` 与 ``store``。不得 import ``tools.*``（引擎
必须能在没有旧 delegate 栈的情况下使用），也不得 import ``worker.py``
（``launcher`` 依赖 ``worker``，反向边会成环）。
"""

from __future__ import annotations

import enum
import random
import time
from dataclasses import dataclass
from typing import Callable

from agent.orchestration.contracts import Isolation, TaskCard, TaskState
from agent.orchestration.store import Store

__all__ = ["Backoff", "Dispatcher", "Tier"]

#: W7 —— 与 ``store._CLAIM_ORDER`` 逐字相同。采样顺序必须与领取顺序一致，否则
#: "先采到的任务反而后领"会让调度决策失真。两边各持一份常量（dispatcher 不
#: 依赖 store 的私有名），由 ``test_sample_order_matches_claim_order`` 钉住。
_SAMPLE_ORDER = "is_key DESC, priority DESC, bottom_level DESC, created_at ASC"

#: W7 —— 纯 SELECT。没有 BEGIN，没有 UPDATE，没有 claimed_by。
_SAMPLE_SQL = (
    "SELECT task_id FROM tasks WHERE state = ? AND pool = ? "
    f"ORDER BY {_SAMPLE_ORDER} LIMIT ?"
)


class Tier(enum.Enum):
    """worker 的**运行形态**，不是任务的执行位置（决议 §一）。

    ``Isolation`` 回答"任务在哪里跑"（父进程内 / 独立子进程），本枚举回答
    "worker 以什么形态存在"（同步 / 后台线程 / 常驻进程）。两者不是一一映射：
    ``EMBEDDED`` 与 ``INLINE`` 同属 ``Isolation.INLINE``，区别只在生命周期。
    """

    INLINE = "inline"
    EMBEDDED = "embedded"
    DAEMON = "daemon"


@dataclass(frozen=True, slots=True)
class Backoff:
    """指数退避 + 抖动（W8）。``attempt`` 从 0 起。"""

    base: float = 0.05
    cap: float = 2.0

    def delay(self, attempt: int, *, rand: Callable[[], float] = random.random) -> float:
        """第 ``attempt`` 次重试前的等待秒数。

        抖动只**向下**乘：``d = min(base * 2**attempt, cap)``，返回
        ``d * (0.5 + 0.5 * rand())``，因子落在 ``[0.5, 1.0)``。两个约束同时成立：

        * ``cap`` 是**硬上界**——返回值 ``<= cap``，调用方可以用它界定最大等待；
        * 封顶之后各 worker 的 ``d`` 相同，但乘上的因子不同，取值区间
          ``[0.5d, d]`` 仍有 2 倍跨度，不会收敛到同一点。

        之所以不向上抖（``0.5 + rand()``）：那会让上界变成 ``1.5 * cap``，
        ``cap`` 名不副实，调用方无法用它界定最大等待。
        """
        ceiling = min(self.base * (2**attempt), self.cap)
        return ceiling * (0.5 + 0.5 * rand())


class Dispatcher:
    """批量采样 + 档位判定 + 退避。**不 claim、不执行、不改状态。**"""

    def __init__(
        self,
        store: Store,
        *,
        backoff: Backoff | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        """``now`` 是冻结签名的一部分（调用方要与 ``Store`` 共用同一个时钟），
        当前**无人读**，属**预留**：阶段 4 的 ``sample(created_before=...)`` 时间
        过滤（按"任务等了多久"重派）才会用到它。本层现在是纯决策层，没有时间
        维度——采样不带时间过滤，退避由调用方 sleep。保留 ``self._now``，不要删。
        """
        self._store = store
        self._backoff = Backoff() if backoff is None else backoff
        self._now = now

    # -- W6 ----------------------------------------------------------------

    def choose_tier(self, card: TaskCard, *, requested: Tier | None = None) -> Tier:
        """决定用哪一档承载这个任务（W6）。

        ``requested`` 是调用方的显式选择，优先级最高；否则 ``PROCESS`` 隔离的
        任务交给常驻进程（daemon），其余一律 ``EMBEDDED``。

        ``card.isolation is None``（自动推断）也落到 ``EMBEDDED``：推断成
        ``PROCESS`` 是契约层 ``infer_isolation`` 的事，本层不重复推断。
        """
        if requested is not None:
            return requested
        if card.isolation is Isolation.PROCESS:
            return Tier.DAEMON
        return Tier.EMBEDDED

    # -- W7 ----------------------------------------------------------------

    def sample(self, pool: str, *, limit: int = 32) -> list[str]:
        """只读采样：返回 ``pool`` 里可领取的 ``task_id``，**不改任何状态**。

        排序与 :meth:`Store.claim` 完全一致（``is_key`` → ``priority`` →
        ``bottom_level`` → ``created_at``），所以"采到的第一个"就是"下一个会
        被领走的"。

        走 :meth:`Store.query` 做只读查询（阶段 4.5 起 ``Store`` 有公开只读
        接口，不再借 ``store._conn``）。
        ``Store`` 没有公开的只读任务查询，而自开连接要重设 WAL/busy_timeout、还会
        与写事务抢锁（``Store`` 是库的唯一持有者，D1）。阶段 3c 应给 ``Store`` 加
        公开的 ``sample_ids(pool, limit)``，届时切过去；现在加会与 ``worker-core``
        正在改的 ``store.py`` 冲突。纯 SELECT 不开事务，因此不违反 D2 的"空队列
        零写事务"。与 ``Store`` 同样要求同线程使用。
        """
        limit = int(limit)
        # LIMIT -1 在 SQLite 里是"不限"，会把整池返回；负数/零必须显式挡掉。
        if limit <= 0:
            return []
        rows = self._store.query(
            _SAMPLE_SQL, (TaskState.QUEUED.value, pool, limit)
        ).fetchall()
        return [row[0] for row in rows]

    # -- W8 ----------------------------------------------------------------

    def poll_delay(self, attempt: int) -> float:
        """下一次轮询前该等多久。纯委托，让调用方不必自己持有 ``Backoff``。"""
        return self._backoff.delay(attempt)
