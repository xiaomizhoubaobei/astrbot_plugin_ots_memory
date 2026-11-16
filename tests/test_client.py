"""百炼记忆库客户端单元测试.

覆盖请求组装、参数校验、错误脱敏与重试策略。这些是插件的安全敏感面：
API Key 鉴权、用户记忆内容与上游错误体都不得泄漏。
"""

from __future__ import annotations

import json

import pytest
from astrbot_plugin_ots_memory.client import (
    DEFAULT_API_BASE_URL,
    BailianMemoryClient,
)


def _make_client() -> BailianMemoryClient:
    return BailianMemoryClient(
        api_key="test_key",
        base_url="https://example.com/api/v2/apps/memory/",
        memory_library_id="lib-1",
        timeout=5,
    )


# ── 构造与归一化 ────────────────────────────────────────────────────────────


def test_base_url_trailing_slash_stripped() -> None:
    """base_url 末尾斜杠应被剥离，避免拼出双斜杠 URL."""
    client = BailianMemoryClient(api_key="k", base_url="https://example.com/api/")
    assert client.base_url == "https://example.com/api"


def test_default_base_url_is_dashscope() -> None:
    client = BailianMemoryClient(api_key="k")
    assert client.base_url == DEFAULT_API_BASE_URL
    assert client.memory_library_id == ""


# ── 请求组装 ────────────────────────────────────────────────────────────────


class _FakeResponse:
    """最小 aiohttp 响应替身."""

    def __init__(
        self,
        payload: dict | None = None,
        *,
        status: int = 200,
        headers: dict | None = None,
        text: str | None = None,
    ) -> None:
        self._payload = payload if payload is not None else {}
        self._text = text
        self.status = status
        self.headers = headers or {}

    async def text(self) -> str:
        if self._text is not None:
            return self._text
        return json.dumps(self._payload)

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSession:
    """最小 aiohttp ClientSession 替身，按顺序返回预设响应."""

    captured: list[dict] = []
    responses: list[object] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def post(
        self, url: str, headers: dict, data: bytes, **kwargs: object
    ) -> _FakeResponse:
        _FakeSession.captured.append(
            {"url": url, "headers": headers, "data": data, "kwargs": kwargs}
        )
        if not _FakeSession.responses:
            return _FakeResponse({})
        item = _FakeSession.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        assert isinstance(item, _FakeResponse)
        return item

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture()
def fake_aiohttp(monkeypatch: pytest.MonkeyPatch):
    """把 client 模块内的 aiohttp.ClientSession 换成替身."""
    from astrbot_plugin_ots_memory import client as client_mod

    monkeypatch.setattr(client_mod.aiohttp, "ClientSession", _FakeSession)
    _FakeSession.captured = []
    _FakeSession.responses = []
    return _FakeSession


@pytest.fixture()
def no_sleep(monkeypatch: pytest.MonkeyPatch):
    """让重试退避不真的等待."""
    from astrbot_plugin_ots_memory import client as client_mod

    async def _noop(_seconds: float) -> None:
        return None

    monkeypatch.setattr(client_mod.asyncio, "sleep", _noop)


@pytest.mark.asyncio
async def test_search_memories_builds_expected_payload(fake_aiohttp) -> None:
    """search_memories 应组装正确的 URL、鉴权头与 payload."""
    fake_aiohttp.responses = [_FakeResponse({"memory_nodes": [{"content": "m"}]})]
    client = _make_client()

    results = await client.search_memories(
        user_id="user-1",
        query="hello",
        top_k=3,
        min_score=0.5,
    )

    assert results == [{"content": "m"}]
    sent = json.loads(fake_aiohttp.captured[0]["data"])
    assert sent == {
        "user_id": "user-1",
        "query": "hello",
        "max_results": 3,
        "rewrite": True,
        "rerank": True,
        "plan_version": "Pro",
        "similarity_threshold": 0.5,
        "memory_library_id": "lib-1",
    }
    assert fake_aiohttp.captured[0]["url"] == (
        "https://example.com/api/v2/apps/memory/memory_nodes/search"
    )
    headers = fake_aiohttp.captured[0]["headers"]
    assert headers["Authorization"] == "Bearer test_key"
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_search_memories_omits_threshold_when_zero(fake_aiohttp) -> None:
    """min_score<=0 时不应下发 similarity_threshold."""
    fake_aiohttp.responses = [_FakeResponse({"memory_nodes": []})]
    await _make_client().search_memories(user_id="u", query="q", min_score=0.0)
    sent = json.loads(fake_aiohttp.captured[0]["data"])
    assert "similarity_threshold" not in sent


