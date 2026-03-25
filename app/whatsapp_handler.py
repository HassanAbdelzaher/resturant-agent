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

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import FastAPI, Request, Response

from app.config import settings

if TYPE_CHECKING:
    from app.agent import WhatsAppAgent

logger = logging.getLogger(__name__)


# ── Texts ─────────────────────────────────────────────────────────
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

*الأوامر المتاحة:*
/قائمة — عرض قائمة الطعام كاملة
/عروض — عروض وخصومات اليوم
/توصية — اختيار الشيف اليوم
/مطعم — معلومات المطعم والتوصيل
/help — عرض هذه الرسالة

_ملاحظة: لا تتردد في السؤال — الجوع لا ينتظر!_ 😄"""


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

    async def send_text(self, chat_id: str, text: str) -> dict:
        """Send a plain text message."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._url("sendMessage"),
                json={"chatId": chat_id, "message": text},
            )
            resp.raise_for_status()
            return resp.json()

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


# ── Webhook payload helpers ───────────────────────────────────────
def extract_message(payload: dict) -> tuple[str, str, str, dict]:
    """
    Parse a GreenAPI webhook payload.

    Returns:
        chat_id    — "79001234567@c.us"
        sender_id  — plain phone number used as user_id
        msg_type   — "textMessage" | "documentMessage" | "imageMessage" | …
        msg_data   — the messageData sub-dict
    """
    sender_data = payload.get("senderData", {})
    chat_id = sender_data.get("chatId", "")
    sender_id = chat_id.replace("@c.us", "").replace("@g.us", "")
    msg_data = payload.get("messageData", {})
    msg_type = msg_data.get("typeMessage", "unknown")
    return chat_id, sender_id, msg_type, msg_data


# ── Route registration ────────────────────────────────────────────
def register_handlers(app: FastAPI, agent: "WhatsAppAgent") -> None:
    """Register the GreenAPI webhook POST endpoint on the FastAPI app."""

    @app.post("/webhook/greenapi")
    async def greenapi_webhook(request: Request) -> Response:
        """
        Receives all GreenAPI instance notifications.
        Must return HTTP 200 quickly; heavy work is awaited inline
        (GreenAPI retries if it doesn't get 200 within ~10 s).
        """
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            return Response(status_code=400)

        webhook_type = payload.get("typeWebhook", "")
        logger.debug(f"GreenAPI webhook: {webhook_type}")

        if webhook_type == "incomingMessageReceived":
            await _handle_incoming(payload, agent)

        # Always acknowledge — GreenAPI expects 200 for every notification
        return Response(status_code=200)


# ── Incoming message dispatcher ───────────────────────────────────
async def _handle_incoming(payload: dict, agent: "WhatsAppAgent") -> None:
    """Dispatch an incomingMessageReceived notification."""
    chat_id, sender_id, msg_type, msg_data = extract_message(payload)
    id_message = payload.get("idMessage", "")
    client = get_client()

    if not chat_id:
        logger.warning("Received notification with no chatId — skipping")
        return

    logger.info(f"Incoming [{msg_type}] from {sender_id}")

    try:
        if msg_type == "textMessage":
            text = msg_data.get("textMessageData", {}).get("textMessage", "").strip()
            await client.read_message(chat_id, id_message)
            await _dispatch_text(chat_id, sender_id, text, agent)

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
            await _dispatch_text(chat_id, sender_id, text, agent)

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
    chat_id: str, sender_id: str, text: str, agent: "WhatsAppAgent"
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

    if text.startswith("/"):
        await _handle_command(chat_id, sender_id, text.lower(), agent)
    else:
        reply = await agent.answer(text, user_id=sender_id)
        await client.send_text(chat_id, reply)


# ── Command handling ──────────────────────────────────────────────
async def _handle_command(
    chat_id: str, sender_id: str, command: str, agent: "WhatsAppAgent"
) -> None:
    """Handle slash commands."""
    client = get_client()

    # ── Restaurant commands ───────────────────────────────────────
    if command in ("/قائمة", "/menu", "/قائمه"):
        reply = await agent.answer(
            "اعطني القائمة الكاملة للمطعم", user_id=sender_id
        )
        await client.send_text(chat_id, reply)

    elif command in ("/عروض", "/offers", "/خصومات"):
        reply = await agent.answer(
            "ما هي عروض وخصومات اليوم؟", user_id=sender_id
        )
        await client.send_text(chat_id, reply)

    elif command in ("/توصية", "/recommend", "/توصيه"):
        reply = await agent.answer(
            "ما هي توصيات الشيف اليوم؟", user_id=sender_id
        )
        await client.send_text(chat_id, reply)

    elif command in ("/مطعم", "/info", "/معلومات"):
        reply = await agent.answer(
            "أخبرني عن معلومات المطعم وأوقات العمل", user_id=sender_id
        )
        await client.send_text(chat_id, reply)

    elif command == "/help":
        await client.send_text(chat_id, HELP_TEXT)

    # ── System commands ───────────────────────────────────────────
    elif command == "/status":
        status_text = await agent.get_status()
        await client.send_text(chat_id, status_text)

    elif command == "/ingest":
        await client.send_text(chat_id, "🔄 جارٍ إعادة فهرسة الملفات...")
        count = agent.rag_pipeline.ingest()
        if count > 0:
            agent.rag_pipeline.build_qa_chain(agent.llm)
            await client.send_text(chat_id, f"✅ تم فهرسة {count} قسم من الملفات.")
        else:
            await client.send_text(chat_id, "⚠️ لا توجد ملفات PDF في المجلد.")

    elif command == "/sources":
        sources = agent.get_pdf_sources()
        if sources:
            source_list = "\n".join(f"📄 {s}" for s in sources)
            await client.send_text(chat_id, f"*الملفات المتاحة:*\n\n{source_list}")
        else:
            await client.send_text(chat_id, "لا توجد ملفات مفهرسة بعد.")

    else:
        await client.send_text(
            chat_id,
            f"❓ أمر غير معروف: {command}\n\n"
            "اكتب /help لرؤية الأوامر المتاحة 😄",
        )


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
