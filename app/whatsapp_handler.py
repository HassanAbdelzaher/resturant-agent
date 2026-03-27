"""
WhatsApp Handler — GreenAPI integration.

How GreenAPI works:
  1. You create an instance at https://green-api.com
  2. Set the Webhook URL in the instance settings to point here
  3. GreenAPI POSTs JSON notifications to POST /webhook/greenapi
  4. We parse the notification, run the agent, and reply via GreenAPI REST API

Notification types handled:
  - incomingMessageReceived  → text / document / image messages
  - outgoingMessageStatus    → silently ignored (delivery receipts)

GreenAPI REST API:
  POST {API_URL}/waInstance{idInstance}/sendMessage/{apiToken}
  Body: {"chatId": "79001234567@c.us", "message": "..."}
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import FastAPI, Request, Response

from app.config import settings
from app.cart import cart_manager

if TYPE_CHECKING:
    from app.agent import WhatsAppAgent

logger = logging.getLogger(__name__)

# WhatsApp message character limit
_WA_MAX_CHARS = 4096

# ── Texts ─────────────────────────────────────────────────────────
def _build_welcome(name: str = "") -> str:
    """Build a personalised first-contact welcome message."""
    greeting = f"أهلاً *{name}*" if name else "أهلاً وسهلاً"
    return (
        f"🎉 {greeting}! مرحباً بك في *مطعم أبو طبق* 🍽️\n"
        "_عندنا الأكل حلو والنكتة أحلى!_\n\n"
        "أنا *أبو طبق*، مساعدك الذكي — اسألني عن أي شيء:\n"
        "• قائمة الطعام والأسعار\n"
        "• توصيات الشيف\n"
        "• عروض اليوم\n"
        "• تفاصيل أي طبق (مكونات، سعرات، حساسية...)\n\n"
        "🛒 *لطلب الطعام:*\n"
        "اكتب */طلب [اسم الطبق]* — مثلاً: /طلب كبسة\n\n"
        "اكتب */help* لرؤية كل الأوامر المتاحة 😄"
    )


HELP_TEXT = """🍽️ *أهلاً في مطعم أبو طبق!*
_عندنا الأكل حلو والنكتة أحلى!_

*اسألني مباشرة عن أي شيء، مثلاً:*
• اعطني قائمة الطعام
• كم سعر الكبسة؟
• وش تنصحني أطلب؟
• أبي شيء حار
• عندكم عروض اليوم؟
• أبي شيء نباتي
• وصف طبق المندي

*📋 أوامر الاستعلام:*
/قائمة — عرض قائمة الطعام كاملة
/عروض — عروض وخصومات اليوم
/توصية — اختيار الشيف اليوم
/مطعم — معلومات المطعم والتوصيل

*🛒 أوامر الطلب:*
/طلب [اسم الطبق] — إضافة طبق للسلة
/سلة — عرض سلتك الحالية
/تأكيد — تأكيد وإرسال الطلب
/إلغاء — إلغاء وتفريغ السلة
/طلباتي — عرض طلباتك السابقة

/help — عرض هذه الرسالة