@pytest.mark.asyncio
async def test_search_memories_returns_empty_on_bad_nodes(fake_aiohttp) -> None:
    """memory_nodes 缺失或类型不对时返回空列表."""
    fake_aiohttp.responses = [_FakeResponse({"memory_nodes": "bad"})]
    assert await _make_client().search_memories(user_id="u", query="q") == []


@pytest.mark.asyncio
async def test_add_memories_uses_messages(fake_aiohttp) -> None:
    """messages 形式应原样下发."""
    fake_aiohttp.responses = [_FakeResponse({"memory_nodes": []})]
    messages = [{"role": "user", "content": "hi"}]
    await _make_client().add_memories(
        user_id="u",
        messages=messages,
        profile_schema="ps",
        project_id="pj",
        meta_data={"source": "test"},
    )
    sent = json.loads(fake_aiohttp.captured[0]["data"])
    assert sent["messages"] == messages
    assert sent["profile_schema"] == "ps"
    assert sent["project_id"] == "pj"
    assert sent["meta_data"] == {"source": "test"}
    assert "custom_content" not in sent


@pytest.mark.asyncio
async def test_add_memories_uses_custom_content(fake_aiohttp) -> None:
    """text 形式应映射到 custom_content."""
    fake_aiohttp.responses = [_FakeResponse({})]
    await _make_client().add_memories(user_id="u", text="记住这件事")
    sent = json.loads(fake_aiohttp.captured[0]["data"])
    assert sent["custom_content"] == "记住这件事"
    assert "messages" not in sent


@pytest.mark.asyncio
async def test_add_memories_rejects_both_or_neither(fake_aiohttp) -> None:
    """messages 与 text 互斥，且不能同时为空."""
    client = _make_client()
    with pytest.raises(ValueError, match="互斥"):
        await client.add_memories(
            user_id="u",
            messages=[{"role": "user", "content": "hi"}],
            text="fact",
        )
    with pytest.raises(ValueError, match="不能同时为空"):
        await client.add_memories(user_id="u")
    assert fake_aiohttp.captured == []


@pytest.mark.asyncio
async def test_add_memories_validates_limits(fake_aiohttp) -> None:
    """user_id / text / messages 超限应在本地拦截，不发出请求."""
    client = _make_client()
    with pytest.raises(ValueError, match="user_id 不能为空"):
        await client.add_memories(user_id="  ", text="x")
    with pytest.raises(ValueError, match="user_id 超长"):
        await client.add_memories(user_id="u" * 65, text="x")
    with pytest.raises(ValueError, match="text 不能为空"):
        await client.add_memories(user_id="u", text="   ")
    with pytest.raises(ValueError, match="text 超长"):
        await client.add_memories(user_id="u", text="x" * 513)
    with pytest.raises(ValueError, match="消息条数超限"):
        await client.add_memories(
            user_id="u",
            messages=[{"role": "user", "content": "x"}] * 51,
        )
    assert fake_aiohttp.captured == []


@pytest.mark.asyncio
async def test_search_memories_validates_arguments(fake_aiohttp) -> None:
    """检索参数越界应在本地拦截."""
    client = _make_client()
    with pytest.raises(ValueError, match="query 不能为空"):
        await client.search_memories(user_id="u", query=" ")
    with pytest.raises(ValueError, match="top_k"):
        await client.search_memories(user_id="u", query="q", top_k=0)
    with pytest.raises(ValueError, match="min_score"):
        await client.search_memories(user_id="u", query="q", min_score=1.5)
    with pytest.raises(ValueError, match="plan_version"):
        await client.search_memories(user_id="u", query="q", plan_version="pro")
    assert fake_aiohttp.captured == []


@pytest.mark.asyncio
async def test_request_disables_redirects(fake_aiohttp) -> None:
    """出站必须显式关闭重定向跟随，避免请求被带往配置地址之外的主机."""
    fake_aiohttp.responses = [_FakeResponse({"memory_nodes": []})]
    await _make_client().search_memories(user_id="u", query="q")
    assert fake_aiohttp.captured[0]["kwargs"].get("allow_redirects") is False


# ── 错误处理与脱敏 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_error_does_not_echo_upstream_body(fake_aiohttp) -> None:
    """异常文本只含状态与请求 ID，不得夹带上游响应体."""
    leak = "user-memory-echo"
    fake_aiohttp.responses = [
        _FakeResponse(status=400, headers={"x-request-id": "rid-123"}, text=leak)
    ]
    with pytest.raises(RuntimeError) as exc_info:
        await _make_client().search_memories(user_id="u", query="q")

    message = str(exc_info.value)
    assert "400" in message
    assert "rid-123" in message
    assert leak not in message


