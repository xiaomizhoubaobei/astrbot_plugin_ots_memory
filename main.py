"""Main entry for the Bailian long-term memory plugin."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Optional

from astrbot.api import AstrBotConfig, FunctionTool, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from mcp.types import CallToolResult, TextContent
from pydantic import Field
from pydantic.dataclasses import dataclass

from .client import DEFAULT_API_BASE_URL, BailianMemoryClient

_MAX_USER_ID_LEN = 64
_MAX_MESSAGES = 50


def _segment_texts(segments: Any) -> list[str]:
    """取出消息段里的非空文本，跳过纯图片/表情等无文本段."""
    texts = []
    for seg in segments or []:
        content = getattr(seg, "text", None)
        if content:
            texts.append(content)
    return texts


def _safe_error_text(exc: BaseException, limit: int = 200) -> str:
    """把异常文本压成可安全落日志的摘要.

    客户端抛出的 ``RuntimeError`` 已只含状态与请求 ID，但其它异常（如
    ``json`` 解析错误）可能携带上游响应片段。此处统一截断，避免异常里的
    响应体被完整铺进日志。
    """
    text = str(exc).strip().replace("\n", " ")
    return text[:limit] if text else "<无描述>"


def _build_user_id(event: AstrMessageEvent) -> str:
    """由消息事件构造百炼记忆实体 ID.

    使用「平台适配器 ID + 发送者 ID」隔离不同平台上的同名用户；超过百炼
    64 字符上限时改用稳定哈希，避免截断造成不同用户碰撞。
    """
    sender_id = (event.get_sender_id() or "").strip()
    if not sender_id:
        return ""

    platform_id = ""
    try:
        platform_id = (event.get_platform_id() or "").strip()
    except Exception:
        # 个别平台适配器未实现 get_platform_id，退化为仅用发送者 ID。
        platform_id = ""

    raw = f"{platform_id}:{sender_id}" if platform_id else sender_id
    if len(raw) <= _MAX_USER_ID_LEN:
        return raw

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    # 前缀 8 字符 + 56 位十六进制，总长 64，满足百炼 user_id 上限。
    return f"astrbot_{digest[:_MAX_USER_ID_LEN - 8]}"


def _tool_result(text: str, *, is_error: bool = False) -> ToolExecResult:
    """构造工具执行结果.

    ``ToolExecResult`` 是 ``str | CallToolResult`` 的联合别名，**不可直接调用**；
    需要表达"出错"语义时必须显式包成 ``CallToolResult(isError=True)``，
    否则运行时会抛 ``TypeError: 'types.UnionType' object is not callable``。
    """
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        isError=is_error,
    )


def _event_user_id(context: ContextWrapper[AstrAgentContext]) -> str:
    """从工具调用上下文里取出当前消息事件并构造记忆实体 ID."""
    event = getattr(context.context, "event", None)
    if event is None:
        return ""
    return _build_user_id(event)


@dataclass
class RecallMemoryTool(FunctionTool[AstrAgentContext]):
    """长期记忆检索工具."""

    name: str = "recall_memory"
    description: str = (
        "从长期记忆库中检索与当前话题相关的历史记忆。"
        "当需要回忆用户之前告知的信息、偏好、约定时使用。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用于语义检索的自然语言查询，描述要回忆的内容",
                }
            },
            "required": ["query"],
        }
    )

    # 运行时注入的宿主插件引用：不参与工具 JSON Schema，也不序列化。
    # 类型须写成 Any：BailianMemoryPlugin 并非 pydantic 可建模类型，直接标注会
    # 在实例化工具时抛 PydanticSchemaGenerationError（宿主 FunctionTool 未开启
    # arbitrary_types_allowed，见 astrbot/core/agent/tool.py）。
    plugin: Optional[Any] = Field(default=None, exclude=True)

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        """执行记忆检索."""
        query = kwargs.get("query", "").strip()
        if not query:
            return _tool_result("query 参数不能为空", is_error=True)

        if not self.plugin or not self.plugin.client:
            return _tool_result("记忆插件客户端未初始化", is_error=True)

        user_id = _event_user_id(context)
        if not user_id:
            return _tool_result("无法确定当前用户，暂时不能检索记忆。", is_error=True)

        try:
            results = await self.plugin.client.search_memories(
                user_id=user_id,
                query=query,
                top_k=self.plugin.top_k,
                min_score=self.plugin.min_score,
                rewrite=self.plugin.rewrite,
                rerank=self.plugin.rerank,
                plan_version=self.plugin.plan_version,
                memory_library_id=self.plugin.memory_library_id or None,
            )
            lines = []
            for item in results:
                content = str(item.get("content", "")).strip()
                if content:
                    lines.append(content)
            if not lines:
                return _tool_result("没有找到相关的历史记忆。")

            return _tool_result("\n".join(lines))
        except Exception as e:
            # 只记异常类型与文本摘要：上游错误体可能回显用户记忆内容，
            # 原始异常文本不得进日志，更不得回吐给模型 / 终端用户。
            logger.error(
                f"[bailian_memory] recall_memory 失败: {type(e).__name__}: "
                f"{_safe_error_text(e)}"
            )
            return _tool_result("检索记忆失败，请稍后重试。", is_error=True)


@dataclass
class SaveMemoryTool(FunctionTool[AstrAgentContext]):
    """长期记忆保存工具."""

    name: str = "save_memory"
    description: str = (
        "将重要事实、用户偏好或约定主动保存到长期记忆库。"
        "当用户告知重要个人信息、做出约定、或提到值得记住的事时使用。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "要保存的事实或信息，用一两句话清晰描述",
                }
            },
            "required": ["fact"],
        }
    )

    # 运行时注入的宿主插件引用：不参与工具 JSON Schema，也不序列化。
    plugin: Optional[Any] = Field(default=None, exclude=True)

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        """执行记忆保存."""
        fact = kwargs.get("fact", "").strip()
        if not fact:
            return _tool_result("fact 参数不能为空", is_error=True)

        if not self.plugin or not self.plugin.client:
            return _tool_result("记忆插件客户端未初始化", is_error=True)

        user_id = _event_user_id(context)
        if not user_id:
            return _tool_result("无法确定当前用户，暂时不能保存记忆。", is_error=True)

        try:
            await self.plugin.client.add_memories(
                user_id=user_id,
                text=fact,
                memory_library_id=self.plugin.memory_library_id or None,
                profile_schema=self.plugin.profile_schema,
                project_id=self.plugin.project_id,
            )
            return _tool_result(f"已保存记忆：{fact}")
        except Exception as e:
            logger.error(
                f"[bailian_memory] save_memory 失败: {type(e).__name__}: "
                f"{_safe_error_text(e)}"
            )
            return _tool_result("保存记忆失败，请稍后重试。", is_error=True)


class BailianMemoryPlugin(Star):
    """Bailian Memory Plugin Star 类."""

    def __init__(self, context: Context, config: AstrBotConfig):
        """初始化插件配置并注册 Tool."""
        super().__init__(context)
        self.config = config

        self.api_base_url = str(
            config.get("api_base_url", DEFAULT_API_BASE_URL)
        ).strip()
        self.api_key = str(config.get("dashscope_api_key", "")).strip()
        self.memory_library_id = str(config.get("memory_library_id", "")).strip()
        self.profile_schema = str(config.get("profile_schema", "")).strip()
        self.project_id = str(config.get("project_id", "")).strip()
        self.top_k = min(100, max(1, int(config.get("top_k", 5))))
        self.min_score = min(1.0, max(0.0, float(config.get("min_score", 0.6))))
        self.rewrite = bool(config.get("rewrite", True))
        self.rerank = bool(config.get("rerank", True))
        self.auto_record = bool(config.get("auto_record", True))

        plan_version = str(config.get("plan_version", "Pro")).strip() or "Pro"
        if plan_version not in ("Pro", "Lite"):
            logger.warning(
                f"[bailian_memory] plan_version={plan_version} 非法，已回落到 Pro"
            )
            plan_version = "Pro"
        self.plan_version = plan_version

        self.client: Optional[BailianMemoryClient]
        if not self.api_key or not self.api_base_url:
            logger.warning(
                "[bailian_memory] 配置不完整，插件功能已禁用。"
                "请填写 dashscope_api_key（api_base_url 不可为空）。"
            )
            self.client = None
        else:
            self.client = BailianMemoryClient(
                api_key=self.api_key,
                base_url=self.api_base_url,
                memory_library_id=self.memory_library_id,
            )
            self.context.add_llm_tools(RecallMemoryTool(plugin=self))
            self.context.add_llm_tools(SaveMemoryTool(plugin=self))
            logger.info(
                "[bailian_memory] 已加载，"
                f"library={self.memory_library_id or '<default>'}，"
                f"top_k={self.top_k}，min_score={self.min_score}，"
                f"plan={self.plan_version}"
            )

    @filter.on_decorating_result()
    async def on_after_reply(self, event: AstrMessageEvent):
        """对话结束后，异步将本轮消息投递到记忆库沉淀（auto_record 开启时）."""
        if not self.auto_record or self.client is None:
            return

        user_id = _build_user_id(event)
        if not user_id:
            logger.debug("[bailian_memory] 无法确定发送者，跳过本轮自动沉淀")
            return

        messages = [
            {"role": "user", "content": text}
            for text in _segment_texts(event.get_messages())
        ]

        # 只取回复链里第一段文本作为 assistant 内容
        result = event.get_result()
        chains = getattr(result, "chain", []) if result else []
        reply_texts = _segment_texts(chains)
        result_text = reply_texts[0] if reply_texts else None

        if not messages or not result_text:
            return

        # 百炼 messages 最多 50 条；保留最近的用户消息并给 assistant 留一位。
        messages = messages[-(_MAX_MESSAGES - 1) :]
        messages.append({"role": "assistant", "content": result_text})

        client = self.client
        library_id = self.memory_library_id or None
        profile_schema = self.profile_schema
        project_id = self.project_id

        async def _background_save():
            try:
                await client.add_memories(
                    user_id=user_id,
                    messages=messages,
                    memory_library_id=library_id,
                    profile_schema=profile_schema,
                    project_id=project_id,
                )
                logger.debug(
                    f"[bailian_memory] 自动沉淀记忆成功，共 {len(messages)} 条"
                )
            except Exception as e:
                logger.warning(
                    f"[bailian_memory] 自动沉淀记忆失败: {type(e).__name__}: "
                    f"{_safe_error_text(e)}"
                )

        asyncio.create_task(_background_save())
