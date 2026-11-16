"""Client for the Alibaba Cloud Bailian (Model Studio) Memory REST API."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import aiohttp
from astrbot.api import logger

# 百炼记忆库默认接入点。若使用业务空间专属域名（如
# https://<workspaceId>.cn-beijing.maas.aliyuncs.com/api/v2/apps/memory），
# 可通过插件配置 api_base_url 覆盖。
DEFAULT_API_BASE_URL = "https://dashscope.aliyuncs.com/api/v2/apps/memory"

# 429 限流与 5xx 采用指数退避；4xx（非限流）属于参数 / 鉴权问题，快速失败。
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_RETRY_DELAYS = (1, 2, 4)
_MAX_USER_ID_LEN = 64
_MAX_CUSTOM_CONTENT_LEN = 512
_MAX_MESSAGES = 50
_MAX_REQUEST_ID_LEN = 64


class BailianMemoryClient:
    """轻量级异步百炼记忆库客户端.

    直接调用百炼记忆库 REST API，不引入额外 SDK。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_API_BASE_URL,
        memory_library_id: str = "",
        timeout: float = 30.0,
    ) -> None:
        """初始化客户端.

        Args:
            api_key: 百炼 API Key（Bearer Token）.
            base_url: 记忆库服务地址，可覆盖为业务空间专属域名.
            memory_library_id: 记忆库 ID；为空时使用服务端默认库.
            timeout: 单次请求超时秒数.
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.memory_library_id = memory_library_id
        self.timeout = timeout

    async def _post_once(
        self, url: str, headers: Dict[str, str], body: bytes
    ) -> tuple[int, str, str]:
        """发送一次 POST 请求，返回状态码、响应文本与 request_id."""
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as session:
            # 出站边界：禁止跟随重定向，避免请求被带向配置地址之外的主机。
            async with session.post(
                url, headers=headers, data=body, allow_redirects=False
            ) as resp:
                text = await resp.text()
                request_id = str(resp.headers.get("x-request-id", ""))[
                    :_MAX_REQUEST_ID_LEN
                ]
                return resp.status, text, request_id

    @staticmethod
    def _extract_request_id(text: str) -> str:
        """从错误响应中只提取 request_id，绝不保留响应体其余内容.

        错误体可能回显用户记忆内容，异常与日志都不得携带它。
        """
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return ""
        if not isinstance(data, dict):
            return ""
        return str(data.get("request_id", ""))[:_MAX_REQUEST_ID_LEN]

    async def _request(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """发送 JSON 请求并返回解析后的响应.

        Args:
            path: 相对 base_url 的接口路径.
            payload: JSON 请求体.

        Returns:
            解析后的响应字典.

        Raises:
            RuntimeError: 网络异常、非 2xx 或响应不是合法 JSON.
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "astrbot-plugin-bailian-memory",
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

        last_error: Optional[BaseException] = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                status, text, request_id = await self._post_once(url, headers, body)
            except aiohttp.ClientError as exc:
                # 网络层异常才重试；异常文本只保留类型，避免携带请求细节。
                last_error = exc
                if attempt < len(_RETRY_DELAYS):
                    logger.warning(
                        f"[bailian_memory] {path} 网络异常 "
                        f"({type(exc).__name__})，{_RETRY_DELAYS[attempt]}s 后重试"
                    )
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                    continue
                raise RuntimeError(
                    f"百炼记忆接口网络异常: {type(exc).__name__}"
                ) from exc

            if status < 300:
                try:
                    return json.loads(text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("百炼记忆接口返回非 JSON 响应") from exc

            request_id = request_id or self._extract_request_id(text)
            if status in _RETRY_STATUSES and attempt < len(_RETRY_DELAYS):
                logger.warning(
                    f"[bailian_memory] {path} 调用失败: status={status} "
                    f"request_id={request_id or '<none>'}，"
                    f"{_RETRY_DELAYS[attempt]}s 后重试"
                )
                await asyncio.sleep(_RETRY_DELAYS[attempt])
                continue

            logger.error(
                f"[bailian_memory] {path} 调用失败: "
                f"status={status} request_id={request_id or '<none>'}"
            )
            raise RuntimeError(
                f"百炼记忆接口错误 [status={status}] "
                f"request_id={request_id or '<none>'}"
            )

        # 理论上不可达：循环最后一轮要么返回、要么抛错；保留兜底以防未来改动。
        raise RuntimeError(  # pragma: no cover
            f"百炼记忆接口调用失败: {type(last_error).__name__ if last_error else '未知错误'}"
        )

    @staticmethod
    def _validate_user_id(user_id: str) -> str:
        """校验并返回记忆实体 ID."""
        value = user_id.strip()
        if not value:
            raise ValueError("user_id 不能为空")
        if len(value) > _MAX_USER_ID_LEN:
            raise ValueError(f"user_id 超长（{len(value)} > {_MAX_USER_ID_LEN} 字符）")
        return value

    async def search_memories(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        *,
        rewrite: bool = True,
        rerank: bool = True,
        plan_version: str = "Pro",
        memory_library_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """语义检索用户记忆.

        Args:
            user_id: 记忆实体 ID（最大 64 字符）.
            query: 检索语句.
            top_k: 最大返回条数（1~100）.
            min_score: 相似度阈值（0.0~1.0）；0 表示不下发阈值.
            rewrite: 是否改写查询.
            rerank: 是否重排结果.
            plan_version: ``Pro`` 或 ``Lite``.
            memory_library_id: 覆盖客户端默认记忆库 ID.

        Returns:
            记忆节点列表.

        Raises:
            ValueError: 参数不合法.
            RuntimeError: 上游调用失败.
        """
        entity_id = self._validate_user_id(user_id)
        query_text = query.strip()
        if not query_text:
            raise ValueError("query 不能为空")
        if not 1 <= top_k <= 100:
            raise ValueError("top_k 必须在 1~100 之间")
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score 必须在 0.0~1.0 之间")
        if plan_version not in ("Pro", "Lite"):
            raise ValueError("plan_version 只能是 Pro 或 Lite")

        payload: Dict[str, Any] = {
            "user_id": entity_id,
            "query": query_text,
            "max_results": top_k,
            "rewrite": rewrite,
            "rerank": rerank,
            "plan_version": plan_version,
        }
        if min_score > 0:
            payload["similarity_threshold"] = min_score
        library_id = memory_library_id or self.memory_library_id
        if library_id:
            payload["memory_library_id"] = library_id

        result = await self._request("memory_nodes/search", payload)
        nodes = result.get("memory_nodes", [])
        return nodes if isinstance(nodes, list) else []

    async def add_memories(
        self,
        user_id: str,
        messages: Optional[List[Dict[str, str]]] = None,
        text: Optional[str] = None,
        *,
        memory_library_id: Optional[str] = None,
        profile_schema: str = "",
        project_id: str = "",
        meta_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """写入记忆.

        ``messages`` 与 ``text`` 二选一：前者用于整轮对话沉淀，后者用于单条事实.

        Args:
            user_id: 记忆实体 ID（最大 64 字符）.
            messages: 对话消息列表（最多 50 条）.
            text: 单条事实文本（最大 512 字符）.
            memory_library_id: 覆盖客户端默认记忆库 ID.
            profile_schema: 画像模板 ID；为空则不提取画像.
            project_id: 事实记忆规则 ID；为空则使用默认规则.
            meta_data: 自定义元数据.

        Returns:
            上游响应字典.

        Raises:
            ValueError: 参数不合法.
            RuntimeError: 上游调用失败.
        """
        entity_id = self._validate_user_id(user_id)
        if messages and text:
            raise ValueError("messages 与 text 互斥，请二选一")
        if not messages and not text:
            raise ValueError("messages 和 text 不能同时为空")

        payload: Dict[str, Any] = {"user_id": entity_id}
        if messages:
            if len(messages) > _MAX_MESSAGES:
                raise ValueError(
                    f"消息条数超限（{len(messages)} > {_MAX_MESSAGES} 条）"
                )
            payload["messages"] = messages
        else:
            content = (text or "").strip()
            if not content:
                raise ValueError("text 不能为空")
            if len(content) > _MAX_CUSTOM_CONTENT_LEN:
                raise ValueError(
                    f"text 超长（{len(content)} > {_MAX_CUSTOM_CONTENT_LEN} 字符）"
                )
            payload["custom_content"] = content

        library_id = memory_library_id or self.memory_library_id
        if library_id:
            payload["memory_library_id"] = library_id
        if profile_schema:
            payload["profile_schema"] = profile_schema
        if project_id:
            payload["project_id"] = project_id
        if meta_data:
            payload["meta_data"] = meta_data

        return await self._request("add", payload)
