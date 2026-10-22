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

import asyncio
import inspect
from typing import Any

import pytest
from astrbot_plugin_ots_memory.client import OTSMemoryClient
from astrbot_plugin_ots_memory.main import (
    OTSMemoryPlugin,
    RecallMemoryTool,
    SaveMemoryTool,
)


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


async def test_tool_result_does_not_echo_exception_text(monkeypatch) -> None:
    """工具返回值只给固定提示，不得回显异常文本（可能夹带上游响应体）."""
    from astrbot_plugin_ots_memory import main as main_mod

    leaky = RuntimeError("OTS 接口错误 [status=400] 用户记忆原文")

    monkeypatch.setattr(main_mod.logger, "error", lambda *a, **k: None)
    monkeypatch.setattr(main_mod.logger, "warning", lambda *a, **k: None)

    recall = await RecallMemoryTool(plugin=_FakePlugin(_FakeClient(error=leaky))).call(
        None, query="x"
    )
    assert "用户记忆原文" not in _text(recall)

    save = await SaveMemoryTool(plugin=_FakePlugin(_FakeClient(error=leaky))).call(
        None, fact="x"
    )
    assert "用户记忆原文" not in _text(save)


# ── 插件本体：构造、Tool 注册与自动沉淀（不阻塞后台任务） ────────────────────
#
# 说明：此前的用例只覆盖 Tool 的 call 分支，插件本体（__init__ 与
# on_after_reply）完全没被执行。下面的用例一律 **真实构造** OTSMemoryPlugin：
# 宿主 Star 只依赖一个 context 对象，唯一的外部副作用是 add_llm_tools（把工具
# 塞进宿主的 Tool 管理器），故用一个只记录调用的替身 context 即可，不需要
# patch 被测代码本身。

_FULL_CONFIG = {
    "endpoint": "https://bot.cn-shanghai.tablestore.aliyuncs.com",
    "instance_name": "bot",
    "access_key_id": "LTAI_test_ak",
    "access_key_secret": "test_secret",
    "region": "cn-shanghai",
    "memory_store_name": "store",
    "app_id": "app",
    "top_k": 3,
    "min_score": 0.5,
    "auto_record": True,
}


class _FakeContext:
    """只记录注册了哪些 Tool 的宿主 Context 替身."""

    def __init__(self) -> None:
        self.tools: list[Any] = []

    def add_llm_tools(self, *tools: Any) -> None:
        self.tools.extend(tools)


class _Seg:
    def __init__(self, text: str | None) -> None:
        self.text = text


class _Result:
    def __init__(self, chain: list[Any]) -> None:
        self.chain = chain


class _FakeEvent:
    """只实现 on_after_reply 用到的两个取值入口."""

    def __init__(self, messages: list[Any], result: Any) -> None:
        self._messages = messages
        self._result = result

    def get_messages(self) -> list[Any]:
        return self._messages

    def get_result(self) -> Any:
        return self._result


async def _drain_tasks() -> None:
    """把 create_task 派生的后台沉淀任务跑完，避免用例结束后残留任务."""
    pending = [
        task for task in asyncio.all_tasks() if task is not asyncio.current_task()
    ]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _make_plugin(config: dict[str, Any] | None = None) -> tuple[Any, _FakeContext]:
    """构造真实插件实例。

    config 传入普通 dict：``AstrBotConfig`` 构造第一参是配置文件**路径**，
    直接塞 dict 会报 stat 错误；而插件只用到 ``.get``，dict 已满足契约。
    """
    context = _FakeContext()
    return OTSMemoryPlugin(context, config or _FULL_CONFIG), context


def test_plugin_registers_both_tools_when_configured() -> None:
    """四要素齐全时应建出真实客户端，并把两个工具注册进宿主."""
    plugin, context = _make_plugin()
    assert isinstance(plugin.client, OTSMemoryClient)
    assert plugin.top_k == 3 and plugin.min_score == 0.5
    assert plugin.tenant_id == "default"
    assert {tool.name for tool in context.tools} == {"recall_memory", "save_memory"}
    # 工具拿到的引用必须指向插件本身，否则 call 里取不到 client
    assert all(tool.plugin is plugin for tool in context.tools)


