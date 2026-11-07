"""任务状态机。

纯函数：输入"当前态 + 目标态 + 守卫条件"，输出新状态或抛
:class:`IllegalTransitionError`。不读写存储、不碰租约表、不依赖
``tools.*``——持久化层的 CAS / fencing 校验属于 ``store.py``（阶段 2）。

守卫条件（三条边不是无条件的，表中存在但需要参数满足）::

    RUNNING -> QUEUED   需要 lease_expired=True        （redispatch 决定直接回收；
                                                         patrol 判死应先落 BLOCKED）
    FAILED  -> QUEUED   需要 attempts <= max_retries   （重试）
    BLOCKED -> QUEUED   需要 handoff_count < handoff_cap（回收重派不得无限次）

``max_retries`` 的语义是**允许的重试次数**，不是总执行次数：``max_retries=1``
表示"失败后再来一次"，即最多 2 次执行。``attempts`` 是已执行次数（含首次，
评审 M12），所以第 1 次失败后 ``attempts=1`` 仍可重试，第 2 次失败后
``attempts=2`` 才拒绝。

**``attempts`` 与 ``handoff_count`` 都由调用方维护，本模块只读不写：**

- ``attempts``（执行次数，含首次）：阶段 2 的 ``store.claim()`` 每次领取时
  ``+1``；``transition()`` 只读它判断能否重试，**不负责递增**；
- ``handoff_count``（持有人变更次数）：每次转手时 ``+1``。``transition()``
  把它当入参读，用于 ``BLOCKED -> QUEUED`` 的 ``handoff_cap`` 守卫，
  同样**不负责递增**；
- 不变式 ``attempts >= handoff_count + 1``（评审 M12），违反即引擎 bug。

漏掉 ``attempts`` 递增会让 ``FAILED -> QUEUED`` 变成无限循环，而本模块的
穷举测试抓不到——这正是 ``test_invariants.py`` 的
``attempts >= handoff_count + 1`` 要守的东西。``BLOCKED -> QUEUED`` 的无限
循环则由 ``handoff_cap`` 守卫在本模块内直接拦下，不依赖调用方自觉。

依赖失败的收敛路径是 ``QUEUED -> CANCELLED``（评审 M6）：下游任务不能永远
停在 QUEUED。``BLOCKED`` 的语义是"跑过、被判死或需人工决策、可回收重派"，
没跑过的任务不占这个状态位；依赖失败的原因写进 ``block_reason`` 数据列，
不新增边。

终态语义见 :func:`is_terminal`：``TERMINAL_STATES`` 表示"**本次执行**已终结"，
**不表示状态图上没有出边**——``FAILED`` 在 ``_ALLOWED`` 里仍有 ``QUEUED``
出边。判断有无出边请查 ``_ALLOWED``，不要用 ``TERMINAL_STATES`` 判空。

状态语义分工（阶段 4 的 patrol/redispatch 必须按此实现）：

- ``RUNNING`` 租约过期（进程死了 / 卡死） -> ``BLOCKED`` -> 可 redispatch，
  属**自动恢复**路径；
- 两条路径的先后：``patrol()`` 判死**只落 BLOCKED**；``RUNNING -> QUEUED`` 是
  redispatch 决策之后的回收动作，``lease_expired`` 是它的安全闸，不是 patrol 的
  第一步。混用会让同一故障既进 BLOCKED 又回 QUEUED，出现双重回收；
- ``RUNNING -> INTERRUPTED`` 用户主动中断，终结，**不自动恢复**；
- ``RUNNING -> CANCELLED`` 用户取消，终结，**不自动恢复**。

``INTERRUPTED`` 为空出边不是为了"防崩溃循环"——崩溃循环由
``BLOCKED -> QUEUED`` 的 ``handoff_cap`` 守卫兜住；它的终结理由是"用户意图
已表达，自动重跑会违背用户意图"。把崩溃误记成 INTERRUPTED 会让任务永久卡死，这是阶段 4 最容易
踩的坑。
"""

from __future__ import annotations

from agent.orchestration.contracts import TERMINAL_STATES, TaskState


class IllegalTransitionError(ValueError):
    """非法状态转移。

    消息里带 from / to / 原因，便于日志与 TUI 直接展示，不做任何静默修正。
    """

    def __init__(self, current: TaskState, target: TaskState, reason: str) -> None:
        self.current = current
        self.target = target
        self.reason = reason
        super().__init__(f"非法状态转移 {current} -> {target}：{reason}")


