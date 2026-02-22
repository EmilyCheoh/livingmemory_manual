"""
LivingMemoryManual - LivingMemory 手动记忆注入伴生插件
直接借用同进程中 LivingMemory 插件的 MemoryEngine 实例，
调用其 add_memory() 接口向记忆库写入手动编写的记忆条目。

核心策略：运行时发现 LivingMemory 插件实例，获取其 memory_engine。
不需要任何独立连接、不需要 Embedding Provider、不需要数据库路径——
MemoryEngine.add_memory() 内部自动处理 BM25、Faiss、SQLite 三路写入。

F(A) = A(F)
"""

import re
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DEFAULT_IMPORTANCE = 0.8  # 手动插入的记忆默认重要性（高于自动总结的 0.5）


@register(
    "LivingMemoryManual",
    "FelisAbyssalis",
    "LivingMemory 手动记忆注入插件 - 向 LivingMemory 的记忆库手动插入记忆条目",
    "1.0.0",
    "",
)
class LivingMemoryManual(Star):
    """
    AstrBot 伴生插件：为 LivingMemory 提供手动记忆插入能力。

    设计原理：
    LivingMemory 使用 SQLite + Faiss 作为存储层，全部运行在同一个
    Python 进程中。我们只需要在运行时找到 LivingMemory 的插件实例，
    拿到它的 memory_engine，然后调用 add_memory() 即可。

    与 Mnemosyne 版本的区别：
    - 不需要 pymilvus 依赖
    - 不需要连接池探测
    - 不需要手动构建数据格式
    - 不需要自己获取 Embedding Provider
    - add_memory() 内部自动处理 BM25/Faiss/SQLite 三路写入
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.context = context

        self._memory_engine = None
        self._default_importance = self.config.get(
            "default_importance", DEFAULT_IMPORTANCE
        )

        logger.info("LivingMemoryManual 插件初始化完成，将在首次使用时连接 LivingMemory")

    # -----------------------------------------------------------------------
    # 运行时发现 LivingMemory 实例
    # -----------------------------------------------------------------------

    def _discover_memory_engine(self) -> Any | None:
        """
        在运行时遍历已加载的 Star 插件，找到 LivingMemory 实例，
        获取其 MemoryEngine。

        LivingMemory 的实例结构:
            plugin.initializer.memory_engine  -> MemoryEngine 实例
        """
        if self._memory_engine is not None:
            return self._memory_engine

        try:
            # AstrBot 的 context 中保存了所有已加载的 Star 插件实例
            star_manager = getattr(self.context, "star_manager", None)
            if not star_manager:
                logger.warning("LivingMemoryManual: 无法获取 star_manager")
                return None

            # 遍历已注册的 Star 实例
            star_insts = getattr(star_manager, "star_insts", None)
            if not star_insts:
                logger.warning("LivingMemoryManual: 无法获取 star_insts")
                return None

            for star_inst in star_insts:
                # star_inst 可能是 StarMetadata 容器，获取实际的 Star 对象
                star_obj = getattr(star_inst, "star_cls", None)
                if star_obj is None:
                    star_obj = star_inst

                # 检查类名是否为 LivingMemoryPlugin
                class_name = type(star_obj).__name__
                if class_name == "LivingMemoryPlugin":
                    # 从 LivingMemory 实例中获取 MemoryEngine
                    initializer = getattr(star_obj, "initializer", None)
                    if initializer is None:
                        logger.warning(
                            "LivingMemoryManual: 找到 LivingMemoryPlugin 但 "
                            "initializer 为 None"
                        )
                        return None

                    memory_engine = getattr(initializer, "memory_engine", None)
                    if memory_engine is None:
                        logger.warning(
                            "LivingMemoryManual: 找到 LivingMemoryPlugin 但 "
                            "memory_engine 尚未初始化"
                        )
                        return None

                    logger.info(
                        "LivingMemoryManual: 成功获取 LivingMemory 的 "
                        "MemoryEngine 实例"
                    )
                    self._memory_engine = memory_engine
                    return memory_engine

            logger.warning(
                "LivingMemoryManual: 未找到 LivingMemoryPlugin 实例。"
                "请确保 LivingMemory 插件已安装并启用"
            )
            return None

        except Exception as e:
            logger.error(
                f"LivingMemoryManual: 发现 LivingMemory 实例时出错: {e}",
                exc_info=True,
            )
            return None

    # -----------------------------------------------------------------------
    # 核心功能: insert_memory
    # -----------------------------------------------------------------------

    async def insert_memory(
        self,
        text: str,
        session_id: str,
        persona_id: str | None = None,
        importance: float | None = None,
    ) -> dict[str, Any]:
        """
        向 LivingMemory 的记忆库中插入一条手动记忆。

        直接调用 MemoryEngine.add_memory()，内部自动处理：
        - BM25 索引（jieba 分词 + FTS5）
        - Faiss 向量索引（Embedding 向量化）
        - SQLite documents 表（元数据存储）

        Args:
            text: 记忆文本内容
            session_id: 会话 ID（来自 event.unified_msg_origin）
            persona_id: 人格 ID（可选）
            importance: 重要性 0-1（可选，默认使用配置值）

        Returns:
            包含 success, message, memory_id 字段的结果字典
        """
        # --- 前置检查 ---
        if not text or not text.strip():
            return {"success": False, "message": "记忆文本不能为空"}

        text = text.strip()
        if len(text) > 4096:
            return {
                "success": False,
                "message": f"记忆文本过长 ({len(text)} 字符)，最大 4096 字符",
            }

        # --- 获取 MemoryEngine ---
        memory_engine = self._discover_memory_engine()
        if memory_engine is None:
            return {
                "success": False,
                "message": (
                    "无法获取 LivingMemory 的 MemoryEngine。"
                    "请确保 LivingMemory 插件已安装、已启用，且初始化完成"
                ),
            }

        # --- 确定 importance ---
        if importance is None:
            importance = self._default_importance

        importance = max(0.0, min(1.0, importance))

        # --- 调用 MemoryEngine.add_memory() ---
        try:
            doc_id = await memory_engine.add_memory(
                content=text,
                session_id=session_id,
                persona_id=persona_id,
                importance=importance,
            )

            logger.info(
                f"LivingMemoryManual 成功插入记忆 "
                f"(ID: {doc_id}, Session: {session_id[:24]}..., "
                f"Importance: {importance})"
            )

            return {
                "success": True,
                "message": "记忆插入成功",
                "memory_id": doc_id,
            }

        except Exception as e:
            logger.error(
                f"LivingMemoryManual 插入记忆失败: {e}", exc_info=True
            )
            return {"success": False, "message": f"插入记忆失败: {e}"}

    # -----------------------------------------------------------------------
    # 命令: /lmadd
    # -----------------------------------------------------------------------

    @filter.command("lmadd")
    async def lmadd_cmd(self, event: AstrMessageEvent, text: str):
        """手动向 LivingMemory 的记忆库中插入一条记忆。

        使用示例: /lmadd <Felis Abyssalis 喜欢在深夜调试代码>
        """
        # 从原始消息中提取 <> 之间的内容
        raw_text = event.message_str if hasattr(event, "message_str") else ""

        match = re.search(r"<(.+?)>", raw_text, re.DOTALL)

        if not match:
            yield event.plain_result(
                "用法: /lmadd <记忆文本>\n"
                "请用 < > 包裹记忆内容\n"
                "示例: /lmadd <Felis Abyssalis 喜欢在深夜调试代码>"
            )
            return

        memory_text = match.group(1).strip()

        if not memory_text:
            yield event.plain_result(
                "用法: /lmadd <记忆文本>\n"
                "示例: /lmadd <Felis Abyssalis 喜欢在深夜调试代码>"
            )
            return

        # 获取当前会话 ID
        session_id = event.unified_msg_origin
        if not session_id:
            yield event.plain_result("无法获取当前会话 ID，请稍后重试")
            return

        # 动态获取当前会话的 Persona ID
        persona_id = await self._get_persona_id(event)

        yield event.plain_result("正在插入记忆...")

        result = await self.insert_memory(
            text=memory_text,
            session_id=session_id,
            persona_id=persona_id,
        )

        if result["success"]:
            memory_id = result.get("memory_id", "N/A")
            yield event.plain_result(
                f"记忆插入成功\n"
                f"ID: {memory_id}\n"
                f"重要性: {self._default_importance}\n"
                f"内容: {memory_text[:100]}{'...' if len(memory_text) > 100 else ''}"
            )
        else:
            yield event.plain_result(f"记忆插入失败: {result['message']}")

    # -----------------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------------

    async def _get_persona_id(self, event: AstrMessageEvent) -> str | None:
        """动态获取当前用户会话对应的人格 ID"""
        try:
            conversation_id = (
                await self.context.conversation_manager.get_curr_conversation_id(
                    event.unified_msg_origin
                )
            )
            conversation = await self.context.conversation_manager.get_conversation(
                event.unified_msg_origin, str(conversation_id)
            )
            persona_id = conversation.persona_id if conversation else None

            if not persona_id or persona_id == "[%None]":
                return None
            return persona_id
        except Exception as e:
            logger.warning(f"LivingMemoryManual: 获取当前会话人格失败: {e}")
            return None

    # -----------------------------------------------------------------------
    # 生命周期
    # -----------------------------------------------------------------------

    async def terminate(self):
        """插件停止时清理资源。"""
        # 我们不持有任何独立资源，MemoryEngine 属于 LivingMemory
        self._memory_engine = None
        logger.info("LivingMemoryManual 插件已停止")
