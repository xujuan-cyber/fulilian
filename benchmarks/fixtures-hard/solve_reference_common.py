"""难题 holdout 的公共约定。

为什么不复用 `benchmarks/fixtures/` 的 solve_reference 约定：那批是 easy
单元语料，2 步解完，且**被调过**——它的数字已经不能再用来衡量"难不难"。
难题 holdout 放在独立目录，是为了让"这个基准没被针对性地改过"这件事
一眼可查（`git log benchmarks/fixtures-hard/` 应当只有新增，没有调参）。

每个难题 fixture 必须提供：
  SOLUTION_STEPS  参考解的最少步骤数。**它是难度的代理指标**，也是
                  验收时的分母：solver 用了 3 倍于参考解的 api_calls，
                  即使解出也说明路径不经济。
  solve(work_dir) -> str   参考解。返回的字符串**必须包含 flag 本身**，
                  供 `--manifest` 逐字比对；同时应包含足够的中间输出，
                  供人工复核"它确实是这么解出来的"。
"""

from __future__ import annotations

from pathlib import Path


def find_flag(text: str) -> str:
    """从一段文本里抽出 flag{...} / NSSCTF{...} 等常见包裹。

    刻意不写死前缀列表：holdout 的 flag 形态可以变，但"最后一个大括号
    片段"这条规则对本题面稳定，且失效时会显式报错而不是静默返回 None。
    """
    import re

    m = re.findall(r"\b([A-Za-z0-9_]{2,16})\{([^}]{1,200})\}", text)
    if not m:
        raise SystemExit("参考解没找到 flag —— fixture 有问题，不是 solver 的问题")
    prefix, body = m[-1]
    return f"{prefix}{{{body}}}"


def read_text(work_dir: str, name: str) -> str:
    return (Path(work_dir) / name).read_text(encoding="utf-8", errors="replace")