_ملاحظة: لا تتردد في السؤال — الجوع لا ينتظر!_ 😄"""


# ── Message Deduplication ─────────────────────────────────────────
class MessageDeduplicator:
    """
    Prevents processing the same GreenAPI message twice.
    GreenAPI retries webhooks if it doesn't receive 200 quickly.
    We keep a rolling window of recently seen message IDs.
    """

    def __init__(self, max_size: int = 500):
        self._seen: set[str] = set()
        self._order: deque[str] = deque(maxlen=max_size)
        self._max_size = max_size

    def is_duplicate(self, message_id: str) -> bool:
        if message_id in self._seen:
            return True
        self._seen.add(message_id)
        if len(self._order) == self._max_size:
            oldest = self._order[0]
            self._seen.discard(oldest)
        self._order.append(message_id)
        return False


# ── Per-User Rate Limiter ─────────────────────────────────────────
class RateLimiter:
    """
    Sliding-window rate limiter: tracks message timestamps per user
    and rejects if they exceed rate_limit_per_minute.
    """

    def __init__(self, max_per_minute: int):
        self._max = max_per_minute
        self._windows: dict[str, deque[float]] = defaultdict(lambda: deque())

    def is_allowed(self, user_id: str) -> bool:
        if self._max == 0:
            return True
        now = time.monotonic()
        window = self._windows[user_id]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._max:
            return False
        window.append(now)
        return True


# Module-level singletons
_deduplicator = MessageDeduplicator()
_rate_limiter = RateLimiter(settings.rate_limit_per_minute)


# ── GreenAPI Async Client ─────────────────────────────────────────
class GreenAPIClient:
    """
    Thin async wrapper around the GreenAPI REST API.

    All methods take a chatId in GreenAPI format: "79001234567@c.us"
    """

    def __init__(self):
        self._base = (
            f"{settings.greenapi_api_url}"
            f"/waInstance{settings.greenapi_id_instance}"
        )
        self._token = settings.greenapi_api_token

    def _url(self, method: str) -> str:
        return f"{self._base}/{method}/{self._token}"

    async def send_text(self, chat_id: str, text: str) -> None:
        """Send a plain text message, splitting if over WhatsApp's limit."""
        chunks = _split_message(text)
        async with httpx.AsyncClient(timeout=30) as client:
            for chunk in chunks:
                resp = await client.post(
                    self._url("sendMessage"),
                    json={"chatId": chat_id, "message": chunk},
                )
                resp.raise_for_status()

    async def read_message(self, chat_id: str, id_message: str) -> None:
        """Mark a message as read (shows blue ticks to sender)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    self._url("readChat"),
                    json={"chatId": chat_id, "idMessage": id_message},
                )
        except Exception as exc:
            logger.debug(f"readChat failed (non-critical): {exc}")

    async def show_typing(self, chat_id: str) -> None:
        """Send a typing indicator to the chat."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    self._url("showTyping"),
                    json={"chatId": chat_id},
                )
        except Exception as exc:
            logger.debug(f"showTyping failed (non-critical): {exc}")

    async def download_file(self, download_url: str) -> bytes:
        """Download a media file from GreenAPI CDN."""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(download_url)
            resp.raise_for_status()
            return resp.content


# Module-level client (instantiated once)
_client: GreenAPIClient | None = None


def get_client() -> GreenAPIClient:
    global _client
    if _client is None:
        _client = GreenAPIClient()
    return _client


