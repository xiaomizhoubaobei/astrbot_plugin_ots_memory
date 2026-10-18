"""Main entry for Tablestore Agent Memory plugin."""

from __future__ import annotations

import asyncio
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

from .client import OTSMemoryClient


def _segment_texts(segments: Any) -> list[str]:
    """取出消息段里的非空文本，跳过纯图片/表情等无文本段."""
    texts = []
    for seg in segments or []:
        content = getattr(seg, "text", None)
        if content:
            texts.append(content)
    return texts


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
    # 类型须写成 Any：OTSMemoryPlugin 并非 pydantic 可建模类型，直接标注会
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
            return _tool_result("OTS 记忆插件客户端未初始化", is_error=True)

        try:
            results = await self.plugin.client.search_memories(
                store_name=self.plugin.store_name,
                app_id=self.plugin.app_id,
                tenant_id=self.plugin.tenant_id,
                query=query,
                top_k=self.plugin.top_k,
                min_score=self.plugin.min_score,
            )
            if not results:
                return _tool_result("没有找到相关的历史记忆。")

            lines = []
            for item in results:
                unit = item.get("unit", {})
                text = unit.get("text", "")
                score = item.get("score", 0.0)
                lines.append(f"[相关度 {score:.2f}] {text}")

            return _tool_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[ots_memory] recall_memory 失败: {e}")
            return _tool_result(f"检索记忆失败: {e}", is_error=True)


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
    # 类型须写成 Any：OTSMemoryPlugin 并非 pydantic 可建模类型，直接标注会
    # 在实例化工具时抛 PydanticSchemaGenerationError（宿主 FunctionTool 未开启
    # arbitrary_types_allowed，见 astrbot/core/agent/tool.py）。
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
            return _tool_result("OTS 记忆插件客户端未初始化", is_error=True)

        try:
            await self.plugin.client.add_memories(
                store_name=self.plugin.store_name,
                app_id=self.plugin.app_id,
                tenant_id=self.plugin.tenant_id,
                text=fact,
            )
            return _tool_result(f"已保存记忆：{fact}")
        except Exception as e:
            logger.error(f"[ots_memory] save_memory 失败: {e}")
            return _tool_result(f"保存记忆失败: {e}", is_error=True)


class OTSMemoryPlugin(Star):
    """Tablestore Agent Memory Plugin Star 类."""

    def __init__(self, context: Context, config: AstrBotConfig):
        """初始化插件配置并注册 Tool."""
        super().__init__(context)
        self.config = config

        self.store_name: str = str(config.get("memory_store_name", "huawu_memory"))
        self.app_id: str = str(config.get("app_id", "astrbot"))
        self.tenant_id: str = "default"
        self.top_k: int = int(config.get("top_k", 5))
        self.min_score: float = float(config.get("min_score", 0.4))
        self.auto_record: bool = bool(config.get("auto_record", True))

        endpoint = config.get("endpoint", "")
        instance_name = config.get("instance_name", "")
        region = config.get("region", "cn-shanghai")
        ak_id = config.get("access_key_id", "")
        ak_secret = config.get("access_key_secret", "")

        self.client: Optional[OTSMemoryClient]
        if not all([endpoint, instance_name, ak_id, ak_secret]):
            logger.warning(
                "[ots_memory] 配置不完整，插件功能已禁用。"
                "请填写 endpoint / instance_name / access_key_id / access_key_secret。"
            )
            self.client = None
        else:
            self.client = OTSMemoryClient(
                endpoint=endpoint,
                instance_name=instance_name,
                access_key_id=ak_id,
                access_key_secret=ak_secret,
                region=region,
            )
            self.context.add_llm_tools(RecallMemoryTool(plugin=self))
            self.context.add_llm_tools(SaveMemoryTool(plugin=self))
            logger.info(
                f"[ots_memory] 已加载，store={self.store_name}，"
                f"app_id={self.app_id}，top_k={self.top_k}，min_score={self.min_score}"
            )

    @filter.on_decorating_result()
    async def on_after_reply(self, event: AstrMessageEvent):
        """对话结束后，异步将本轮消息投递到记忆库沉淀（auto_record 开启时）."""
        if not self.auto_record or self.client is None:
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

        messages.append({"role": "assistant", "content": result_text})

        client = self.client

        async def _background_save():
            try:
                await client.add_memories(
                    store_name=self.store_name,
                    app_id=self.app_id,
                    tenant_id=self.tenant_id,
                    messages=messages,
                )
                logger.debug(f"[ots_memory] 自动沉淀记忆成功，共 {len(messages)} 条")
            except Exception as e:
                logger.warning(f"[ots_memory] 自动沉淀记忆失败: {e}")

        asyncio.create_task(_background_save())
