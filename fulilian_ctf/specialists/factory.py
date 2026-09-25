"""SpecialistFactory — 分类专家工厂。

提供注册、创建和查询专家实例的功能。

词表说明（与 ``reasoner.TaskCategory`` / 语料库同一套约定）：

- **注册表键 = 规范类别**（pwn/rev/web/crypto/forensics/misc），与
  ``TaskCategory`` 枚举值一致，``test_reasoner_category`` 把这个不变量钉死。
- **知识层用的是 "reverse"**：知识卡文件名（``knowledge.CATEGORIES``）、
  语料/``knowledge.db`` 的 category 列、题面清单都写 "reverse"。
  所以专家实例的 ``category`` 属性走知识层词表（``RevSpecialist.category
  == "reverse"``），而注册表键仍是 "rev"。

``create()`` 是外部词表进入注册表的**唯一收口**：把 "reverse" 等别名
归一成注册表键后再查表，避免反向题静默降级为 MiscSpecialist。
"""

from __future__ import annotations

import logging
from typing import Optional, Type

from .base import BaseSpecialist
from .crypto_specialist import CryptoSBeSpecialist
from .forensics_specialist import ForensicsSpecialist
from .misc_specialist import MiscSpecialist
from .pwn_specialist import PwnSpecialist
from .rev_specialist import RevSpecialist
from .web_specialist import WebSpecialist

logger = logging.getLogger(__name__)

# 外部词表 → 规范注册表键。单一收口，勿在别处再抄一份。
_CATEGORY_ALIASES: dict[str, str] = {
    "reverse": "rev",
    "reversing": "rev",
    "reverse_engineering": "rev",
    "re": "rev",
    "pwnable": "pwn",
    "binary": "pwn",
    "forensic": "forensics",
    "cryptography": "crypto",
}


class SpecialistFactory:
    """分类专家工厂。

    维护类别到专家类的映射，提供创建和注册接口。
    """

    _registry: dict[str, Type[BaseSpecialist]] = {
        "pwn": PwnSpecialist,
        "rev": RevSpecialist,
        "web": WebSpecialist,
        "crypto": CryptoSBeSpecialist,
        "forensics": ForensicsSpecialist,
        "misc": MiscSpecialist,
    }

    @classmethod
    def canonical_category(cls, category: str) -> str:
        """把外部类别词归一到注册表键（小写、连字符/空格转下划线）。

        "reverse" → "rev"；未收录的词原样返回（交由 ``create()`` 判定降级）。
        """
        key = (category or "").strip().lower().replace("-", "_").replace(" ", "_")
        return _CATEGORY_ALIASES.get(key, key)

    @classmethod
    def create(cls, category: str) -> Optional[BaseSpecialist]:
        """创建指定类别的专家实例。

        Args:
            category: 题目类别（pwn/rev/web/crypto/forensics/misc，不区分大小写；
                接受 "reverse" 等外部别名）

        Returns:
            BaseSpecialist: 专家实例；类别未注册时**降级返回 MiscSpecialist**，
            从不返回 None（调用方无需判空）。
        """
        cat = cls.canonical_category(category)
        specialist_cls = cls._registry.get(cat)
        if specialist_cls is None:
            # 静默降级曾把整类 reverse 题吞成 misc，这里留痕便于定位。
            if cat:
                logger.warning(
                    "SpecialistFactory: 未注册类别 %r（原始值 %r），降级为 MiscSpecialist",
                    cat,
                    category,
                )
            return MiscSpecialist()
        return specialist_cls()

    @classmethod
    def register(cls, category: str, specialist_cls: Type[BaseSpecialist]) -> None:
        """注册新类别专家。

        Args:
            category: 类别标识（大小写不敏感；别名会先归一到规范键）
            specialist_cls: 专家类（须继承 BaseSpecialist）
        """
        cls._registry[cls.canonical_category(category)] = specialist_cls

    @classmethod
    def list_categories(cls) -> list[str]:
        """列出所有已注册的类别。

        Returns:
            list[str]: 类别列表
        """
        return sorted(cls._registry.keys())


__all__ = ["SpecialistFactory"]