# ── Message splitting ──────────────────────────────────────────────
def _split_message(text: str, limit: int = _WA_MAX_CHARS) -> list[str]:
    """
    Split a long message into chunks at the nearest newline before `limit`.
    Avoids cutting mid-word.
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks


# ── Webhook payload helpers ───────────────────────────────────────
def extract_message(payload: dict) -> tuple[str, str, str, dict, str]:
    """
    Parse a GreenAPI webhook payload.

    Returns:
        chat_id     — "79001234567@c.us"
        sender_id   — plain phone number used as user_id
        msg_type    — "textMessage" | "documentMessage" | "imageMessage" | …
        msg_data    — the messageData sub-dict
        sender_name — display name of the sender (may be empty)
    """
    sender_data = payload.get("senderData", {})
    chat_id = sender_data.get("chatId", "")
    sender_id = chat_id.replace("@c.us", "").replace("@g.us", "")
    sender_name = sender_data.get("senderName", "") or sender_data.get("pushname", "")
    msg_data = payload.get("messageData", {})
    msg_type = msg_data.get("typeMessage", "unknown")
    return chat_id, sender_id, msg_type, msg_data, sender_name


def _is_group_chat(chat_id: str) -> bool:
    """Group chats use @g.us suffix; individual chats use @c.us."""
    return chat_id.endswith("@g.us")


def _is_admin(sender_id: str) -> bool:
    """Check if sender is in the admin whitelist."""
    admin_ids = settings.admin_ids_set
    # If no admins configured, allow all (backwards-compatible default)
    if not admin_ids:
        return True
    return sender_id in admin_ids


# ── Route registration ────────────────────────────────────────────
def register_handlers(app: FastAPI, agent: "WhatsAppAgent") -> None:
    """Register the GreenAPI webhook POST endpoint on the FastAPI app."""

    @app.post("/webhook/greenapi")
    async def greenapi_webhook(request: Request) -> Response:
        """
        Receives all GreenAPI instance notifications.
        Returns HTTP 200 immediately and processes the message in the background.
        GreenAPI retries if it doesn't get 200 within ~10 s, so we must respond fast.
        """
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            return Response(status_code=400)

        webhook_type = payload.get("typeWebhook", "")
        logger.debug(f"GreenAPI webhook: {webhook_type}")

        if webhook_type == "incomingMessageReceived":
            # Deduplicate before scheduling background work
            message_id = payload.get("idMessage", "")
            if message_id and _deduplicator.is_duplicate(message_id):
                logger.debug(f"Duplicate message {message_id} — skipping")
                return Response(status_code=200)
            # Fire-and-forget: process in background, return 200 immediately
            asyncio.create_task(_handle_incoming(payload, agent))

        # Always acknowledge — GreenAPI expects 200 for every notification
        return Response(status_code=200)


# ── Incoming message dispatcher ───────────────────────────────────
async def _handle_incoming(payload: dict, agent: "WhatsAppAgent") -> None:
    """Dispatch an incomingMessageReceived notification."""
    chat_id, sender_id, msg_type, msg_data, sender_name = extract_message(payload)
    id_message = payload.get("idMessage", "")
    client = get_client()

    if not chat_id:
        logger.warning("Received notification with no chatId — skipping")
        return

    # Ignore group chats
    if _is_group_chat(chat_id):
        logger.debug(f"Ignoring group chat message from {chat_id}")
        return

    logger.info(f"Incoming [{msg_type}] from {sender_id} ({sender_name})")

    try:
        if msg_type == "textMessage":
            text = msg_data.get("textMessageData", {}).get("textMessage", "").strip()
            await client.read_message(chat_id, id_message)
            await _dispatch_text(chat_id, sender_id, sender_name, text, agent)

        elif msg_type in ("documentMessage", "imageMessage", "videoMessage"):
            file_data = msg_data.get("fileMessageData", {})
            mime = file_data.get("mimeType", "")
            if mime == "application/pdf":
                await client.read_message(chat_id, id_message)
                await _handle_pdf(chat_id, sender_id, file_data, agent)
            else:
                await client.send_text(
                    chat_id,
                    "😄 شكراً للملف! حالياً أفهم بس النصوص وملفات PDF.\n"
                    "اسألني عن أي طبق أو اكتب /help 🍽️",
                )

        elif msg_type == "extendedTextMessage":
            # Links / formatted messages — treat the body as plain text
            text = (
                msg_data.get("extendedTextMessageData", {})
                .get("text", "")
                .strip()
            )
            await client.read_message(chat_id, id_message)
            await _dispatch_text(chat_id, sender_id, sender_name, text, agent)

        else:
            await client.send_text(
                chat_id,
                "😄 ما فهمت هذا النوع من الرسائل!\n"
                "اسألني بالنص أو أرسل PDF 🍽️",
            )

    except Exception as exc:
        logger.error(f"Error handling message from {sender_id}: {exc}", exc_info=True)
        try:
            await client.send_text(
                chat_id,
                "😅 صار خطأ تقني عندنا!\n"
                "الشيف مشغول يصلحه — جرب مرة ثانية بعد ثواني 🔧",
            )
        except Exception:
            pass


# ── Text message routing ──────────────────────────────────────────
async def _dispatch_text(
    chat_id: str, sender_id: str, sender_name: str, text: str, agent: "WhatsAppAgent"
) -> None:
    """Route a text message to command handler or agent pipeline."""
    client = get_client()

    if not text:
        await client.send_text(
            chat_id,
            "😄 ما فهمت سؤالك، بس معدتي فاهمة!\n\n"
            "اسألني عن أي طبق أو اكتب /قائمة لتشوف كل شيء 🍽️",
        )
        return

    # Rate limit check
    if not _rate_limiter.is_allowed(sender_id):
        await client.send_text(
            chat_id,
            "⏳ أنت تراسلنا كثيراً! انتظر لحظة ثم حاول مرة أخرى 😅",
        )
        return

    # Welcome new users on their very first message
    _, is_new = await agent.db.get_or_create_user(sender_id, name=sender_name)
    if is_new:
        await client.send_text(chat_id, _build_welcome(sender_name))

    if text.startswith("/"):
        await _handle_command(chat_id, sender_id, sender_name, text.lower(), agent)
    else:
        await client.show_typing(chat_id)
        reply = await agent.answer(text, user_id=sender_id, user_name=sender_name)
        await client.send_text(chat_id, reply)


# ── Command handling ──────────────────────────────────────────────
async def _handle_command(
    chat_id: str, sender_id: str, sender_name: str, command: str, agent: "WhatsAppAgent"
) -> None:
    """Handle slash commands."""
    client = get_client()

    # ── Restaurant commands (available to all) ────────────────────
    if command in ("/قائمة", "/menu", "/قائمه"):
        await client.show_typing(chat_id)
        reply = await agent.answer(
            "اعطني القائمة الكاملة للمطعم", user_id=sender_id, user_name=sender_name
        )
        await client.send_text(chat_id, reply)

    elif command in ("/عروض", "/offers", "/خصومات"):
        await client.show_typing(chat_id)
        reply = await agent.answer(
            "ما هي عروض وخصومات اليوم؟", user_id=sender_id, user_name=sender_name
        )
        await client.send_text(chat_id, reply)

    elif command in ("/توصية", "/recommend", "/توصيه"):
        await client.show_typing(chat_id)
        reply = await agent.answer(
            "ما هي توصيات الشيف اليوم؟", user_id=sender_id, user_name=sender_name
        )
        await client.send_text(chat_id, reply)

    elif command in ("/مطعم", "/info", "/معلومات"):
        await client.show_typing(chat_id)
        reply = await agent.answer(
            "أخبرني عن معلومات المطعم وأوقات العمل", user_id=sender_id, user_name=sender_name
        )
        await client.send_text(chat_id, reply)

    elif command == "/help":
        await client.send_text(chat_id, HELP_TEXT)

    # ── System commands (admin only) ──────────────────────────────
    elif command == "/status":
        if not _is_admin(sender_id):
            await client.send_text(chat_id, "🚫 هذا الأمر للمشرفين فقط.")
            return
        status_text = await agent.get_status()
        await client.send_text(chat_id, status_text)

    elif command == "/ingest":
        if not _is_admin(sender_id):
            await client.send_text(chat_id, "🚫 هذا الأمر للمشرفين فقط.")
            return
        await client.send_text(chat_id, "🔄 جارٍ إعادة فهرسة الملفات...")
        count = agent.rag_pipeline.ingest()
        if count > 0:
            agent.rag_pipeline.build_qa_chain(agent.llm)
            await client.send_text(chat_id, f"✅ تم فهرسة {count} قسم من الملفات.")
        else:
            await client.send_text(chat_id, "⚠️ لا توجد ملفات PDF في المجلد.")

    elif command == "/sources":
        if not _is_admin(sender_id):
            await client.send_text(chat_id, "🚫 هذا الأمر للمشرفين فقط.")
            return
        sources = agent.get_pdf_sources()
        if sources:
            source_list = "\n".join(f"📄 {s}" for s in sources)
            await client.send_text(chat_id, f"*الملفات المتاحة:*\n\n{source_list}")
        else:
            await client.send_text(chat_id, "لا توجد ملفات مفهرسة بعد.")

    # ── Order commands (available to all) ────────────────────────
    elif command == "/سلة" or command == "/cart":
        await client.send_text(chat_id, cart_manager.format_cart(sender_id))

    elif command.startswith("/طلب") or command.startswith("/order"):
        # /طلب <dish name>
        parts = command.split(maxsplit=1)
        dish_query = parts[1].strip() if len(parts) > 1 else ""
        if not dish_query:
            await client.send_text(
                chat_id,
                "✍️ اكتب اسم الطبق بعد الأمر، مثلاً:\n/طلب كبسة\n/طلب كنافة",
            )
            return
        dish = cart_manager.find_dish(dish_query)
        if not dish:
            await client.send_text(
                chat_id,
                f"❓ ما لقيت طبق باسم *{dish_query}*\n\n"
                "جرب /قائمة لتشوف الأصناف المتاحة.",
            )
            return
        currency = cart_manager.get_currency()
        cart_manager.add_item(
            sender_id, dish["id"], dish["name"], float(dish["price"])
        )
        total = cart_manager.get_total(sender_id)
        await client.send_text(
            chat_id,
            f"✅ تمت الإضافة!\n"
            f"{dish.get('emoji','🍽️')} *{dish['name']}* — {dish['price']} {currency}\n\n"
            f"💰 إجمالي سلتك: *{total:.0f} {currency}*\n\n"
            "اكتب /سلة لعرض سلتك أو /تأكيد لإتمام الطلب.",
        )

    elif command in ("/تأكيد", "/confirm", "/checkout"):
        await _confirm_order(chat_id, sender_id, sender_name, agent)

    elif command in ("/إلغاء", "/cancel", "/الغاء"):
        if cart_manager.is_empty(sender_id):
            await client.send_text(chat_id, "🛒 سلتك فارغة أصلاً! لا يوجد شيء للإلغاء.")
        else:
            cart_manager.clear(sender_id)
            await client.send_text(
                chat_id,
                "❌ تم إلغاء طلبك وتفريغ السلة.\n\n"
                "عندما تكون جاهزاً، استخدم /قائمة لتبدأ من جديد 🍽️",
            )

    elif command in ("/طلباتي", "/orders", "/myorders"):
        orders = await agent.db.get_user_orders(sender_id, limit=5)
        if not orders:
            await client.send_text(chat_id, "📋 ليس لديك طلبات سابقة بعد.\n\nابدأ بـ /قائمة!")
        else:
            currency = cart_manager.get_currency()
            lines = ["📋 *آخر طلباتك:*", ""]
            for order in orders:
                status_icon = "✅" if order.status == "confirmed" else "❌"
                lines.append(
                    f"{status_icon} طلب #{order.id} — "
                    f"*{order.total:.0f} {currency}* — "
                    f"{order.created_at.strftime('%Y/%m/%d %H:%M')}"
                )
            await client.send_text(chat_id, "\n".join(lines))

    else:
        await client.send_text(
            chat_id,
            f"❓ أمر غير معروف: {command}\n\n"
            "اكتب /help لرؤية الأوامر المتاحة 😄",
        )


# ── Order confirmation ────────────────────────────────────────────
async def _confirm_order(
    chat_id: str, sender_id: str, sender_name: str, agent: "WhatsAppAgent"
) -> None:
    """Validate, save, and notify staff about a confirmed order."""
    client = get_client()

    if cart_manager.is_empty(sender_id):
        await client.send_text(
            chat_id,
            "🛒 سلتك فارغة! أضف أطباقاً أولاً بـ /طلب <اسم الطبق>",
        )
        return

    total = cart_manager.get_total(sender_id)
    min_order = cart_manager.get_min_order()
    currency = cart_manager.get_currency()

    if total < min_order:
        remaining = min_order - total
        await client.send_text(
            chat_id,
            f"⚠️ الحد الأدنى للطلب {min_order:.0f} {currency}.\n"
            f"سلتك الحالية {total:.0f} {currency} — أضف {remaining:.0f} {currency} أكثر.",
        )
        return

    # Save order to DB
    items = cart_manager.get_items(sender_id)
    order = await agent.db.place_order(
        wa_id=sender_id,
        items=items,
        total=total,
        user_name=sender_name or None,
    )

    # Notify user
    await client.send_text(
        chat_id,
        f"🎉 *تم تأكيد طلبك!*\n\n"
        f"رقم طلبك: *#{order.id}*\n"
        f"💰 الإجمالي: *{total:.0f} {currency}*\n"
        f"🚚 وقت التوصيل المتوقع: 30-45 دقيقة\n\n"
        "شكراً لك! سيتم تحضير طلبك الآن. 😄🍽️",
    )

    # Notify staff (if configured)
    staff_id = settings.staff_wa_id.strip()
    if staff_id:
        staff_chat_id = f"{staff_id}@c.us"
        staff_msg = cart_manager.format_order_for_staff(sender_id, order.id, sender_name)
        try:
            await client.send_text(staff_chat_id, staff_msg)
        except Exception as exc:
            logger.error(f"Failed to notify staff ({staff_id}): {exc}")

    # Clear cart after successful order
    cart_manager.clear(sender_id)


# ── PDF upload handling ───────────────────────────────────────────
async def _handle_pdf(
    chat_id: str, sender_id: str, file_data: dict, agent: "WhatsAppAgent"
) -> None:
    """Download a PDF from GreenAPI CDN and ingest it into the RAG pipeline."""
    client = get_client()
    await client.send_text(chat_id, "📥 استلمنا ملفك! جارٍ المعالجة...")

    download_url = file_data.get("downloadUrl", "")
    file_name = file_data.get("fileName", "upload.pdf")

    if not download_url:
        await client.send_text(chat_id, "❌ تعذّر تحميل الملف — لم يصل الرابط.")
        return

    try:
        pdf_bytes = await client.download_file(download_url)

        # Enforce file size limit
        max_size = settings.pdf_max_size_bytes
        if len(pdf_bytes) > max_size:
            max_mb = max_size // (1024 * 1024)
            await client.send_text(
                chat_id,
                f"❌ الملف كبير جداً! الحد الأقصى {max_mb} ميغابايت.",
            )
            return

        # Save to pdfs/ directory
        pdf_dir = Path(agent.rag_pipeline.pdf_dir)
        pdf_dir.mkdir(parents=True, exist_ok=True)
        dest = pdf_dir / file_name

        # Avoid overwriting — add a numeric suffix if needed
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            for i in range(1, 1000):
                dest = pdf_dir / f"{stem}_{i}{suffix}"
                if not dest.exists():
                    break

        dest.write_bytes(pdf_bytes)
        logger.info(f"Saved PDF to {dest}")

        count = agent.rag_pipeline.add_pdf(str(dest))
        agent.rag_pipeline.build_qa_chain(agent.llm)

        await client.send_text(
            chat_id,
            f"✅ تم معالجة الملف! أضفنا {count} قسم للقاعدة المعرفية.\n"
            "يمكنك الآن السؤال عن محتواه 📚",
        )

    except Exception as exc:
        logger.error(f"PDF ingestion failed: {exc}", exc_info=True)
        await client.send_text(
            chat_id, "❌ حصل خطأ في معالجة الملف. حاول مرة ثانية 🙏"
        )
