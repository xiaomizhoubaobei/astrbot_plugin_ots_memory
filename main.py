import asyncio
import logging
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import AstrBotConfig, FunctionTool, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from .client import OTSMemoryClient


@dataclass
class RecallMemoryTool(FunctionTool[AstrAgentContext]):
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

    plugin: object = Field(default=None, exclude=True)

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs,
    ) -> ToolExecResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolExecResult(is_error=True, result="query 参数不能为空")

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
                return ToolExecResult(result="没有找到相关的历史记忆。")

            lines = []
            for item in results:
                unit = item.get("unit", {})
                text = unit.get("text", "")
                score = item.get("score", 0.0)
                lines.append(f"[相关度 {score:.2f}] {text}")

            return ToolExecResult(result="\n".join(lines))
        except Exception as e:
            logger.error(f"[ots_memory] recall_memory 失败: {e}")
            return ToolExecResult(is_error=True, result=f"检索记忆失败: {e}")


@dataclass
class SaveMemoryTool(FunctionTool[AstrAgentContext]):
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

    plugin: object = Field(default=None, exclude=True)

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs,
    ) -> ToolExecResult:
        fact = kwargs.get("fact", "").strip()
        if not fact:
            return ToolExecResult(is_error=True, result="fact 参数不能为空")

        try:
            await self.plugin.client.add_memories(
                store_name=self.plugin.store_name,
                app_id=self.plugin.app_id,
                tenant_id=self.plugin.tenant_id,
                text=fact,
            )
            return ToolExecResult(result=f"已保存记忆：{fact}")
        except Exception as e:
            logger.error(f"[ots_memory] save_memory 失败: {e}")
            return ToolExecResult(is_error=True, result=f"保存记忆失败: {e}")


class OTSMemoryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.store_name: str = config.get("memory_store_name", "huawu_memory")
        self.app_id: str = config.get("app_id", "astrbot")
        self.tenant_id: str = "default"
        self.top_k: int = int(config.get("top_k", 5))
        self.min_score: float = float(config.get("min_score", 0.4))
        self.auto_record: bool = bool(config.get("auto_record", True))

        endpoint = config.get("endpoint", "")
        instance_name = config.get("instance_name", "")
        region = config.get("region", "cn-shanghai")
        ak_id = config.get("access_key_id", "")
        ak_secret = config.get("access_key_secret", "")

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
        """对话结束后，异步将本轮消息投递到记忆库沉淀（auto_record 开启时）"""
        if not self.auto_record or self.client is None:
            return

        messages = []
        for seg in event.get_messages():
            content = getattr(seg, "text", None)
            if content:
                messages.append({"role": "user", "content": content})

        result_text = None
        result = event.get_result()
        if result:
            chains = getattr(result, "chain", [])
            for seg in chains:
                content = getattr(seg, "text", None)
                if content:
                    result_text = content
                    break

        if result_text:
            messages.append({"role": "assistant", "content": result_text})

        if not messages:
            return

        try:
            asyncio.ensure_future(
                self.client.add_memories(
                    store_name=self.store_name,
                    app_id=self.app_id,
                    tenant_id=self.tenant_id,
                    messages=messages,
                )
            )
        except Exception as e:
            logger.debug(f"[ots_memory] 异步记忆沉淀失败: {e}")
