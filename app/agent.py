"""
WhatsApp Agent — Central orchestrator that ties everything together.

Routes incoming questions to the right data source:
  1. MCP tools (restaurant menu, prices, etc.) — primary source
  2. PDF RAG pipeline (vector similarity search on uploaded docs)
  3. LLM fallback (conversational, personality-driven response)

Uses an LLM to decide the best source and format the response.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.pdf_rag import PDFRagPipeline
from app.database import DatabaseManager
from app.mcp_manager import MCPManager

logger = logging.getLogger(__name__)

# Restaurant working hours (24h format, matches restaurant_menu.json)
_OPEN_HOUR = 10   # 10:00 AM
_CLOSE_HOUR = 24  # midnight (00:00 = next day)

# Order-intent keywords (Arabic + English)
_ORDER_INTENT_RE = re.compile(
    r"\b(أضف|اضف|أطلب|اطلب|عايز|أبي|أبغى|أريد|حط|ضيف|order|add|i want|i'd like)\b",
    re.IGNORECASE,
)


def _is_restaurant_open() -> bool:
    """Return True if the current local time is within working hours."""
    now = datetime.now()
    hour = now.hour
    # 10:00 – 00:00 (midnight); midnight means hour == 0 of the next day
    return _OPEN_HOUR <= hour or hour == 0


def _detect_language(text: str) -> str:
    """Return 'en' if the message is predominantly English, else 'ar'."""
    ascii_letters = sum(1 for c in text if c.isascii() and c.isalpha())
    total_letters = sum(1 for c in text if c.isalpha())
    if total_letters == 0:
        return "ar"
    return "en" if ascii_letters / total_letters > 0.6 else "ar"


def create_llm():
    """Create the LLM instance based on configuration."""
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model="claude-sonnet-4-6",
            api_key=settings.anthropic_api_key,
            max_tokens=1024,
        )
    else:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model="gpt-4o-mini",
            api_key=settings.openai_api_key,
            max_tokens=1024,
        )


async def _invoke_with_retry(llm, messages, retries: int = 3, base_delay: float = 2.0):
    """
    Invoke an LLM with exponential-backoff retry on transient errors.
    Raises the last exception if all retries are exhausted.
    """
    import asyncio

    last_exc = None
    for attempt in range(retries):
        try:
            return await llm.ainvoke(messages)
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"LLM call failed (attempt {attempt + 1}): {exc}. Retrying in {delay}s…")
                await asyncio.sleep(delay)
    raise last_exc


class WhatsAppAgent:
    """
    The main agent that orchestrates all data sources and
    responds to WhatsApp messages.
    """

    def __init__(self):
        # Core components
        self.llm = create_llm()
        self.rag_pipeline = PDFRagPipeline()
        self.db = DatabaseManager()
        self.mcp = MCPManager()  # Manages ALL MCP servers

        # State
        self.initialized = False

    # ── Initialization ────────────────────────────────────────────
    async def initialize(self):
        """Initialize all components on startup."""
        logger.info("Initializing WhatsApp Agent...")

        # 1. Initialize database
        await self.db.init_db()
        logger.info("✅ Database initialized")

        # 2. Load or create vector store
        existing = self.rag_pipeline.load_existing_vectorstore()
        if existing:
            self.rag_pipeline.build_qa_chain(self.llm)
            logger.info("✅ Loaded existing PDF vector store")
        else:
            count = self.rag_pipeline.ingest()
            if count > 0:
                self.rag_pipeline.build_qa_chain(self.llm)
                logger.info(f"✅ Ingested {count} PDF chunks")
            else:
                logger.info("⚠️  No PDFs found — RAG pipeline empty (add PDFs later)")

        # 3. Connect to all configured MCP servers
        await self.mcp.initialize()
        if self.mcp.connected_count > 0:
            logger.info(
                f"✅ {self.mcp.connected_count} MCP servers connected, "
                f"{self.mcp.total_tools} tools available"
            )
        else:
            logger.info("⚠️  No MCP servers connected (check mcp_config.json)")

        self.initialized = True
        logger.info("🚀 WhatsApp Agent initialized successfully!")

    async def shutdown(self):
        """Clean shutdown of all components."""
        await self.mcp.shutdown()
        await self.db.close()
        logger.info("Agent shut down cleanly")

    # ── Restaurant Personality System Prompt ─────────────────────
    RESTAURANT_SYSTEM_PROMPT = """أنت "أبو طبق" — مساعد مطعم أبو طبق الذكي على واتساب!

