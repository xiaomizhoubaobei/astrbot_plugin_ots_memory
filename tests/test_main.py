"""``main.py`` 工具层单元测试（依赖 AstrBot 宿主）.

背景：本仓库此前的单测只覆盖不依赖宿主的 ``client.py``，``main.py`` 因无法
import 宿主而长期 0% 覆盖，反而掩盖了两个真实缺陷：

1. 工具 dataclass 上的 ``plugin`` 字段若标注为插件类本身，pydantic 会在**实例化
   工具**时抛 ``PydanticSchemaGenerationError``（宿主 ``FunctionTool`` 未开启
   ``arbitrary_types_allowed``）——即插件注册的 Tool 根本造不出来；
2. 返回值写法 ``ToolExecResult(is_error=True, ...)`` 在宿主把 ``ToolExecResult``
   改成 ``str | CallToolResult`` 联合别名后**不可调用**，抛
   ``TypeError: 'types.UnionType' object is not callable``。

本文件把「工具可实例化 + 各分支返回形状正确」固化成回归用例。宿主由
``requirements-dev.txt`` 安装，故这些用例在 CI 中始终可运行。
"""

from __future__ import annotations

from typing import Any

import pytest
from astrbot_plugin_ots_memory.main import RecallMemoryTool, SaveMemoryTool


class _FakeClient:
    """替身客户端：按预设返回 / 抛错，隔离真实网络调用."""

    def __init__(
        self,
        *,
        memories: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._memories = memories or []
        self._error = error
        self.added: list[dict[str, Any]] = []

    async def search_memories(self, **kwargs: Any) -> list[dict[str, Any]]:
        if self._error:
            raise self._error
        return self._memories

    async def add_memories(self, **kwargs: Any) -> None:
        if self._error:
            raise self._error
        self.added.append(kwargs)


class _FakePlugin:
    """只提供 Tool 需要的属性，避免构造完整 Star 实例."""

    store_name = "store"
    app_id = "app"
    tenant_id = "default"
    top_k = 5
    min_score = 0.4

    def __init__(self, client: Any = None) -> None:
        self.client = client


def _text(result: Any) -> str:
    """取出 CallToolResult 里的首段文本."""
    return result.content[0].text


# ── 实例化契约（回归 1：pydantic 建模） ────────────────────────────────────


def test_tools_can_be_instantiated() -> None:
    """工具必须能在不注入 plugin 的情况下实例化（回归 PydanticSchemaGenerationError）."""
    assert RecallMemoryTool().name == "recall_memory"
    assert SaveMemoryTool().name == "save_memory"


def test_plugin_ref_is_bound_and_excluded_from_schema() -> None:
    """plugin 引用要能绑定，且不进入工具参数 schema / 序列化结果."""
    plugin = _FakePlugin()
    tool = RecallMemoryTool(plugin=plugin)
    assert tool.plugin is plugin
    assert "plugin" not in tool.parameters.get("properties", {})


# ── 参数校验 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tool_cls", "kwargs", "expected"),
    [
        (RecallMemoryTool, {"query": "   "}, "query 参数不能为空"),
        (SaveMemoryTool, {"fact": "  "}, "fact 参数不能为空"),
    ],
)
async def test_blank_argument_rejected(
    tool_cls: type, kwargs: dict[str, str], expected: str
) -> None:
    result = await tool_cls(plugin=_FakePlugin(_FakeClient())).call(None, **kwargs)
    assert result.isError is True
    assert _text(result) == expected


# ── 客户端未初始化 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tool_cls", "kwargs"),
    [(RecallMemoryTool, {"query": "x"}), (SaveMemoryTool, {"fact": "x"})],
)
async def test_missing_client_reports_error(
    tool_cls: type, kwargs: dict[str, str]
) -> None:
    """配置不全时 client 为 None，工具应回友好错误而不是崩栈."""
    result = await tool_cls(plugin=_FakePlugin(None)).call(None, **kwargs)
    assert result.isError is True
    assert "未初始化" in _text(result)


# ── recall_memory 正常 / 空结果 / 异常 ────────────────────────────────────


async def test_recall_memory_formats_hits() -> None:
    client = _FakeClient(memories=[{"unit": {"text": "用户喜欢梅花"}, "score": 0.87}])
    result = await RecallMemoryTool(plugin=_FakePlugin(client)).call(None, query="喜好")
    assert result.isError is False
    assert "用户喜欢梅花" in _text(result)
    assert "0.87" in _text(result)


async def test_recall_memory_empty_result() -> None:
    result = await RecallMemoryTool(plugin=_FakePlugin(_FakeClient())).call(
        None, query="喜好"
    )
    assert result.isError is False
    assert _text(result) == "没有找到相关的历史记忆。"


async def test_recall_memory_error_is_wrapped() -> None:
    client = _FakeClient(error=RuntimeError("boom"))
    result = await RecallMemoryTool(plugin=_FakePlugin(client)).call(None, query="x")
    assert result.isError is True
    assert "检索记忆失败" in _text(result)


# ── save_memory 正常 / 异常 ───────────────────────────────────────────────


async def test_save_memory_success() -> None:
    client = _FakeClient()
    result = await SaveMemoryTool(plugin=_FakePlugin(client)).call(
        None, fact="用户喜欢梅花"
    )
    assert result.isError is False
    assert _text(result) == "已保存记忆：用户喜欢梅花"
    assert client.added and client.added[0]["text"] == "用户喜欢梅花"


async def test_save_memory_error_is_wrapped() -> None:
    client = _FakeClient(error=RuntimeError("boom"))
    result = await SaveMemoryTool(plugin=_FakePlugin(client)).call(None, fact="x")
    assert result.isError is True
    assert "保存记忆失败" in _text(result)