def test_extract_request_id_handles_bad_json_and_non_dict() -> None:
    """错误体不是合法 JSON 或不是对象时，request_id 退化为空串."""
    assert BailianMemoryClient._extract_request_id("not-json") == ""
    assert BailianMemoryClient._extract_request_id("[]") == ""


@pytest.mark.asyncio
async def test_error_request_id_from_json_body(fake_aiohttp) -> None:
    """响应头没有 request_id 时，只从 JSON 错误体提取该字段，不保留其余内容."""
    body = json.dumps({"request_id": "rid-json", "message": "secret-echo"})
    fake_aiohttp.responses = [_FakeResponse(status=400, text=body)]
    with pytest.raises(RuntimeError) as exc_info:
        await _make_client().add_memories(user_id="u", text="fact")

    message = str(exc_info.value)
    assert "rid-json" in message
    assert "secret-echo" not in message


@pytest.mark.asyncio
async def test_non_json_success_raises(fake_aiohttp) -> None:
    """2xx 但响应不是 JSON 时应转为 RuntimeError."""
    fake_aiohttp.responses = [_FakeResponse(status=200, text="not-json")]
    with pytest.raises(RuntimeError, match="非 JSON"):
        await _make_client().search_memories(user_id="u", query="q")


@pytest.mark.asyncio
async def test_retries_on_503_then_succeeds(fake_aiohttp, no_sleep) -> None:
    """503 应退避重试，后续成功则正常返回."""
    fake_aiohttp.responses = [
        _FakeResponse(status=503),
        _FakeResponse({"memory_nodes": [{"content": "ok"}]}),
    ]
    results = await _make_client().search_memories(user_id="u", query="q")
    assert results == [{"content": "ok"}]
    assert len(fake_aiohttp.captured) == 2


@pytest.mark.asyncio
async def test_retry_exhausted_raises(fake_aiohttp, no_sleep) -> None:
    """429 连续失败达到重试上限后应抛 RuntimeError."""
    fake_aiohttp.responses = [_FakeResponse(status=429) for _ in range(4)]
    with pytest.raises(RuntimeError, match="status=429"):
        await _make_client().search_memories(user_id="u", query="q")
    assert len(fake_aiohttp.captured) == 4


@pytest.mark.asyncio
async def test_4xx_does_not_retry(fake_aiohttp, no_sleep) -> None:
    """非限流 4xx 属参数/鉴权问题，应快速失败不重试."""
    fake_aiohttp.responses = [_FakeResponse(status=401)]
    with pytest.raises(RuntimeError, match="status=401"):
        await _make_client().add_memories(user_id="u", text="x")
    assert len(fake_aiohttp.captured) == 1


@pytest.mark.asyncio
async def test_network_error_retries_then_raises(fake_aiohttp, no_sleep) -> None:
    """网络异常应重试，耗尽后转为 RuntimeError."""
    from astrbot_plugin_ots_memory import client as client_mod

    fake_aiohttp.responses = [client_mod.aiohttp.ClientError("boom") for _ in range(4)]
    with pytest.raises(RuntimeError, match="网络异常"):
        await _make_client().search_memories(user_id="u", query="q")
    assert len(fake_aiohttp.captured) == 4


# ── 日志与依赖边界 ──────────────────────────────────────────────────────────


def test_uses_astrbot_api_logger() -> None:
    """日志记录器必须来自 astrbot.api，禁止内置 logging / 第三方日志库."""
    from astrbot.api import logger as astrbot_logger
    from astrbot_plugin_ots_memory import client as client_mod

    assert client_mod.logger is astrbot_logger
    assert "logging" not in client_mod.__dict__


@pytest.mark.asyncio
async def test_error_log_omits_body_and_truncates_request_id(
    fake_aiohttp, monkeypatch
) -> None:
    """错误日志只记状态与截断后的请求 ID，不得落盘上游响应体."""
    from astrbot_plugin_ots_memory import client as client_mod

    huge_body = "sensitive-echo-" * 1000
    fake_aiohttp.responses = [
        _FakeResponse(
            status=400,
            headers={"x-request-id": "R" * 200},
            text=huge_body,
        )
    ]
    calls: list[str] = []
    monkeypatch.setattr(client_mod.logger, "error", lambda msg: calls.append(msg))

    with pytest.raises(RuntimeError) as exc_info:
        await _make_client().search_memories(user_id="u", query="q")

    assert len(calls) == 1
    logged = calls[0]
    assert "status=400" in logged
    assert ("R" * 64) in logged
    assert "R" * 65 not in logged
    assert "sensitive-echo" not in logged
    assert "sensitive-echo" not in str(exc_info.value)