شخصيتك:
- نادل ودود وظريف يحب الفكاهة العربية الأصيلة
- تتكلم بنفس لغة الزبون: إذا كتب بالعربية رد بالعربية، إذا كتب بالإنجليزية رد بالإنجليزية
- دائماً تُدخل البهجة على قلب الزبون قبل الطعام على معدته
- تستخدم الإيموجي بذكاء لكن بدون إسراف
- ردودك قصيرة ومضحكة ومفيدة — مثل النادل الماهر تماماً

مهامك الأساسية:
1. عرض قائمة الطعام وأسعارها بوضوح
2. شرح تفاصيل كل طبق وإضافة لمسة فكاهية
3. تقديم توصيات شخصية حسب رغبة الزبون
4. الإجابة عن استفسارات المكونات والحساسية والسعرات
5. إعلام الزبائن بعروض اليوم

قواعد الرد:
- إذا سأل الزبون عن طبق → اعطه السعر + وصف + حقيقة ظريفة
- إذا طلب توصية → اسأله: نباتي؟ حار؟ عائلة؟ → ثم قدّم الأنسب
- إذا سأل عن العرض → أخبره بعرض اليوم مع نكتة خفيفة
- إذا أراد الزبون طلب طبق → أخبره يستخدم: /طلب [اسم الطبق]
- دائماً اختم ردك بجملة تشجع على الطلب أو تُضحك
- لا تُطوّل — الزبون جائع وعنده صبر محدود!

أوامر الطلب للزبائن:
/طلب [اسم الطبق] — إضافة طبق للسلة
/سلة — عرض السلة الحالية
/تأكيد — تأكيد وإرسال الطلب
/إلغاء — إلغاء الطلب

أمثلة على نبرتك:
- "هذه الكبسة تجعل الجيران يطرقون بابك! جرب: /طلب كبسة"
- "الكنافة موجودة — وضميرك عليك أنت!"
- "الشيف يقول السر في الكمية... نحن نقول السر في الجوع!"