#: 状态转移表，逐字对应方案 §4.2。全部使用限定名（评审 M18）：裸名会 NameError
#: 或误引用，且 ``TaskState`` 与 ``TaskTier`` 混用时 key 类型校验会失效。
_ALLOWED: dict[TaskState, frozenset[TaskState]] = {
    TaskState.QUEUED: frozenset({TaskState.CLAIMED, TaskState.CANCELLED}),
    # 阶段 4：补 BLOCKED / CANCELLED 两条边。"持有者还没开跑就被打断"
    # （崩溃、停止）与 RUNNING 上的同类事件语义一致，缺边曾迫使两处绕路：
    # patrol 走 CLAIMED->FAILED->QUEUED（白耗一次重试预算），cancel 加
    # RUNNING 前置检查。补边后两处都可删。
    TaskState.CLAIMED: frozenset(
        {
            TaskState.RUNNING,
            TaskState.QUEUED,
            TaskState.FAILED,
            TaskState.BLOCKED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.RUNNING: frozenset(
        {
            TaskState.BLOCKED,
            TaskState.SUCCEEDED,
            TaskState.FAILED,
            TaskState.INTERRUPTED,
            TaskState.CANCELLED,
            TaskState.QUEUED,
        }
    ),
    TaskState.BLOCKED: frozenset(
        {TaskState.QUEUED, TaskState.CANCELLED, TaskState.FAILED}
    ),
    TaskState.FAILED: frozenset({TaskState.QUEUED}),
    TaskState.SUCCEEDED: frozenset(),
    TaskState.INTERRUPTED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


def transition(
    current: TaskState,
    target: TaskState,
    *,
    max_retries: int,
    lease_expired: bool = False,
    attempts: int = 0,
    handoff_count: int = 0,
    handoff_cap: int = 2,
) -> TaskState:
    """校验并返回目标状态。

    非法转移一律抛 :class:`IllegalTransitionError`，**不静默修正**：
    调用方拿到错就说明上游逻辑或数据有问题，掩盖它只会让问题后移。

    Args:
        current: 当前状态。
        target: 目标状态。
        max_retries: 允许的重试次数，仅影响 ``FAILED -> QUEUED``。**必传**：
            默认值朝"放行"方向偏是最危险的默认，强制调用方显式给出。
            ``max_retries=1`` → 最多 2 次执行（首次 + 1 次重试）。
        lease_expired: 租约是否已过期，仅影响 ``RUNNING -> QUEUED``。
        attempts: 已执行次数（含首次），仅影响 ``FAILED -> QUEUED``。
            由调用方维护（``store.claim()`` 每次领取 +1），本模块只读不写。
        handoff_count: 已发生的持有人变更次数，仅影响 ``BLOCKED -> QUEUED``。
            由调用方维护（每次转手 +1），本模块只读不写。
        handoff_cap: 允许的持有人变更上限，仅影响 ``BLOCKED -> QUEUED``。
            ``handoff_count >= handoff_cap`` 时拒绝，堵住
            ``RUNNING -> BLOCKED -> QUEUED`` 的无限崩溃循环。

    Returns:
        校验通过时返回 ``target``，方便链式调用。

    Raises:
        TypeError: 参数不是 :class:`TaskState`。
        IllegalTransitionError: 同态转移、终态出边、表外转移或守卫条件不满足。
    """
    if not isinstance(current, TaskState):
        raise TypeError(f"current 必须是 TaskState，收到 {type(current).__name__}")
    if not isinstance(target, TaskState):
        raise TypeError(f"target 必须是 TaskState，收到 {type(target).__name__}")

    # 幂等由调用方处理（例如"已是 SUCCEEDED 就不再写"），状态机不替它决定。
    if current is target:
        raise IllegalTransitionError(current, target, "同态转移无意义，幂等应由调用方处理")

    allowed = _ALLOWED.get(current, frozenset())
    if target not in allowed:
        if not allowed:
            raise IllegalTransitionError(current, target, "终态没有出边")
        raise IllegalTransitionError(current, target, "不在允许的转移表中")

    if current is TaskState.RUNNING and target is TaskState.QUEUED and not lease_expired:
        raise IllegalTransitionError(
            current, target, "只有租约过期（lease_expired=True）才允许回收"
        )

    if current is TaskState.FAILED and target is TaskState.QUEUED:
        # attempts 含首次，max_retries 只数"额外"的次数，所以边界是 <= 而不是 <。
        if attempts > max_retries:
            raise IllegalTransitionError(
                current,
                target,
                f"重试次数已用尽（attempts={attempts} > max_retries={max_retries}）",
            )

    if current is TaskState.BLOCKED and target is TaskState.QUEUED:
        # P0：崩溃循环兜底。没有这条守卫时 RUNNING -> BLOCKED -> QUEUED 可以
        # 无限转下去，而报错点离现场很远（只有 redispatch 一处自觉检查）。
        if handoff_count >= handoff_cap:
            raise IllegalTransitionError(
                current,
                target,
                f"转手次数已用尽（handoff_count={handoff_count} >= "
                f"handoff_cap={handoff_cap}）",
            )

    return target


def is_terminal(state: TaskState) -> bool:
    """是否处于本次执行的终态。

    ``TERMINAL_STATES`` 的语义是"本次执行已终结"，不是"状态图上没有出边"。
    ``FAILED`` 也返回 True，但 ``FAILED -> QUEUED`` 是合法边（开新 attempt），
    两者不冲突。
    """
    return state in TERMINAL_STATES


def assert_not_terminal(state: TaskState) -> None:
    """断言状态不是终态，用于"不得再推进本次执行"的调用点。

    Raises:
        IllegalTransitionError: 状态处于终态。
    """
    if is_terminal(state):
        raise IllegalTransitionError(state, state, "状态已是终态，不能再推进")