def test_plugin_disabled_when_config_incomplete() -> None:
    """缺任一鉴权字段时插件应降级为禁用：client=None 且不注册工具."""
    plugin, context = _make_plugin({**_FULL_CONFIG, "access_key_secret": ""})
    assert plugin.client is None
    assert context.tools == []


def test_plugin_uses_config_defaults() -> None:
    """可选配置缺省时应落到代码内的默认值."""
    plugin, _ = _make_plugin(
        {
            "endpoint": "https://example.com/",
            "instance_name": "i",
            "access_key_id": "a",
            "access_key_secret": "s",
        }
    )
    assert plugin.store_name == "huawu_memory"
    assert plugin.app_id == "astrbot"
    assert plugin.top_k == 5
    assert plugin.min_score == 0.4
    assert plugin.auto_record is True
    assert plugin.client is not None and plugin.client.region == "cn-shanghai"


async def test_auto_record_persists_conversation() -> None:
    """自动沉淀应把用户文本段与回复首段文本组装成 messages 投递."""
    plugin, _ = _make_plugin()
    client = _FakeClient()
    plugin.client = client
    event = _FakeEvent(
        messages=[_Seg("我养了一只猫"), _Seg(None), _Seg("它叫团子")],
        result=_Result([_Seg("记住了"), _Seg("还有别的吗")]),
    )

    await plugin.on_after_reply(event)
    await _drain_tasks()

    assert client.added
    assert client.added[0]["messages"] == [
        {"role": "user", "content": "我养了一只猫"},
        {"role": "user", "content": "它叫团子"},
        {"role": "assistant", "content": "记住了"},
    ]
    assert client.added[0]["store_name"] == "store"


async def test_auto_record_skips_when_disabled_or_no_client() -> None:
    """auto_record 关闭或客户端未初始化时不应发出任何请求."""
    for config, use_client in (
        ({**_FULL_CONFIG, "auto_record": False}, True),
        (_FULL_CONFIG, False),
    ):
        plugin, _ = _make_plugin(config)
        client = _FakeClient()
        plugin.client = client if use_client else None
        await plugin.on_after_reply(_FakeEvent([_Seg("hi")], _Result([_Seg("yo")])))
        await _drain_tasks()
        assert client.added == []


async def test_auto_record_skips_without_reply_or_user_text() -> None:
    """缺用户文本或缺回复文本时都应直接返回，不投递半截对话."""
    for event in (
        _FakeEvent([], _Result([_Seg("只有回复")])),
        _FakeEvent([_Seg("只有提问")], _Result([])),
        _FakeEvent([_Seg("只有提问")], None),
        _FakeEvent([_Seg(None)], _Result([_Seg(None)])),
    ):
        plugin, _ = _make_plugin()
        client = _FakeClient()
        plugin.client = client
        await plugin.on_after_reply(event)
        await _drain_tasks()
        assert client.added == []


async def test_auto_record_failure_does_not_propagate() -> None:
    """后台沉淀失败只记日志，不得让异常逃逸出去."""
    plugin, _ = _make_plugin()
    plugin.client = _FakeClient(error=RuntimeError("boom"))
    await plugin.on_after_reply(_FakeEvent([_Seg("hi")], _Result([_Seg("yo")])))
    await _drain_tasks()


def test_on_after_reply_is_registered_as_hook() -> None:
    """on_after_reply 必须是宿主识别得到的 on_decorating_result 钩子."""
    meta = getattr(OTSMemoryPlugin.on_after_reply, "__decorator_meta__", None)
    if meta is None:  # 宿主版本未暴露装饰器元信息时，退化为「仍是异步函数」
        assert inspect.iscoroutinefunction(OTSMemoryPlugin.on_after_reply)
        return
    assert "on_decorating_result" in str(meta)