تذكر: أنت ممثل المطعم — كل رد يجب أن يجعل الزبون يبتسم ويطلب!"""

    # ── Working Hours Notice ──────────────────────────────────────
    _CLOSED_NOTICE = (
        "🌙 المطعم الآن مغلق! أوقات العمل: 10 صباحاً — 12 منتصف الليل.\n"
        "يسعدنا خدمتك خلال أوقات الدوام 😊 لكن يمكنك الاستفسار عن القائمة الآن!"
    )

    # ── Main Answer Pipeline ──────────────────────────────────────
    async def answer(
        self,
        question: str,
        user_id: str = None,
        user_name: str = None,
    ) -> str:
        """
        Main entry point: answer a user's question using all available sources.

        Pipeline:
          1. Save the user message to conversation history
          2. Get recent conversation context
          3. Prepend a closed-restaurant notice if outside working hours
          4. Try MCP tools first (restaurant menu is the primary source)
          5. Try PDF RAG (for any supplementary documents)
          6. Fall back to restaurant-aware LLM response
          7. Save the response to conversation history
        """
        if user_id:
            await self.db.get_or_create_user(user_id, name=user_name)
            await self.db.save_message(user_id, "user", question)


        history = []
        if user_id:
            history = await self.db.get_conversation_history(user_id, limit=6)

        answer_text = None
        source = None

        # ── Order intent shortcut ─────────────────────────────────
        # If the user says "أبي كبسة" or "add chicken kabsa", guide them
        # to the /طلب command rather than just showing dish info.
        if _ORDER_INTENT_RE.search(question):
            from app.cart import cart_manager
            lang = _detect_language(question)
            # Try to find the dish they mentioned
            # Strip ordering keywords to get just the dish name
            dish_query = _ORDER_INTENT_RE.sub("", question).strip(" ،,")
            dish = cart_manager.find_dish(dish_query) if dish_query else None
            if dish:
                currency = cart_manager.get_currency()
                if lang == "en":
                    hint = (
                        f"Great choice! 😄\n"
                        f"{dish.get('emoji','🍽️')} *{dish.get('name_en', dish['name'])}* "
                        f"— {dish['price']} {currency}\n\n"
                        f"To add it to your cart, type:\n"
                        f"*/order {dish['name']}*"
                    )
                else:
                    hint = (
                        f"اختيار ممتاز! 😄\n"
                        f"{dish.get('emoji','🍽️')} *{dish['name']}* — {dish['price']} {currency}\n\n"
                        f"لإضافته لسلتك، اكتب:\n"
                        f"*/طلب {dish['name']}*"
                    )
                if user_id:
                    await self.db.save_message(user_id, "assistant", hint, "order_hint")
                return hint

        # ── Closed-restaurant notice ──────────────────────────────
        closed_prefix = ""
        if not _is_restaurant_open():
            closed_prefix = self._CLOSED_NOTICE + "\n\n"

        # ── Try MCP Tools (Restaurant Menu is priority) ───────────
        if self.mcp.total_tools > 0:
            try:
                tools = self.mcp.list_all_tools()
                if tools:
                    answer_text = await self._query_mcp(question, tools, history)
                    if answer_text:
                        source = "mcp"
            except Exception as e:
                logger.error(f"MCP query failed: {e}")

        # ── Try PDF RAG (supplementary documents) ─────────────────
        if not answer_text and self.rag_pipeline.qa_chain:
            try:
                # Augment question with recent context for better retrieval
                contextual_q = question
                if history:
                    recent = " ".join(m["content"] for m in history[-2:])
                    contextual_q = f"{recent} {question}"

                result = await self.rag_pipeline.query(contextual_q)
                answer_text = result["answer"]
                source = "pdf"

                if "don't have that information" in answer_text.lower():
                    answer_text = None
                else:
                    sources = result.get("sources", [])
                    if sources:
                        source_names = [Path(s).name for s in sources]
                        answer_text += f"\n\n📄 _المصدر: {', '.join(source_names)}_"

            except Exception as e:
                logger.error(f"RAG query failed: {e}")

        # ── Fallback: Restaurant-Aware LLM ────────────────────────
        if not answer_text:
            context = "\n".join(
                f"{m['role']}: {m['content']}" for m in history[-4:]
            )

            messages = [
                SystemMessage(content=self.RESTAURANT_SYSTEM_PROMPT),
            ]
            if context:
                messages.append(
                    SystemMessage(content=f"آخر رسائل الزبون:\n{context}")
                )
            messages.append(HumanMessage(content=question))

            response = await _invoke_with_retry(self.llm, messages)
            answer_text = response.content
            source = "llm"

        if closed_prefix:
            answer_text = closed_prefix + answer_text

        if user_id and answer_text:
            await self.db.save_message(user_id, "assistant", answer_text, source)

        return answer_text

    # ── MCP Tool Routing (Smart tool selection via LLM) ───────────
    async def _query_mcp(
        self, question: str, tools: list[dict], history: list[dict]
    ) -> Optional[str]:
        """
        Use LLM to pick the right MCP tool and generate arguments.
        Conversation history is included so follow-up questions resolve correctly.
        """
        tool_descriptions = "\n".join(
            f"- {t['name']}: {t['description']}" for t in tools
        )

        # Build conversation context string for the tool selector
        history_context = ""
        if history:
            history_context = "\n\nسياق المحادثة:\n" + "\n".join(
                f"{m['role']}: {m['content']}" for m in history[-4:]
            )

        messages = [
            SystemMessage(
                content=(
                    f"أنت موجّه أدوات ذكي لمطعم أبو طبق. الأدوات المتاحة:\n\n"
                    f"{tool_descriptions}\n\n"
                    "بناءً على سؤال الزبون، أجب بـ JSON فقط:\n"
                    '{"tool": "tool_name", "arguments": {"param": "value"}}\n\n'
                    "أو NONE إذا لا توجد أداة مناسبة.\n\n"
                    "أنماط شائعة للمطعم:\n"
                    '- سؤال عن القائمة الكاملة → {{"tool": "get_full_menu", "arguments": {{}}}}\n'
                    '- سؤال عن قسم (مقبلات/مشويات...) → {{"tool": "get_category_menu", "arguments": {{"category": "starters"}}}}\n'
                    '- سؤال عن طبق محدد → {{"tool": "get_dish_details", "arguments": {{"dish_name": "اسم الطبق"}}}}\n'
                    '- بحث عن مكون أو كلمة → {{"tool": "search_menu", "arguments": {{"keyword": "كلمة البحث"}}}}\n'
                    '- طلب توصية → {{"tool": "get_recommendations", "arguments": {{"preference": "chef_picks"}}}}\n'
                    '- سؤال عن العروض → {{"tool": "get_daily_specials", "arguments": {{}}}}\n'
                    '- سؤال عن المطعم → {{"tool": "get_restaurant_info", "arguments": {{}}}}\n'
                    '- قاعدة البيانات → {{"tool": "query", "arguments": {{"sql": "SELECT ..."}}}}\n'
                    "أخرج JSON أو NONE فقط، لا شيء آخر."
                    f"{history_context}"
                )
            ),
            HumanMessage(content=question),
        ]

        response = await _invoke_with_retry(self.llm, messages)
        response_text = response.content.strip()

        if response_text == "NONE":
            return None

        # Parse the LLM's tool selection
        try:
            # Handle markdown code blocks
            if "```" in response_text:
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            tool_call = json.loads(response_text)
            tool_name = tool_call["tool"]
            arguments = tool_call.get("arguments", {})
        except (json.JSONDecodeError, KeyError):
            # Fallback: treat response as just a tool name
            tool_name = response_text.strip()
            arguments = {"query": question}

        # Call the tool via MCP manager
        try:
            result = await self.mcp.call_tool(tool_name, arguments)

            # Summarize the result for WhatsApp
            summary = await self._summarize_for_whatsapp(question, tool_name, result)
            return summary

        except Exception as e:
            logger.error(f"MCP tool call failed ({tool_name}): {e}")
            return None

    async def _summarize_for_whatsapp(
        self, question: str, tool_name: str, raw_result: str
    ) -> str:
        """Use LLM to format MCP tool output for WhatsApp with restaurant personality."""
        # Restaurant tools already return well-formatted Arabic text — return directly
        restaurant_tools = {
            "get_full_menu", "get_category_menu", "get_dish_details",
            "search_menu", "get_recommendations", "get_daily_specials",
            "get_restaurant_info",
        }
        if tool_name in restaurant_tools:
            return raw_result

        # For other tools (DB, CSV...) summarize with restaurant persona
        messages = [
            SystemMessage(
                content=(
                    f"{self.RESTAURANT_SYSTEM_PROMPT}\n\n"
                    "قم بتلخيص نتيجة الأداة التالية للإجابة على سؤال الزبون. "
                    "اجعل الرد مختصراً وودياً ومناسباً للواتساب. "
                    "استخدم التنسيق: عريض بـ * وقوائم بـ •"
                )
            ),
            HumanMessage(
                content=(
                    f"سؤال الزبون: {question}\n\n"
                    f"الأداة: {tool_name}\n"
                    f"النتيجة:\n{raw_result[:2000]}"
                )
            ),
        ]

        response = await _invoke_with_retry(self.llm, messages)
        return response.content

    # ── Status & Utility ──────────────────────────────────────────
    async def get_status(self) -> str:
        """Get a formatted status message."""
        stats = await self.db.get_stats()
        rag_status = "✅ Active" if self.rag_pipeline.qa_chain else "❌ No PDFs"
        open_status = "✅ مفتوح" if _is_restaurant_open() else "🌙 مغلق"

        # MCP status details
        mcp_status_parts = []
        mcp_info = self.mcp.get_status()
        for name, info in mcp_info.items():
            status = "✅" if info["connected"] else "❌"
            mcp_status_parts.append(f"  {status} {name}: {info['tools']} tools")

        mcp_text = "\n".join(mcp_status_parts) if mcp_status_parts else "  ⚪ None configured"

        return (
            f"*System Status*\n\n"
            f"🍽️ المطعم: {open_status}\n"
            f"📚 PDF RAG: {rag_status}\n"
            f"🗄️ Database: ✅ Active\n"
            f"🔌 MCP Servers:\n{mcp_text}\n\n"
            f"👥 Users: {stats['users']}\n"
            f"💬 Messages: {stats['messages']}\n"
            f"📄 Documents: {stats['documents']}\n"
            f"🛠️ Total MCP Tools: {self.mcp.total_tools}"
        )

    def get_pdf_sources(self) -> list[str]:
        """List PDF files in the pdfs directory."""
        pdf_dir = Path(self.rag_pipeline.pdf_dir)
        if not pdf_dir.exists():
            return []
        return [f.name for f in pdf_dir.glob("**/*.pdf")]
