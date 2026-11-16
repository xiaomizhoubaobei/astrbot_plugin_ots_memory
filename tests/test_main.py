"""``main.py`` 工具层与插件本体单元测试（依赖 AstrBot 宿主）.

锁定两类容易回归的契约：

1. 工具 dataclass 上的 ``plugin`` 字段必须是 ``Optional[Any] + Field(exclude=True)``，
   否则 pydantic 会在实例化工具时抛 ``PydanticSchemaGenerationError``；
2. 工具返回值 ``ToolExecResult`` 是联合别名，不可调用，出错必须显式构造
   ``CallToolResult(isError=True)``。

同时覆盖「按发送者隔离 user_id」与「对话结束自动沉淀」两条新增链路。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from typing import Any

import pytest
from astrbot_plugin_ots_memory.client import BailianMemoryClient
from astrbot_plugin_ots_memory.main import (
    BailianMemoryPlugin,
    RecallMemoryTool,
    SaveMemoryTool,
    _build_user_id,
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

    top_k = 5
    min_score = 0.6
    rewrite = True
    rerank = True
    plan_version = "Pro"
    memory_library_id = ""
    profile_schema = ""
    project_id = ""

    def __init__(self, client: Any = None) -> None:
        self.client = client


class _Seg:
    def __init__(self, text: str | None) -> None:
        self.text = text


class _Result:
    def __init__(self, chain: list[Any]) -> None:
        self.chain = chain


class _FakeEvent:
    """只实现工具与自动沉淀用到的取值入口."""

    def __init__(
        self,
        messages: list[Any] | None = None,
        result: Any = None,
        *,
        sender_id: str = "user-1",
        platform_id: str = "aiocqhttp",
    ) -> None:
        self._messages = messages or []
        self._result = result
        self._sender_id = sender_id
        self._platform_id = platform_id

    def get_messages(self) -> list[Any]:
        return self._messages

    def get_result(self) -> Any:
        return self._result

    def get_sender_id(self) -> str:
        return self._sender_id

    def get_platform_id(self) -> str:
        return self._platform_id


class _AgentContext:
    def __init__(self, event: _FakeEvent | None) -> None:
        self.event = event


class _ToolContext:
    """模拟 ContextWrapper[AstrAgentContext] 的 ``context.event`` 访问路径."""

    def __init__(self, event: _FakeEvent | None = None) -> None:
        self.context = _AgentContext(event)


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


# ── user_id 构造 ────────────────────────────────────────────────────────────


def test_build_user_id_uses_platform_and_sender() -> None:
    assert _build_user_id(_FakeEvent(sender_id="42")) == "aiocqhttp:42"


def test_build_user_id_without_platform() -> None:
    event = _FakeEvent(sender_id="42", platform_id="")
    assert _build_user_id(event) == "42"


def test_build_user_id_hashes_long_values() -> None:
    raw = f"aiocqhttp:{'x' * 80}"
    expected = "astrbot_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:56]
    user_id = _build_user_id(_FakeEvent(sender_id="x" * 80))
    assert user_id == expected
    assert len(user_id) == 64
    # 同一输入必须稳定，否则每次对话都会落到不同记忆实体。
    assert user_id == _build_user_id(_FakeEvent(sender_id="x" * 80))


def test_build_user_id_empty_sender() -> None:
    assert _build_user_id(_FakeEvent(sender_id="  ")) == ""


def test_build_user_id_tolerates_platform_errors() -> None:
    class _BrokenEvent(_FakeEvent):
        def get_platform_id(self) -> str:
            raise RuntimeError("unsupported")

    assert _build_user_id(_BrokenEvent(sender_id="42")) == "42"


# ── 参数校验与客户端未初始化 ────────────────────────────────────────────────


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
    result = await tool_cls(plugin=_FakePlugin(_FakeClient())).call(
        _ToolContext(), **kwargs
    )
    assert result.isError is True
    assert _text(result) == expected


@pytest.mark.parametrize(
    ("tool_cls", "kwargs"),
    [(RecallMemoryTool, {"query": "x"}), (SaveMemoryTool, {"fact": "x"})],
)
async def test_missing_client_reports_error(
    tool_cls: type, kwargs: dict[str, str]
) -> None:
    """配置不全时 client 为 None，工具应回友好错误而不是崩栈."""
    result = await tool_cls(plugin=_FakePlugin(None)).call(_ToolContext(), **kwargs)
    assert result.isError is True
    assert "未初始化" in _text(result)


@pytest.mark.parametrize(
    ("tool_cls", "kwargs", "expected"),
    [
        (RecallMemoryTool, {"query": "x"}, "无法确定当前用户"),
        (SaveMemoryTool, {"fact": "x"}, "无法确定当前用户"),
    ],
)
async def test_missing_sender_reports_error(
    tool_cls: type, kwargs: dict[str, str], expected: str
) -> None:
    """取不到发送者 ID 时不能把记忆写到共享实体."""
    event = _FakeEvent(sender_id="")
    result = await tool_cls(plugin=_FakePlugin(_FakeClient())).call(
        _ToolContext(event), **kwargs
    )
    assert result.isError is True
    assert expected in _text(result)


@pytest.mark.parametrize(
    ("tool_cls", "kwargs"),
    [(RecallMemoryTool, {"query": "x"}), (SaveMemoryTool, {"fact": "x"})],
)
async def test_missing_event_reports_error(
    tool_cls: type, kwargs: dict[str, str]
) -> None:
    """工具上下文里没有 event 时同样不能兜底写到共享实体."""
    result = await tool_cls(plugin=_FakePlugin(_FakeClient())).call(
        _ToolContext(None), **kwargs
    )
    assert result.isError is True
    assert "无法确定当前用户" in _text(result)


# ── recall_memory 正常 / 空结果 / 异常 ────────────────────────────────────


async def test_recall_memory_formats_hits() -> None:
    client = _FakeClient(memories=[{"content": "用户喜欢梅花"}])
    result = await RecallMemoryTool(plugin=_FakePlugin(client)).call(
        _ToolContext(_FakeEvent()), query="喜好"
    )
    assert result.isError is False
    assert _text(result) == "用户喜欢梅花"


async def test_recall_memory_passes_user_scope() -> None:
    """检索必须带上当前发送者的 user_id 与插件配置."""
    client = _FakeClient(memories=[])
    plugin = _FakePlugin(client)
    plugin.memory_library_id = "lib"
    plugin.plan_version = "Lite"
    plugin.rewrite = False
    plugin.rerank = False

    calls: list[dict[str, Any]] = []

    async def _search(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return []

    client.search_memories = _search  # type: ignore[method-assign]
    await RecallMemoryTool(plugin=plugin).call(
        _ToolContext(_FakeEvent(sender_id="42")), query="喜好"
    )
    assert calls[0]["user_id"] == "aiocqhttp:42"
    assert calls[0]["memory_library_id"] == "lib"
    assert calls[0]["plan_version"] == "Lite"
    assert calls[0]["rewrite"] is False
    assert calls[0]["rerank"] is False


async def test_recall_memory_empty_result() -> None:
    result = await RecallMemoryTool(plugin=_FakePlugin(_FakeClient())).call(
        _ToolContext(_FakeEvent()), query="喜好"
    )
    assert result.isError is False
    assert _text(result) == "没有找到相关的历史记忆。"


async def test_recall_memory_skips_blank_content() -> None:
    client = _FakeClient(memories=[{"content": "  "}, {}])
    result = await RecallMemoryTool(plugin=_FakePlugin(client)).call(
        _ToolContext(_FakeEvent()), query="喜好"
    )
    assert _text(result) == "没有找到相关的历史记忆。"


async def test_recall_memory_error_is_wrapped() -> None:
    client = _FakeClient(error=RuntimeError("boom"))
    result = await RecallMemoryTool(plugin=_FakePlugin(client)).call(
        _ToolContext(_FakeEvent()), query="x"
    )
    assert result.isError is True
    assert "检索记忆失败" in _text(result)


# ── save_memory 正常 / 异常 ───────────────────────────────────────────────


async def test_save_memory_success() -> None:
    client = _FakeClient()
    plugin = _FakePlugin(client)
    plugin.memory_library_id = "lib"
    plugin.profile_schema = "ps"
    plugin.project_id = "pj"

    result = await SaveMemoryTool(plugin=plugin).call(
        _ToolContext(_FakeEvent(sender_id="42")), fact="用户喜欢梅花"
    )
    assert result.isError is False
    assert _text(result) == "已保存记忆：用户喜欢梅花"
    assert client.added[0]["user_id"] == "aiocqhttp:42"
    assert client.added[0]["text"] == "用户喜欢梅花"
    assert client.added[0]["memory_library_id"] == "lib"
    assert client.added[0]["profile_schema"] == "ps"
    assert client.added[0]["project_id"] == "pj"


async def test_save_memory_error_is_wrapped() -> None:
    client = _FakeClient(error=RuntimeError("boom"))
    result = await SaveMemoryTool(plugin=_FakePlugin(client)).call(
        _ToolContext(_FakeEvent()), fact="x"
    )
    assert result.isError is True
    assert "保存记忆失败" in _text(result)


async def test_tool_result_does_not_echo_exception_text(monkeypatch) -> None:
    """工具返回值只给固定提示，不得回显异常文本（可能夹带上游响应体）."""
    from astrbot_plugin_ots_memory import main as main_mod

    leaky = RuntimeError("百炼记忆接口错误 [status=400] 用户记忆原文")

    monkeypatch.setattr(main_mod.logger, "error", lambda *a, **k: None)
    monkeypatch.setattr(main_mod.logger, "warning", lambda *a, **k: None)

    recall = await RecallMemoryTool(plugin=_FakePlugin(_FakeClient(error=leaky))).call(
        _ToolContext(_FakeEvent()), query="x"
    )
    assert "用户记忆原文" not in _text(recall)

    save = await SaveMemoryTool(plugin=_FakePlugin(_FakeClient(error=leaky))).call(
        _ToolContext(_FakeEvent()), fact="x"
    )
    assert "用户记忆原文" not in _text(save)


# ── 插件本体：构造、Tool 注册与自动沉淀 ────────────────────────────────────

_FULL_CONFIG = {
    "dashscope_api_key": "sk-test",
    "api_base_url": "https://example.com/api/v2/apps/memory",
    "memory_library_id": "lib-1",
    "profile_schema": "ps",
    "project_id": "pj",
    "plan_version": "Lite",
    "top_k": 3,
    "min_score": 0.5,
    "rewrite": False,
    "rerank": False,
    "auto_record": True,
}


class _FakeContext:
    """只记录注册了哪些 Tool 的宿主 Context 替身."""

    def __init__(self) -> None:
        self.tools: list[Any] = []

    def add_llm_tools(self, *tools: Any) -> None:
        self.tools.extend(tools)


async def _drain_tasks() -> None:
    """把 create_task 派生的后台沉淀任务跑完，避免用例结束后残留任务."""
    pending = [
        task for task in asyncio.all_tasks() if task is not asyncio.current_task()
    ]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _make_plugin(config: dict[str, Any] | None = None) -> tuple[Any, _FakeContext]:
    """构造真实插件实例.

    config 传入普通 dict：插件只用到 ``.get``，dict 已满足契约。
    """
    context = _FakeContext()
    return BailianMemoryPlugin(context, config or _FULL_CONFIG), context


def test_plugin_registers_both_tools_when_configured() -> None:
    """API Key 与地址齐全时应建出真实客户端，并把两个工具注册进宿主."""
    plugin, context = _make_plugin()
    assert isinstance(plugin.client, BailianMemoryClient)
    assert plugin.top_k == 3 and plugin.min_score == 0.5
    assert plugin.memory_library_id == "lib-1"
    assert plugin.plan_version == "Lite"
    assert plugin.rewrite is False and plugin.rerank is False
    assert {tool.name for tool in context.tools} == {"recall_memory", "save_memory"}
    assert all(tool.plugin is plugin for tool in context.tools)


def test_plugin_disabled_when_api_key_missing() -> None:
    """缺 API Key 时应降级为禁用：client=None 且不注册工具."""
    plugin, context = _make_plugin({**_FULL_CONFIG, "dashscope_api_key": ""})
    assert plugin.client is None
    assert context.tools == []


def test_plugin_disabled_when_base_url_empty() -> None:
    plugin, context = _make_plugin({**_FULL_CONFIG, "api_base_url": "  "})
    assert plugin.client is None
    assert context.tools == []


def test_plugin_uses_config_defaults_and_clamps() -> None:
    """可选配置缺省时落到默认值，越界值应被收敛."""
    plugin, _ = _make_plugin(
        {
            "dashscope_api_key": "sk-test",
            "top_k": 999,
            "min_score": 9.0,
        }
    )
    assert plugin.memory_library_id == ""
    assert plugin.profile_schema == ""
    assert plugin.project_id == ""
    assert plugin.top_k == 100
    assert plugin.min_score == 1.0
    assert plugin.plan_version == "Pro"
    assert plugin.rewrite is True
    assert plugin.rerank is True
    assert plugin.auto_record is True
    assert plugin.client is not None


def test_invalid_plan_version_falls_back_to_pro() -> None:
    plugin, _ = _make_plugin({**_FULL_CONFIG, "plan_version": "lite"})
    assert plugin.plan_version == "Pro"


async def test_auto_record_persists_conversation() -> None:
    """自动沉淀应把用户文本段与回复首段文本组装成 messages 投递."""
    plugin, _ = _make_plugin()
    client = _FakeClient()
    plugin.client = client
    event = _FakeEvent(
        messages=[_Seg("我养了一只猫"), _Seg(None), _Seg("它叫团子")],
        result=_Result([_Seg("记住了"), _Seg("还有别的吗")]),
        sender_id="42",
    )

    await plugin.on_after_reply(event)
    await _drain_tasks()

    assert client.added
    assert client.added[0]["user_id"] == "aiocqhttp:42"
    assert client.added[0]["messages"] == [
        {"role": "user", "content": "我养了一只猫"},
        {"role": "user", "content": "它叫团子"},
        {"role": "assistant", "content": "记住了"},
    ]
    assert client.added[0]["memory_library_id"] == "lib-1"
    assert client.added[0]["profile_schema"] == "ps"
    assert client.added[0]["project_id"] == "pj"


async def test_auto_record_caps_messages_at_fifty() -> None:
    """超过百炼 50 条上限时应保留最近的用户消息并保留 assistant 末位."""
    plugin, _ = _make_plugin()
    client = _FakeClient()
    plugin.client = client

    segments = [_Seg(f"消息{i}") for i in range(80)]
    event = _FakeEvent(segments, _Result([_Seg("收到")]), sender_id="42")

    await plugin.on_after_reply(event)
    await _drain_tasks()

    messages = client.added[0]["messages"]
    assert len(messages) == 50
    assert messages[-1] == {"role": "assistant", "content": "收到"}
    assert messages[-2] == {"role": "user", "content": "消息79"}


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


async def test_auto_record_skips_without_sender() -> None:
    """取不到发送者时不能把记忆落到共享实体."""
    plugin, _ = _make_plugin()
    client = _FakeClient()
    plugin.client = client
    await plugin.on_after_reply(
        _FakeEvent([_Seg("hi")], _Result([_Seg("yo")]), sender_id="")
    )
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
    meta = getattr(BailianMemoryPlugin.on_after_reply, "__decorator_meta__", None)
    if meta is None:  # 宿主版本未暴露装饰器元信息时，退化为「仍是异步函数」
        assert inspect.iscoroutinefunction(BailianMemoryPlugin.on_after_reply)
        return
    assert "on_decorating_result" in str(meta)
