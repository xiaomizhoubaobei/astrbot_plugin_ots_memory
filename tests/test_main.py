"""插件主入口单元测试：配置装载、Tool 行为与自动沉淀.

覆盖 ``main.py`` 中不依赖真实 AstrBot 宿主的逻辑。宿主符号由
``tests/astrbot_stub.py`` 打桩（装了真实宿主时自动让位），故这些用例在
「装没装 AstrBot」的环境里都能跑——这正是此前 ``main.py`` 覆盖率恒为 0 的症结。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from astrbot_plugin_ots_memory.main import (
    OTSMemoryPlugin,
    RecallMemoryTool,
    SaveMemoryTool,
)

_FULL_CONFIG: Dict[str, Any] = {
    "endpoint": "https://bot.cn-shanghai.tablestore.aliyuncs.com",
    "instance_name": "bot",
    "region": "cn-shanghai",
    "access_key_id": "LTAI_test_ak",
    "access_key_secret": "test_secret",
    "memory_store_name": "mem_store",
    "app_id": "app",
    "top_k": 3,
    "min_score": 0.5,
    "auto_record": True,
}


class _FakeContext:
    """宿主 Context 的最小替身：只记录注册过的 LLM 工具."""

    def __init__(self) -> None:
        self.llm_tools: List[Any] = []

    def add_llm_tools(self, *tools: Any) -> None:
        self.llm_tools.extend(tools)


class _FakeClient:
    """OTS 客户端替身：按需返回预设结果或抛错，并记下调用参数."""

    def __init__(
        self,
        search_result: Optional[List[Dict[str, Any]]] = None,
        raise_on_search: bool = False,
        raise_on_add: bool = False,
    ) -> None:
        self.search_result = search_result or []
        self.raise_on_search = raise_on_search
        self.raise_on_add = raise_on_add
        self.search_calls: List[Dict[str, Any]] = []
        self.add_calls: List[Dict[str, Any]] = []

    async def search_memories(self, **kwargs: Any) -> List[Dict[str, Any]]:
        self.search_calls.append(kwargs)
        if self.raise_on_search:
            raise RuntimeError("boom-search")
        return self.search_result

    async def add_memories(self, **kwargs: Any) -> Dict[str, Any]:
        self.add_calls.append(kwargs)
        if self.raise_on_add:
            raise RuntimeError("boom-add")
        return {"ok": True}


class _Seg:
    """消息段替身：插件只读取 ``text`` 属性."""

    def __init__(self, text: Optional[str]) -> None:
        self.text = text


class _Result:
    def __init__(self, chain: List[Any]) -> None:
        self.chain = chain


class _Event:
    def __init__(self, messages: List[Any], result: Any = None) -> None:
        self._messages = messages
        self._result = result

    def get_messages(self) -> List[Any]:
        return self._messages

    def get_result(self) -> Any:
        return self._result


def _make_plugin(
    config: Optional[Dict[str, Any]] = None, client: Any = None
) -> OTSMemoryPlugin:
    """构造插件实例，并按需替换 client（None 表示沿用真实构造结果）."""
    plugin = OTSMemoryPlugin(_FakeContext(), dict(config or _FULL_CONFIG))
    if client is not None:
        plugin.client = client
    return plugin


# ── 初始化与配置装载 ────────────────────────────────────────────────────


def test_full_config_builds_client_and_registers_tools() -> None:
    """配置完整时应建好 client，并注册两个 LLM 工具."""
    plugin = _make_plugin()
    assert plugin.client is not None
    assert plugin.store_name == "mem_store"
    assert plugin.app_id == "app"
    assert plugin.tenant_id == "default"
    assert plugin.top_k == 3
    assert plugin.min_score == 0.5
    assert plugin.auto_record is True

    tools = plugin.context.llm_tools
    assert [t.name for t in tools] == ["recall_memory", "save_memory"]
    assert all(t.plugin is plugin for t in tools)


def test_config_defaults_are_applied() -> None:
    """缺省字段应回落到约定默认值."""
    plugin = OTSMemoryPlugin(
        _FakeContext(),
        {
            "endpoint": "https://e",
            "instance_name": "i",
            "access_key_id": "a",
            "access_key_secret": "s",
        },
    )
    assert plugin.store_name == "huawu_memory"
    assert plugin.app_id == "astrbot"
    assert plugin.top_k == 5
    assert plugin.min_score == 0.4
    assert plugin.auto_record is True


@pytest.mark.parametrize(
    "missing",
    ["endpoint", "instance_name", "access_key_id", "access_key_secret"],
)
def test_incomplete_config_disables_plugin(missing: str) -> None:
    """任一必填项缺失时插件自禁：client 为 None 且不注册工具."""
    config = dict(_FULL_CONFIG)
    config[missing] = ""
    plugin = _make_plugin(config)
    assert plugin.client is None
    assert plugin.context.llm_tools == []


# ── recall_memory ──────────────────────────────────────────────────────


async def test_recall_rejects_empty_query() -> None:
    result = await RecallMemoryTool(plugin=_make_plugin()).call(None, query="   ")
    assert result.is_error is True
    assert "query" in result.result


async def test_recall_reports_uninitialized_client() -> None:
    """client 未初始化时不得发起请求，直接回错."""
    plugin = _make_plugin()
    plugin.client = None
    result = await RecallMemoryTool(plugin=plugin).call(None, query="任何")
    assert result.is_error is True
    assert "未初始化" in result.result


async def test_recall_without_plugin_instance() -> None:
    """`plugin` 为空的工具实例也应安全回错（不抛异常）."""
    result = await RecallMemoryTool().call(None, query="任何")
    assert result.is_error is True


async def test_recall_returns_no_match_message() -> None:
    client = _FakeClient(search_result=[])
    result = await RecallMemoryTool(plugin=_make_plugin(client=client)).call(
        None, query="上次说到哪"
    )
    assert result.is_error is False
    assert "没有找到" in result.result


async def test_recall_formats_hits_with_score() -> None:
    """命中的记忆应带上相关度，且查询参数取自插件配置."""
    client = _FakeClient(
        search_result=[
            {"unit": {"text": "用户喜欢喝茶"}, "score": 0.87},
            {"unit": {}, "score": 0.5},
        ]
    )
    result = await RecallMemoryTool(plugin=_make_plugin(client=client)).call(
        None, query=" 偏好 "
    )
    assert result.is_error is False
    assert "[相关度 0.87] 用户喜欢喝茶" in result.result
    assert "[相关度 0.50] " in result.result

    call = client.search_calls[0]
    assert call["query"] == "偏好"
    assert call["store_name"] == "mem_store"
    assert call["app_id"] == "app"
    assert call["tenant_id"] == "default"
    assert call["top_k"] == 3
    assert call["min_score"] == 0.5


async def test_recall_converts_exception_to_error_result() -> None:
    """上游异常必须转成 is_error 结果，不向调用方抛栈."""
    client = _FakeClient(raise_on_search=True)
    result = await RecallMemoryTool(plugin=_make_plugin(client=client)).call(
        None, query="x"
    )
    assert result.is_error is True
    assert "boom-search" in result.result


# ── save_memory ────────────────────────────────────────────────────────


async def test_save_rejects_empty_fact() -> None:
    result = await SaveMemoryTool(plugin=_make_plugin()).call(None, fact="  ")
    assert result.is_error is True
    assert "fact" in result.result


async def test_save_reports_uninitialized_client() -> None:
    plugin = _make_plugin()
    plugin.client = None
    result = await SaveMemoryTool(plugin=plugin).call(None, fact="记一件事")
    assert result.is_error is True
    assert "未初始化" in result.result


async def test_save_without_plugin_instance() -> None:
    result = await SaveMemoryTool().call(None, fact="记一件事")
    assert result.is_error is True


async def test_save_writes_fact_and_echoes_it() -> None:
    client = _FakeClient()
    result = await SaveMemoryTool(plugin=_make_plugin(client=client)).call(
        None, fact=" 用户在杭州 "
    )
    assert result.is_error is False
    assert "用户在杭州" in result.result
    call = client.add_calls[0]
    assert call["text"] == "用户在杭州"
    assert call["store_name"] == "mem_store"
    assert call["tenant_id"] == "default"


async def test_save_converts_exception_to_error_result() -> None:
    client = _FakeClient(raise_on_add=True)
    result = await SaveMemoryTool(plugin=_make_plugin(client=client)).call(
        None, fact="x"
    )
    assert result.is_error is True
    assert "boom-add" in result.result


# ── on_after_reply（自动沉淀） ──────────────────────────────────────────


async def _drain_background() -> None:
    """把 on_after_reply 里 create_task 抛出的后台任务跑完."""
    await asyncio.gather(*[t for t in asyncio.all_tasks() if t is not asyncio.current_task()])


async def test_auto_record_skipped_when_disabled() -> None:
    config = dict(_FULL_CONFIG, auto_record=False)
    client = _FakeClient()
    plugin = _make_plugin(config, client=client)
    await plugin.on_after_reply(_Event([_Seg("提问")], _Result([_Seg("回答")])))
    await _drain_background()
    assert client.add_calls == []


async def test_auto_record_skipped_without_client() -> None:
    plugin = _make_plugin()
    plugin.client = None
    await plugin.on_after_reply(_Event([_Seg("提问")], _Result([_Seg("回答")])))


async def test_auto_record_submits_turn_messages() -> None:
    """正常一轮对话应把 user + assistant 两条消息投递沉淀."""
    client = _FakeClient()
    plugin = _make_plugin(client=client)
    event = _Event([_Seg("我住在杭州"), _Seg(None)], _Result([_Seg(None), _Seg("记住啦")]))
    await plugin.on_after_reply(event)
    await _drain_background()

    assert len(client.add_calls) == 1
    call = client.add_calls[0]
    assert call["messages"] == [
        {"role": "user", "content": "我住在杭州"},
        {"role": "assistant", "content": "记住啦"},
    ]
    assert call["store_name"] == "mem_store"


@pytest.mark.parametrize(
    "messages,result",
    [
        ([], _Result([_Seg("回答")])),  # 无用户消息
        ([_Seg("提问")], None),  # 无结果
        ([_Seg("提问")], _Result([])),  # 结果链为空
        ([_Seg("提问")], _Result([_Seg(None)])),  # 结果链无文本
    ],
)
async def test_auto_record_skips_incomplete_turn(messages: List[Any], result: Any) -> None:
    """缺用户消息或助手文本时不动记忆库."""
    client = _FakeClient()
    plugin = _make_plugin(client=client)
    await plugin.on_after_reply(_Event(messages, result))
    await _drain_background()
    assert client.add_calls == []


async def test_auto_record_background_failure_is_swallowed() -> None:
    """后台沉淀失败只告警，不把异常抛回事件循环."""
    client = _FakeClient(raise_on_add=True)
    plugin = _make_plugin(client=client)
    await plugin.on_after_reply(_Event([_Seg("提问")], _Result([_Seg("回答")])))
    await _drain_background()
    assert len(client.add_calls) == 1
