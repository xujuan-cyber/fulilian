"""SpecialistFactory — 分类专家工厂。

提供注册、创建和查询专家实例的功能。
"""

from __future__ import annotations

from typing import Optional, Type

from .base import BaseSpecialist
from .crypto_specialist import CryptoSBeSpecialist
from .forensics_specialist import ForensicsSpecialist
from .misc_specialist import MiscSpecialist
from .pwn_specialist import PwnSpecialist
from .rev_specialist import RevSpecialist
from .web_specialist import WebSpecialist


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
    def create(cls, category: str) -> Optional[BaseSpecialist]:
        """创建指定类别的专家实例。

        Args:
            category: 题目类别（pwn/rev/web/crypto/forensics/misc，不区分大小写）

        Returns:
            BaseSpecialist | None: 专家实例，类别未注册时返回 None
        """
        cat = category.lower()
        specialist_cls = cls._registry.get(cat)
        if specialist_cls is None:
            return MiscSpecialist()
        return specialist_cls()

    @classmethod
    def register(cls, category: str, specialist_cls: Type[BaseSpecialist]) -> None:
        """注册新类别专家。

        Args:
            category: 类别标识（小写）
            specialist_cls: 专家类（须继承 BaseSpecialist）
        """
        cls._registry[category.lower()] = specialist_cls

    @classmethod
    def list_categories(cls) -> list[str]:
        """列出所有已注册的类别。

        Returns:
            list[str]: 类别列表
        """
        return sorted(cls._registry.keys())


__all__ = ["SpecialistFactory"]