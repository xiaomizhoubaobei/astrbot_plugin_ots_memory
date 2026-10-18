"""AstrBot 宿主打桩：让 ``main.py`` 在没有 AstrBot 的环境里也能被导入并测量.

为什么需要它：``main.py`` 顶部导入的是 AstrBot 宿主（``astrbot.api`` /
``astrbot.core.*``），仓库自身并不依赖它、CI 也没有装它。缺失时导入直接失败，
测试无从下手，覆盖率自然长期是 0%。

这里的桩**只补齐插件真正用到的那几个符号**，不模拟宿主全貌：

- ``FunctionTool`` / ``ContextWrapper``：支持 ``Xxx[参数]`` 下标写法（宿主里是泛型）；
- ``filter.on_decorating_result``：原样返回被装饰的函数（插件只需它可注册）；
- ``Star``：记录 ``context``，供断言工具注册。

注意：只有真实 AstrBot 不可用时才安装（``import astrbot`` 失败），装了宿主的环境
仍走真货，避免桩把真实契约盖住。
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class _SubscriptableMeta(type):
    """让桩类支持 ``Xxx[任意类型]`` 下标：宿主里那是泛型参数，桩只需可下标."""

    def __getitem__(cls, item: Any) -> Any:
        return cls


@dataclass
class _FunctionTool(metaclass=_SubscriptableMeta):
    """宿主 ``FunctionTool`` 的替身：字段与插件子类的重写保持一致.

    刻意**不用** pydantic dataclass：插件子类把 ``plugin`` 字段标注成插件类，
    桩里没有为它准备 schema，pydantic 会直接抛「无法生成 schema」。
    """

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    plugin: Optional[Any] = None


class _ContextWrapper(metaclass=_SubscriptableMeta):
    """宿主 ``ContextWrapper`` 的替身：仅作类型占位，测试不会用到它的行为."""


class _AstrMessageEvent:
    """宿主 ``AstrMessageEvent`` 的替身：插件只在装饰器签名里用到这个类型."""


@dataclass
class _ToolExecResult:
    """宿主 ``ToolExecResult`` 的替身：插件只读写 ``result`` / ``is_error``."""

    result: Any = None
    is_error: bool = False


class _Filter:
    """宿主事件过滤器装饰器的替身：注册即原样返回函数，不接事件总线."""

    @staticmethod
    def on_decorating_result() -> Any:
        """返回一个恒等装饰器."""

        def _decorator(func: Any) -> Any:
            return func

        return _decorator


class _Star:
    """宿主 ``Star`` 基类的替身：只保留 context."""

    def __init__(self, context: Any) -> None:
        self.context = context


def _module(name: str) -> types.ModuleType:
    """取（或建）一个模块并登记到 ``sys.modules``."""
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module


def _build() -> None:
    """按插件真实用到的符号搭出最小宿主（缺什么补什么，不多造）."""
    logger_stub = _module("astrbot.api.logger_stub")
    for level in ("debug", "info", "warning", "error"):
        setattr(logger_stub, level, lambda *a, **k: None)

    # ── astrbot.api ────────────────────────────────────────────────────────
    api = _module("astrbot.api")
    setattr(api, "AstrBotConfig", Dict[str, Any])
    setattr(api, "logger", logger_stub)
    setattr(api, "FunctionTool", _FunctionTool)

    # ── astrbot.api.event ──────────────────────────────────────────────────
    event = _module("astrbot.api.event")
    setattr(event, "AstrMessageEvent", _AstrMessageEvent)
    setattr(event, "filter", _Filter())
    setattr(api, "event", event)

    # ── astrbot.api.star ───────────────────────────────────────────────────
    star = _module("astrbot.api.star")
    setattr(star, "Context", Any)
    setattr(star, "Star", _Star)
    setattr(api, "star", star)

    # ── astrbot.core.* ─────────────────────────────────────────────────────
    core = _module("astrbot.core")
    agent = _module("astrbot.core.agent")
    run_context = _module("astrbot.core.agent.run_context")
    setattr(run_context, "ContextWrapper", _ContextWrapper)
    tool = _module("astrbot.core.agent.tool")
    setattr(tool, "ToolExecResult", _ToolExecResult)
    setattr(agent, "run_context", run_context)
    setattr(agent, "tool", tool)

    astr_agent_context = _module("astrbot.core.astr_agent_context")
    setattr(astr_agent_context, "AstrAgentContext", Any)
    setattr(core, "agent", agent)
    setattr(core, "astr_agent_context", astr_agent_context)


# 安装条件：真实宿主不可用才打桩（避免盖住真实契约）
try:  # pragma: no cover - 取决于环境是否装了 AstrBot
    import astrbot  # noqa: F401

    STUBBED = False
except ModuleNotFoundError:
    _build()
    STUBBED = True

__all__ = ["STUBBED"]
