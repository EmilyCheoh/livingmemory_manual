"""
LivingMemoryManual - LivingMemory 手动记忆注入伴生插件
直接借用同进程中 LivingMemory 插件的 MemoryEngine 实例，
调用其 add_memory() 接口向记忆库写入手动编写的记忆条目。

核心策略：运行时发现 LivingMemory 插件实例，获取其 memory_engine。
不需要任何独立连接、不需要 Embedding Provider、不需要数据库路径——
MemoryEngine.add_memory() 内部自动处理 BM25、Faiss、SQLite 三路写入。

F(A) = A(F)
"""

import json
import re
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.provider.entities import ProviderType


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

        使用 AstrBot v4.15.0 的 Context API:
            context.get_registered_star(name) -> StarMetadata
            context.get_all_stars() -> list[StarMetadata]

        LivingMemory 的实例结构:
            star_metadata.star_cls.initializer.memory_engine -> MemoryEngine
        """
        if self._memory_engine is not None:
            return self._memory_engine

        try:
            # 方法 1: 直接按注册名查找 LivingMemory
            star_meta = self.context.get_registered_star("LivingMemory")
            if star_meta is not None:
                star_obj = getattr(star_meta, "star_cls", None)
                if star_obj is not None:
                    return self._extract_engine(star_obj)

            # 方法 2: 遍历所有已注册的插件，按类名匹配
            all_stars = self.context.get_all_stars()
            if not all_stars:
                logger.warning(
                    "LivingMemoryManual: 已注册插件列表为空"
                )
                return None

            for star_meta in all_stars:
                star_obj = getattr(star_meta, "star_cls", None)
                if star_obj is None:
                    continue

                class_name = type(star_obj).__name__
                if class_name == "LivingMemoryPlugin":
                    return self._extract_engine(star_obj)

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

    def _extract_engine(self, star_obj: Any) -> Any | None:
        """从 LivingMemoryPlugin 实例中提取 MemoryEngine。"""
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

    async def _ensure_db_connection(self, memory_engine: Any) -> bool:
        """
        确保 MemoryEngine 内部的 FAISS DocumentStorage 数据库连接已初始化。

        当 LivingMemory 的初始化顺序异常，或 SQLite 连接在运行时被释放
        （如热重载、错误恢复等），DocumentStorage.engine 可能为 None。
        此方法会探测并重新初始化连接，避免 AssertionError。

        探测路径：
            memory_engine.hybrid_retriever.vector_retriever.faiss_db.document_storage
        """
        try:
            hybrid = getattr(memory_engine, "hybrid_retriever", None)
            if hybrid is None:
                logger.debug(
                    "LivingMemoryManual: 无法探测 hybrid_retriever，跳过连接检查"
                )
                return True  # 无法探测，放行让上层自然报错

            vec_ret = getattr(hybrid, "vector_retriever", None)
            if vec_ret is None:
                logger.debug(
                    "LivingMemoryManual: 无法探测 vector_retriever，跳过连接检查"
                )
                return True

            faiss_db = getattr(vec_ret, "faiss_db", None)
            if faiss_db is None:
                logger.debug(
                    "LivingMemoryManual: 无法探测 faiss_db，跳过连接检查"
                )
                return True

            doc_storage = getattr(faiss_db, "document_storage", None)
            if doc_storage is None:
                logger.debug(
                    "LivingMemoryManual: 无法探测 document_storage，跳过连接检查"
                )
                return True

            engine = getattr(doc_storage, "engine", None)
            if engine is None:
                logger.warning(
                    "LivingMemoryManual: 检测到 DocumentStorage.engine 为 None，"
                    "尝试重新初始化数据库连接..."
                )
                await doc_storage.initialize()
                if doc_storage.engine is not None:
                    logger.info(
                        "LivingMemoryManual: DocumentStorage 数据库连接已重新初始化"
                    )
                    return True
                else:
                    logger.error(
                        "LivingMemoryManual: DocumentStorage 重新初始化失败，"
                        "engine 仍然为 None。清除缓存以便下次重新发现"
                    )
                    self._memory_engine = None
                    return False

            return True

        except Exception as e:
            logger.warning(
                f"LivingMemoryManual: 数据库连接检查出错: {e}，"
                "将继续尝试写入"
            )
            return True  # 检查出错时放行，让上层捕获实际错误

    # -----------------------------------------------------------------------
    # LLM 分析: 提取 topics / key_facts / sentiment
    # -----------------------------------------------------------------------

    _ANALYSIS_SYSTEM_PROMPT = (
        "你是一个记忆分析引擎。给定一段手动写入的记忆文本，"
        "请提取结构化信息并以 JSON 格式返回。"
        "只输出 JSON，不要任何额外文字。"
    )

    _ANALYSIS_USER_PROMPT = (
        "请分析以下记忆文本，提取结构化信息。\n\n"
        "记忆文本：\n{text}\n\n"
        "请用以下 JSON 格式返回：\n"
        '{{\n'
        '  "topics": ["主题1", "主题2"],\n'
        '  "key_facts": ["关键事实1", "关键事实2"],\n'
        '  "sentiment": "positive 或 negative 或 neutral"\n'
        '}}\n\n'
        "要求：\n"
        "- topics: 2-4 个简短的主题短语，概括记忆的核心内容\n"
        "- key_facts: 从文本中提取的独立事实陈述，每条一个要点\n"
        "- sentiment: 整体情感倾向，只能是 positive / negative / neutral 之一\n"
        "- 只输出 JSON，不要 markdown 代码块，不要任何解释"
    )

    async def _analyze_with_llm(self, text: str) -> dict:
        """
        调用 AstrBot 的 LLM Provider 分析记忆文本，
        提取 topics、key_facts、sentiment。

        如果 LLM 调用失败或解析失败，返回合理的默认值。
        """
        try:
            provider = self.context.provider_manager.get_using_provider(
                ProviderType.CHAT_COMPLETION
            )
            if provider is None:
                logger.warning(
                    "LivingMemoryManual: 没有可用的 LLM Provider，"
                    "跳过元数据分析"
                )
                return {}

            response = await provider.text_chat(
                prompt=self._ANALYSIS_USER_PROMPT.format(text=text),
                system_prompt=self._ANALYSIS_SYSTEM_PROMPT,
            )

            result_text = response.completion_text
            if not result_text:
                return {}

            # 清理可能的 markdown 代码块包裹
            result_text = result_text.strip()
            if result_text.startswith("```"):
                result_text = re.sub(
                    r"^```(?:json)?\s*", "", result_text
                )
                result_text = re.sub(r"\s*```$", "", result_text)

            parsed = json.loads(result_text)

            # 校验字段类型
            if not isinstance(parsed.get("topics"), list):
                parsed["topics"] = [text[:50]]
            if not isinstance(parsed.get("key_facts"), list):
                parsed["key_facts"] = [text]
            if parsed.get("sentiment") not in (
                "positive", "negative", "neutral"
            ):
                parsed["sentiment"] = "neutral"

            logger.info(
                f"LivingMemoryManual: LLM 分析完成 - "
                f"topics={parsed['topics']}, "
                f"sentiment={parsed['sentiment']}"
            )
            return parsed

        except json.JSONDecodeError as e:
            logger.warning(
                f"LivingMemoryManual: LLM 返回内容解析失败: {e}"
            )
            return {}
        except Exception as e:
            logger.warning(
                f"LivingMemoryManual: LLM 分析失败，使用默认值: {e}"
            )
            return {}

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

        # --- 使用 LLM 分析文本，生成与 LivingMemory 自动总结一致的 metadata ---
        analyzed = await self._analyze_with_llm(text)

        key_facts = analyzed.get("key_facts", [text])
        # canonical_summary 对齐原版格式: summary | fact1；fact2；...
        canonical_parts = [text]
        if key_facts:
            canonical_parts.append("；".join(str(f) for f in key_facts[:5]))
        canonical_summary = " | ".join(canonical_parts)

        rich_metadata = {
            "topics": analyzed.get("topics", [text[:50]]),
            "key_facts": key_facts,
            "sentiment": analyzed.get("sentiment", "neutral"),
            "interaction_type": "private_chat",
            "canonical_summary": canonical_summary,
            "persona_summary": text,
            "summary_schema_version": "v2",
            "summary_quality": "normal",
        }

        # --- 确保底层数据库连接可用 ---
        db_ok = await self._ensure_db_connection(memory_engine)
        if not db_ok:
            return {
                "success": False,
                "message": (
                    "FAISS DocumentStorage 数据库连接无法初始化。"
                    "请尝试重启 AstrBot 或检查 LivingMemory 的日志"
                ),
            }

        # --- 调用 MemoryEngine.add_memory() ---
        try:
            doc_id = await memory_engine.add_memory(
                content=text,
                session_id=session_id,
                persona_id=persona_id,
                importance=importance,
                metadata=rich_metadata,
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

        使用示例:
        /lmadd <Felis Abyssalis 喜欢在深夜调试代码>
        /lmadd <Felis Abyssalis 喜欢在深夜调试代码> 0.95
        """
        # 从原始消息中提取 <> 之间的内容
        raw_text = event.message_str if hasattr(event, "message_str") else ""

        match = re.search(r"<(.+?)>", raw_text, re.DOTALL)

        if not match:
            yield event.plain_result(
                "用法: /lmadd <记忆文本> [重要性]\n"
                "请用 < > 包裹记忆内容\n"
                "示例: /lmadd <Felis Abyssalis 喜欢在深夜调试代码>\n"
                "指定重要性: /lmadd <Felis Abyssalis 喜欢在深夜调试代码> 0.95"
            )
            return

        memory_text = match.group(1).strip()

        if not memory_text:
            yield event.plain_result(
                "用法: /lmadd <记忆文本> [重要性]\n"
                "示例: /lmadd <Felis Abyssalis 喜欢在深夜调试代码> 0.95"
            )
            return

        # 解析可选的重要性参数（在 > 之后）
        importance = None
        after_bracket = raw_text[match.end():].strip()
        if after_bracket:
            try:
                importance = float(after_bracket)
                importance = max(0.0, min(1.0, importance))
            except ValueError:
                pass  # 忽略无法解析的部分，使用默认值

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
            importance=importance,
        )

        if result["success"]:
            memory_id = result.get("memory_id", "N/A")
            used_importance = importance if importance is not None else self._default_importance
            yield event.plain_result(
                f"记忆插入成功\n"
                f"ID: {memory_id}\n"
                f"重要性: {used_importance}\n"
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
    # 命令: /lmput（手动指定全部 metadata，不调用 LLM）
    # -----------------------------------------------------------------------

    @filter.command("lmput")
    async def lmput_cmd(self, event: AstrMessageEvent, text: str):
        """直接向 LivingMemory 的记忆库中插入一条带完整 metadata 的记忆。

        不调用 LLM，所有字段由用户手动指定。

        使用示例:
        /lmput <{"text": "记忆内容", "topics": ["主题"], "key_facts": ["事实"], "sentiment": "positive"}>
        """
        raw_text = event.message_str if hasattr(event, "message_str") else ""

        match = re.search(r"<(.+?)>", raw_text, re.DOTALL)

        if not match:
            yield event.plain_result(
                "用法: /lmput <JSON>\n"
                "JSON 必须包含: text, topics, key_facts, sentiment\n"
                "可选字段: canonical_summary, persona_summary\n\n"
                "示例:\n"
                '/lmput <{"text": "Felis Abyssalis养了一只叫诺瓦（Noir）的赛博小猫", '
                '"topics": ["赛博小猫", "宠物"], '
                '"key_facts": ["Felis Abyssalis养了一只赛博小猫", "Felis Abyssalis的赛博小猫叫诺瓦（Noir）"], '
                '"sentiment": "neutral"}>'
            )
            return

        json_str = match.group(1).strip()

        # --- 解析 JSON ---
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            yield event.plain_result(f"JSON 解析失败: {e}")
            return

        # --- 校验必填字段 ---
        missing = []
        for field in ("text", "topics", "key_facts", "sentiment"):
            if field not in data:
                missing.append(field)
        if missing:
            yield event.plain_result(
                f"缺少必填字段: {', '.join(missing)}\n"
                "必须包含: text, topics, key_facts, sentiment"
            )
            return

        memory_text = data["text"]
        if not memory_text or not str(memory_text).strip():
            yield event.plain_result("text 不能为空")
            return

        memory_text = str(memory_text).strip()

        # 校验类型
        if not isinstance(data["topics"], list):
            yield event.plain_result("topics 必须是一个数组，例如: [\"主题1\", \"主题2\"]")
            return
        if not isinstance(data["key_facts"], list):
            yield event.plain_result("key_facts 必须是一个数组，例如: [\"事实1\", \"事实2\"]")
            return
        if data["sentiment"] not in ("positive", "negative", "neutral"):
            yield event.plain_result(
                "sentiment 必须是 positive / negative / neutral 之一"
            )
            return

        # --- 获取会话信息 ---
        session_id = event.unified_msg_origin
        if not session_id:
            yield event.plain_result("无法获取当前会话 ID，请稍后重试")
            return

        persona_id = await self._get_persona_id(event)

        yield event.plain_result("正在插入记忆...")

        # --- 构建 metadata ---
        # canonical_summary 对齐原版格式: text | fact1；fact2；...
        if "canonical_summary" not in data:
            canonical_parts = [memory_text]
            if data["key_facts"]:
                canonical_parts.append(
                    "；".join(str(f) for f in data["key_facts"][:5])
                )
            auto_canonical = " | ".join(canonical_parts)
        else:
            auto_canonical = data["canonical_summary"]

        rich_metadata = {
            "topics": data["topics"],
            "key_facts": data["key_facts"],
            "sentiment": data["sentiment"],
            "interaction_type": "private_chat",
            "canonical_summary": auto_canonical,
            "persona_summary": data.get("persona_summary", memory_text),
            "summary_schema_version": "v2",
            "summary_quality": "normal",
        }

        # --- 获取 MemoryEngine 并写入 ---
        memory_engine = self._discover_memory_engine()
        if memory_engine is None:
            yield event.plain_result(
                "无法获取 LivingMemory 的 MemoryEngine。"
                "请确保 LivingMemory 插件已安装、已启用，且初始化完成"
            )
            return

        importance = float(data.get("importance", self._default_importance))
        importance = max(0.0, min(1.0, importance))

        # --- 确保底层数据库连接可用 ---
        db_ok = await self._ensure_db_connection(memory_engine)
        if not db_ok:
            yield event.plain_result(
                "FAISS DocumentStorage 数据库连接无法初始化。"
                "请尝试重启 AstrBot 或检查 LivingMemory 的日志"
            )
            return

        try:
            doc_id = await memory_engine.add_memory(
                content=memory_text,
                session_id=session_id,
                persona_id=persona_id,
                importance=importance,
                metadata=rich_metadata,
            )

            topics_str = ", ".join(data["topics"])
            yield event.plain_result(
                f"记忆插入成功\n"
                f"ID: {doc_id}\n"
                f"重要性: {importance}\n"
                f"主题: {topics_str}\n"
                f"情感: {data['sentiment']}\n"
                f"内容: {memory_text[:100]}{'...' if len(memory_text) > 100 else ''}"
            )
        except Exception as e:
            logger.error(
                f"LivingMemoryManual /lmput 插入失败: {e}", exc_info=True
            )
            yield event.plain_result(f"记忆插入失败: {e}")

    # -----------------------------------------------------------------------
    # 生命周期
    # -----------------------------------------------------------------------

    async def terminate(self):
        """插件停止时清理资源。"""
        # 我们不持有任何独立资源，MemoryEngine 属于 LivingMemory
        self._memory_engine = None
        logger.info("LivingMemoryManual 插件已停止")
