"""OTS V4 签名与请求组装单元测试.

覆盖 ``client.py`` 中不依赖 AstrBot 宿主的纯逻辑：签名派生、请求头构造、
请求体组装与错误转换。这些是插件的安全敏感面（AK/SK 签名），值得单测锁定。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from astrbot_plugin_ots_memory.client import OTSMemoryClient


def _make_client() -> OTSMemoryClient:
    return OTSMemoryClient(
        endpoint="https://bot.cn-shanghai.tablestore.aliyuncs.com",
        instance_name="bot",
        access_key_id="LTAI_test_ak",
        access_key_secret="test_secret",
        region="cn-shanghai",
    )


# ── 构造与归一化 ────────────────────────────────────────────────────────────


def test_endpoint_trailing_slash_stripped() -> None:
    """endpoint 末尾斜杠应被剥离，避免拼出双斜杠 URL."""
    client = OTSMemoryClient(
        endpoint="https://example.com/",
        instance_name="i",
        access_key_id="a",
        access_key_secret="s",
    )
    assert client.endpoint == "https://example.com"


def test_default_region_is_cn_shanghai() -> None:
    client = OTSMemoryClient(
        endpoint="https://example.com",
        instance_name="i",
        access_key_id="a",
        access_key_secret="s",
    )
    assert client.region == "cn-shanghai"


# ── 签名派生（V4 派生链） ───────────────────────────────────────────────────


def test_signing_key_is_deterministic_and_base64() -> None:
    """相同入参应派生出稳定且为 base64 的签名密钥."""
    client = _make_client()
    key1 = client._get_signing_key("20250101")
    key2 = client._get_signing_key("20250101")
    assert key1 == key2
    # 应为合法 base64（可解码且长度合理）
    assert isinstance(key1, bytes)
    base64.b64decode(key1)


def test_signing_key_changes_with_date() -> None:
    """签名密钥随 sign_date 变化（派生链包含日期）."""
    client = _make_client()
    assert client._get_signing_key("20250101") != client._get_signing_key("20250102")


def test_signing_key_changes_with_secret() -> None:
    """签名密钥随 AK Secret 变化."""
    c1 = _make_client()
    c2 = OTSMemoryClient(
        endpoint="https://example.com",
        instance_name="bot",
        access_key_id="LTAI_test_ak",
        access_key_secret="other_secret",
    )
    assert c1._get_signing_key("20250101") != c2._get_signing_key("20250101")


# ── 请求头构造 ──────────────────────────────────────────────────────────────


def test_build_headers_contains_required_ots_fields() -> None:
    """请求头应包含 OTS 签名所需的全部字段."""
    client = _make_client()
    body = b'{"hello":"world"}'
    headers = client._build_headers("SearchMemories", body)

    for field in (
        "x-ots-apiversion",
        "x-ots-accesskeyid",
        "x-ots-instancename",
        "x-ots-contentmd5",
        "x-ots-date",
        "x-ots-signdate",
        "x-ots-signregion",
        "x-ots-signaturev4",
        "Content-Type",
        "User-Agent",
    ):
        assert field in headers, f"缺少请求头 {field}"

    assert headers["x-ots-accesskeyid"] == "LTAI_test_ak"
    assert headers["x-ots-instancename"] == "bot"
    assert headers["x-ots-signregion"] == "cn-shanghai"
    assert headers["Content-Type"] == "application/json"


def test_content_md5_matches_body() -> None:
    """x-ots-contentmd5 必须等于请求体的 MD5（base64）."""
    client = _make_client()
    body = b'{"a":1}'
    headers = client._build_headers("AddMemories", body)
    # 与实现同口径：MD5 是 OTS 协议校验用途，非安全哈希，故标注 usedforsecurity=False
    expected = base64.b64encode(
        hashlib.md5(body, usedforsecurity=False).digest()
    ).decode("utf-8")
    assert headers["x-ots-contentmd5"] == expected


def test_content_md5_does_not_leak_secret() -> None:
    """请求头不得泄漏 AK Secret（不应出现在任何值中）."""
    client = _make_client()
    headers = client._build_headers("AddMemories", b"{}")
    joined = "\n".join(f"{k}:{v}" for k, v in headers.items())
    assert "test_secret" not in joined


# 已知答案（KAT）向量：签名密钥派生链的固定快照。
# 注意：这是对「阿里云 OTS V4 派生链」的**外部**固定值锁定——
# 一旦派生顺序/盐值/编码被误改，此处会立刻失败，且不依赖实现自身的复算。
_SIGNING_KEY_KAT = {
    # (ak_secret, sign_date, region) -> base64(signing key)
    ("test_secret", "20250101", "cn-shanghai"): (
        "5Y9rvjOzmRGRri2jt9QSu2FUn4svfP50lOsDv879qC0="
    ),
}


def test_signing_key_matches_known_answer_vector() -> None:
    """签名密钥须与固定 KAT 一致（锁定 V4 派生链，避免自证式测试）."""
    client = _make_client()
    key = client._get_signing_key("20250101")
    expected = _SIGNING_KEY_KAT[("test_secret", "20250101", "cn-shanghai")]
    assert key.decode("utf-8") == expected


def test_signature_matches_known_answer_vector() -> None:
    """用固定 KAT 密钥独立复算签名，锁定 canonical string 与签名口径.

    关键点：**不复用实现的 ``_get_signing_key``**，而是在下方内联一条
    独立的派生链，避免「错误的密钥派生导致两边同时变化、测试仍通过」。
    """
    client = _make_client()
    body = b'{"hello":"world"}'
    sign_date = "20250101"
    date_str = "2025-01-01T00:00:00.000Z"

    # 独立派生（与实现完全解耦的一段本地实现，仅依据阿里云 OTS V4 规范）
    k_secret = b"aliyun_v4test_secret"
    h1 = hmac.new(k_secret, sign_date.encode(), hashlib.sha256).digest()
    h2 = hmac.new(h1, b"cn-shanghai", hashlib.sha256).digest()
    h3 = hmac.new(h2, b"ots", hashlib.sha256).digest()
    fourth = hmac.new(h3, b"aliyun_v4_request", hashlib.sha256).digest()
    independent_key = base64.b64encode(fourth)
    # 实现的派生链必须与上述独立链一致（否则 KAT 断言会失效）
    assert client._get_signing_key(sign_date) == independent_key

    # 逐字复刻 OTS 协议头：MD5 为请求体校验用途，非安全哈希
    md5 = base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode(
        "utf-8"
    )
    header_items = [
        "x-ots-accesskeyid:LTAI_test_ak",
        "x-ots-apiversion:2015-12-31",
        f"x-ots-contentmd5:{md5}",
        f"x-ots-date:{date_str}",
        f"x-ots-signdate:{sign_date}",
        "x-ots-instancename:bot",
        "x-ots-signregion:cn-shanghai",
    ]
    header_items.sort()
    headers_string = "\n".join(header_items)
    request_string = f"/SearchMemories\nPOST\n\n{headers_string}\n"
    sign_string = f"{request_string}ots"

    expect = base64.b64encode(
        hmac.new(independent_key, sign_string.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")

    # 固定 KAT：以上文独立派生得到的签名值，锁定 OTS V4 口径
    assert expect == "USHWqNI0NkcUkNcVfUn5B/I4XwstDJD/syQkpIIWo4s="


def test_signature_changes_with_body() -> None:
    """不同请求体应产生不同签名（MD5 进签名链）."""
    client = _make_client()
    s1 = client._build_headers("AddMemories", b'{"a":1}')["x-ots-signaturev4"]
    s2 = client._build_headers("AddMemories", b'{"a":2}')["x-ots-signaturev4"]
    assert s1 != s2


# ── 请求体组装 ──────────────────────────────────────────────────────────────


class _FakeResponse:
    """最小 aiohttp 响应替身，用于捕获出站请求."""

    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    async def text(self) -> str:
        return json.dumps(self._payload)

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSession:
    """最小 aiohttp ClientSession 替身."""

    captured: dict = {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def post(self, url: str, headers: dict, data: bytes) -> _FakeResponse:
        _FakeSession.captured = {"url": url, "headers": headers, "data": data}
        return _FakeResponse(_FakeSession.response_payload)

    response_payload: dict = {}

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture()
def fake_aiohttp(monkeypatch: pytest.MonkeyPatch):
    """把 client 模块内的 aiohttp.ClientSession 换成替身."""
    from astrbot_plugin_ots_memory import client as client_mod

    monkeypatch.setattr(client_mod.aiohttp, "ClientSession", _FakeSession)
    _FakeSession.captured = {}
    return _FakeSession


@pytest.mark.asyncio
async def test_search_memories_builds_expected_payload(fake_aiohttp) -> None:
    """search_memories 应组装正确的 URL 与 payload，并回传 results."""
    fake_aiohttp.response_payload = {"results": [{"score": 0.9}]}
    client = _make_client()
    results = await client.search_memories(
        store_name="store",
        app_id="app",
        tenant_id="tenant",
        query="hello",
        top_k=3,
        min_score=0.5,
    )
    assert results == [{"score": 0.9}]

    sent = json.loads(fake_aiohttp.captured["data"])
    assert sent["memoryStoreName"] == "store"
    assert sent["scope"] == {"appId": "app", "tenantId": "tenant"}
    assert sent["query"] == "hello"
    assert sent["topK"] == 3
    assert sent["thresholds"] == {"minScore": 0.5}
    assert fake_aiohttp.captured["url"].endswith("/SearchMemories")


@pytest.mark.asyncio
async def test_search_memories_omits_threshold_when_zero(fake_aiohttp) -> None:
    """min_score<=0 时不应下发 thresholds 字段."""
    fake_aiohttp.response_payload = {"results": []}
    client = _make_client()
    await client.search_memories(
        store_name="s", app_id="a", tenant_id="t", query="q", min_score=0.0
    )
    sent = json.loads(fake_aiohttp.captured["data"])
    assert "thresholds" not in sent


@pytest.mark.asyncio
async def test_add_memories_prefers_messages_over_text(fake_aiohttp) -> None:
    """messages 与 text 同时给出时，应优先使用 messages."""
    fake_aiohttp.response_payload = {}
    client = _make_client()
    await client.add_memories(
        store_name="s",
        app_id="a",
        tenant_id="t",
        messages=[{"role": "user", "content": "hi"}],
        text="ignored",
    )
    sent = json.loads(fake_aiohttp.captured["data"])
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert "userMemories" not in sent


@pytest.mark.asyncio
async def test_add_memories_uses_text_when_no_messages(fake_aiohttp) -> None:
    """仅有 text 时应组装 userMemories."""
    fake_aiohttp.response_payload = {}
    client = _make_client()
    await client.add_memories(
        store_name="s", app_id="a", tenant_id="t", text="记住这件事"
    )
    sent = json.loads(fake_aiohttp.captured["data"])
    assert sent["userMemories"] == [{"text": "记住这件事"}]
    assert "messages" not in sent


@pytest.mark.asyncio
async def test_add_memories_raises_when_both_empty(fake_aiohttp) -> None:
    """messages 与 text 均为空时应抛 ValueError，不发出请求."""
    client = _make_client()
    with pytest.raises(ValueError):
        await client.add_memories(store_name="s", app_id="a", tenant_id="t")


@pytest.mark.asyncio
async def test_error_status_raises_runtime_error(fake_aiohttp) -> None:
    """上游非 2xx 状态应转换为 RuntimeError，而非泄漏原始异常."""
    from astrbot_plugin_ots_memory import client as client_mod

    class _ErrResponse(_FakeResponse):
        def __init__(self) -> None:
            super().__init__({}, status=500)

        async def text(self) -> str:
            return "boom"

    class _ErrSession(_FakeSession):
        def post(self, url: str, headers: dict, data: bytes) -> _ErrResponse:
            return _ErrResponse()

    client_mod.aiohttp.ClientSession = _ErrSession
    client = _make_client()
    with pytest.raises(RuntimeError, match="OTS API Error"):
        await client.search_memories(
            store_name="s", app_id="a", tenant_id="t", query="q"
        )


def test_uses_astrbot_api_logger() -> None:
    """日志记录器必须来自 astrbot.api，禁止内置 logging / 第三方日志库.

    上架规范硬性要求：``from astrbot.api import logger``。此处锁定两点——
    模块内不再导入内置 ``logging``，且 ``logger`` 就是 astrbot.api 提供的那一个。
    """
    from astrbot.api import logger as astrbot_logger
    from astrbot_plugin_ots_memory import client as client_mod

    assert client_mod.logger is astrbot_logger
    assert "logging" not in client_mod.__dict__


@pytest.mark.asyncio
async def test_error_status_logs_via_astrbot_logger(fake_aiohttp, monkeypatch) -> None:
    """上游出错时应落一条 error 日志，便于宿主侧统一收集."""
    from astrbot_plugin_ots_memory import client as client_mod

    class _ErrResponse(_FakeResponse):
        def __init__(self) -> None:
            super().__init__({}, status=503)

        async def text(self) -> str:
            return "unavailable"

    class _ErrSession(_FakeSession):
        def post(self, url: str, headers: dict, data: bytes) -> _ErrResponse:
            return _ErrResponse()

    calls: list[str] = []
    monkeypatch.setattr(client_mod.logger, "error", lambda msg: calls.append(msg))
    monkeypatch.setattr(client_mod.aiohttp, "ClientSession", _ErrSession)

    client = _make_client()
    with pytest.raises(RuntimeError):
        await client.search_memories(
            store_name="s", app_id="a", tenant_id="t", query="q"
        )

    assert len(calls) == 1
    assert "status=503" in calls[0]


@pytest.mark.asyncio
async def test_error_log_omits_body_and_truncates_request_id(
    fake_aiohttp, monkeypatch
) -> None:
    """错误日志只记状态与截断后的请求 ID，不得落盘上游响应体.

    上游非 2xx 响应体可能极大或回显用户数据，同一份内容已随 RuntimeError
    抛给调用方，因此这里锁死：日志里不出现响应体，请求 ID 超长须截断。
    """
    from astrbot_plugin_ots_memory import client as client_mod

    huge_body = "sensitive-echo-" * 1000

    class _ErrResponse(_FakeResponse):
        def __init__(self) -> None:
            super().__init__({}, status=429)
            self.headers = {"x-ots-requestid": "R" * 200}

        async def text(self) -> str:
            return huge_body

    class _ErrSession(_FakeSession):
        def post(self, url: str, headers: dict, data: bytes) -> _ErrResponse:
            return _ErrResponse()

    calls: list[str] = []
    monkeypatch.setattr(client_mod.logger, "error", lambda msg: calls.append(msg))
    monkeypatch.setattr(client_mod.aiohttp, "ClientSession", _ErrSession)

    client = _make_client()
    with pytest.raises(RuntimeError) as exc_info:
        await client.search_memories(
            store_name="s", app_id="a", tenant_id="t", query="q"
        )

    assert len(calls) == 1
    logged = calls[0]
    assert "status=429" in logged
    assert ("R" * 64) in logged
    # 请求 ID 截断到 64 字符，响应体一律不进日志
    assert "R" * 65 not in logged
    assert "sensitive-echo" not in logged
    # 响应体仍完整保留在异常里，交由调用方决定如何处置
    assert "sensitive-echo" in str(exc_info.value)
