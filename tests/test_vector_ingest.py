"""向量知识库脚本的纯函数单元测试.

脚本位于 ``.claude/skills/vector-knowledge/scripts/``，不是插件的运行时模块，
因此用 importlib 按文件路径加载。测试只覆盖不依赖网络的纯逻辑：仓库识别、
切片、主键、V4 签名、错误脱敏与参数校验。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "vector-knowledge"
    / "scripts"
    / "vector_ingest.py"
)
_MODULE_NAME = "vector_ingest_under_test"
_SPEC = importlib.util.spec_from_file_location(_MODULE_NAME, _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
vi: Any = importlib.util.module_from_spec(_SPEC)
# dataclasses 在 Python 3.14 会通过 sys.modules 反查模块，必须先注册。
sys.modules[_MODULE_NAME] = vi
_SPEC.loader.exec_module(vi)


def _options(**overrides: Any) -> Any:
    """构造测试用 IngestOptions，默认使用假凭证."""
    oss = vi.OssConfig(
        bucket="bucket",
        index="index",
        region="cn-shanghai",
        account_id="123",
        endpoint="example.com",
        access_key_id="ak",
        access_key_secret="sk",
    )
    values: dict[str, Any] = {"oss": oss, "dashscope_api_key": "dashscope-key"}
    values.update(overrides)
    return vi.IngestOptions(**values)


# ── 仓库识别 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("owner/repo", "owner/repo"),
        ("/owner/repo/", "owner/repo"),
        (
            "XMZZUZHI/Astrbot/astrbot_plugin_ots_memory",
            "XMZZUZHI/Astrbot/astrbot_plugin_ots_memory",
        ),
    ],
)
def test_normalize_repo_accepts(value: str, expected: str) -> None:
    """合法的两级或三级仓库标识应被归一化."""
    assert vi.normalize_repo(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "repo", "owner//repo", "owner/../repo", "owner/repo;rm"],
)
def test_normalize_repo_rejects(value: str) -> None:
    """空段、路径逃逸与非法字符应被拒绝."""
    assert vi.normalize_repo(value) is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://cnb.cool/XMZZUZHI/Astrbot/astrbot_plugin_ots_memory.git",
            "XMZZUZHI/Astrbot/astrbot_plugin_ots_memory",
        ),
        ("git@github.com:owner/repo.git", "owner/repo"),
        ("ssh://git@github.com/owner/repo.git", "owner/repo"),
        ("", None),
        ("https://example.com/justone", None),
    ],
)
def test_parse_repo_from_remote(url: str, expected: str | None) -> None:
    """https / ssh / scp 形式的 remote 都应解析出仓库标识."""
    assert vi.parse_repo_from_remote(url) == expected


@pytest.mark.parametrize(
    ("repo", "expected"),
    [
        ("XMZZUZHI/Astrbot/astrbot_plugin_ots_memory", "Astrbot"),
        ("owner/repo", "owner"),
    ],
)
def test_repo_group(repo: str, expected: str) -> None:
    """CNB 三级路径取第二段，GitHub 两级路径取 owner."""
    assert vi.repo_group(repo) == expected


def test_repo_hash_is_case_insensitive() -> None:
    """仓库哈希应忽略大小写并保持固定长度."""
    assert vi.repo_hash("Owner/Repo") == vi.repo_hash("owner/repo")
    assert len(vi.repo_hash("owner/repo")) == 16


# ── 主键与旧切片清理 ────────────────────────────────────────────────────────


def test_default_key_uses_source_prefix() -> None:
    """默认主键应由仓库前缀、来源哈希与切片号组成."""
    prefix = vi._source_key_prefix("cnb", "o/r", "docs/a.md")
    key = vi._default_key("cnb", "o/r", "docs/a.md", 3)
    assert key == f"{prefix}0003"
    assert key == vi._default_key("cnb", "o/r", "docs/a.md", 3)
    assert vi._source_key_prefix("cnb", "o/r", "docs/b.md") != prefix


def test_stale_keys_filters_by_source_prefix() -> None:
    """只返回同来源前缀、且不在保留集合中的主键."""
    prefix = vi._source_key_prefix("cnb", "o/r", "docs/a.md")
    vectors = [
        {"key": f"{prefix}0000"},
        {"key": f"{prefix}0001"},
        {"key": "cnb:other:0000"},
        {"key": 42},
    ]
    assert vi.stale_keys(vectors, prefix, {f"{prefix}0000"}) == [f"{prefix}0001"]


# ── 切片与批次 ──────────────────────────────────────────────────────────────


def test_chunk_text_empty_and_short() -> None:
    """空白文本返回空列表，短文本原样返回."""
    assert vi.chunk_text(" \n\n ", 10, 2) == []
    assert vi.chunk_text("hello", 10, 2) == ["hello"]


def test_chunk_text_rejects_non_positive_size() -> None:
    """chunk_size 必须为正数."""
    with pytest.raises(vi.IngestError, match="chunk_size"):
        vi.chunk_text("hello", 0, 0)


def test_chunk_text_splits_long_text() -> None:
    """长文本应被切成多个非空切片，且不超过 chunk_size."""
    text = "第一段。" * 50
    chunks = vi.chunk_text(text, 30, 5)
    assert len(chunks) > 1
    assert all(chunks)
    assert all(len(chunk) <= 30 for chunk in chunks)


def test_chunk_batches_splits_without_loss() -> None:
    """分批应保留全部元素与顺序."""
    chunks = [vi.Chunk(key=str(index), text="x", metadata={}) for index in range(5)]
    batches = list(vi._chunk_batches(chunks, 2))
    assert [[chunk.key for chunk in batch] for batch in batches] == [
        ["0", "1"],
        ["2", "3"],
        ["4"],
    ]


# ── V4 签名 ─────────────────────────────────────────────────────────────────


def test_build_canonical_request_sorts_headers() -> None:
    """规范请求应把 header 名转小写并按字典序排列."""
    canonical = vi.build_canonical_request(
        "POST",
        "/bucket/",
        "putVectors",
        {
            "x-oss-date": "20260101T000000Z",
            "Content-Type": "application/json",
        },
    )
    assert canonical.startswith("POST\n/bucket/\nputVectors\n")
    assert "content-type:application/json\n" in canonical
    assert "x-oss-date:20260101T000000Z\n" in canonical
    assert canonical.endswith("\nUNSIGNED-PAYLOAD")


def test_sign_v4_is_deterministic() -> None:
    """相同输入签名稳定，查询串变化则签名变化."""
    headers = {
        "content-type": "application/json",
        "x-oss-date": "20260101T000000Z",
    }
    first = vi.sign_v4(
        "POST",
        "/bucket/",
        "putVectors",
        headers,
        "AKID",
        "SECRET",
        "cn-shanghai",
        "20260101T000000Z",
    )
    second = vi.sign_v4(
        "POST",
        "/bucket/",
        "putVectors",
        headers,
        "AKID",
        "SECRET",
        "cn-shanghai",
        "20260101T000000Z",
    )
    changed = vi.sign_v4(
        "POST",
        "/bucket/",
        "queryVectors",
        headers,
        "AKID",
        "SECRET",
        "cn-shanghai",
        "20260101T000000Z",
    )
    assert first == second
    assert first != changed
    assert first.startswith(
        "OSS4-HMAC-SHA256 Credential=AKID/20260101/cn-shanghai/oss/"
        "aliyun_v4_request,Signature="
    )


# ── 错误脱敏 ────────────────────────────────────────────────────────────────


def test_describe_http_error_redacts_by_default() -> None:
    """默认错误信息不应包含响应体或 message."""
    body = json.dumps(
        {
            "Code": "NoSuchIndex",
            "Message": "secret knowledge text",
            "RequestId": "rid-1",
        }
    ).encode("utf-8")
    vi._set_debug_errors(False)
    message = vi._describe_http_error(404, body)
    assert "HTTP 404" in message
    assert "NoSuchIndex" in message
    assert "request_id=rid-1" in message
    assert "secret knowledge text" not in message


def test_describe_http_error_unwraps_nested_error() -> None:
    """OSS 的 {"Error": {...}} 结构也应提取 code 与 request_id."""
    body = json.dumps({"Error": {"Code": "NoSuchBucket", "RequestId": "rid-3"}}).encode(
        "utf-8"
    )
    vi._set_debug_errors(False)
    message = vi._describe_http_error(404, body)
    assert "NoSuchBucket" in message
    assert "request_id=rid-3" in message


def test_describe_http_error_debug_includes_body() -> None:
    """--debug 下才附带 message 与响应体."""
    body = json.dumps(
        {"Code": "NoSuchIndex", "Message": "secret knowledge text"}
    ).encode("utf-8")
    vi._set_debug_errors(True)
    try:
        message = vi._describe_http_error(404, body)
    finally:
        vi._set_debug_errors(False)
    assert "secret knowledge text" in message


def test_describe_http_error_reads_request_id_header() -> None:
    """非 JSON 响应也应从 header 提取 request_id."""
    message = vi._describe_http_error(403, b"not-json", {"x-oss-request-id": "rid-2"})
    assert "request_id=rid-2" in message
    assert "not-json" not in message


def test_preview_suffix_redacts_by_default() -> None:
    """响应体预览默认隐藏，--debug 时展示."""
    vi._set_debug_errors(False)
    assert "已隐藏" in vi._preview_suffix(b"secret")
    vi._set_debug_errors(True)
    try:
        assert "secret" in vi._preview_suffix(b"secret")
    finally:
        vi._set_debug_errors(False)


# ── 切片构造 ────────────────────────────────────────────────────────────────


def test_chunks_from_text_metadata(tmp_path: Path) -> None:
    """文本切片应带来源、仓库、标题与切片序号."""
    path = tmp_path / "doc.md"
    path.write_text("# Title\n\n" + "正文。" * 30, encoding="utf-8")
    options = _options(repo="o/r", group="o", chunk_size=40, chunk_overlap=0)
    chunks = vi._chunks_from_text(path, options)
    source = vi._source_label(path)
    prefix = vi._source_key_prefix("cnb", "o/r", source)
    assert chunks
    assert all(chunk.key.startswith(prefix) for chunk in chunks)
    assert chunks[0].metadata["title"] == "Title"
    assert all(chunk.metadata["repo"] == "o/r" for chunk in chunks)


def test_chunks_from_jsonl_custom_key(tmp_path: Path) -> None:
    """JSONL 自定义 key 应被强制加上仓库命名空间."""
    path = tmp_path / "doc.jsonl"
    path.write_text(
        '{"text": "alpha", "key": "custom"}\n'
        '{"content": "beta", "metadata": {"kind": "pitfall"}}\n',
        encoding="utf-8",
    )
    options = _options(repo="o/r")
    chunks = vi._chunks_from_jsonl(path, options)
    repo_prefix = vi._repo_key_prefix("cnb", "o/r")
    assert chunks[0].key == f"{repo_prefix}:custom"
    assert chunks[1].key.startswith(
        vi._source_key_prefix("cnb", "o/r", vi._source_label(path))
    )
    assert chunks[1].metadata["kind"] == "pitfall"


# ── 参数校验 ────────────────────────────────────────────────────────────────


def test_build_options_check_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """--check 不需要仓库识别，也不要求 DashScope Key."""
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "sk")
    args = vi.build_parser().parse_args(["--check", "--account-id", "123"])
    options = vi._build_options(args)
    assert options.repo == ""
    assert options.oss.index == "cnbknowledge"


def test_build_options_rejects_delete_without_repo() -> None:
    """--delete 必须显式给出 --repo."""
    args = vi.build_parser().parse_args(["--delete", "--yes"])
    with pytest.raises(vi.IngestError, match="必须显式指定 --repo"):
        vi._build_options(args)


def test_build_options_rejects_prune_with_query() -> None:
    """--prune 只能用于写入模式."""
    args = vi.build_parser().parse_args(["--prune", "--query", "x"])
    with pytest.raises(vi.IngestError, match="--prune 只能用于写入模式"):
        vi._build_options(args)


def test_build_options_rejects_source_without_delete() -> None:
    """--source 只能与 --delete 搭配."""
    args = vi.build_parser().parse_args(["--source", "docs/a.md", "docs/a.md"])
    with pytest.raises(vi.IngestError, match="--source 只能与 --delete"):
        vi._build_options(args)


def test_parser_parses_new_flags() -> None:
    """新增参数应能被解析."""
    args = vi.build_parser().parse_args(
        ["--check", "--debug", "--prune", "--yes", "--source", "docs/a.md"]
    )
    assert args.check is True
    assert args.debug is True
    assert args.prune is True
    assert args.yes is True
    assert args.source == "docs/a.md"
