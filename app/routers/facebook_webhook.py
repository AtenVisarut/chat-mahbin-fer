import logging
import asyncio
import time
from fastapi import APIRouter, Request, Query, Response

from app.utils.facebook.helpers import (
    verify_facebook_webhook,
    verify_fb_signature,
    send_facebook_message,
    send_typing_on,
    split_message,
)
from app.services.chat.handler import handle_natural_conversation
from app.services.memory import clear_memory, add_to_memory
from app.utils.rate_limiter import check_user_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/facebook", tags=["facebook"])


# ──────────────────────────────────────────────
# GET  /facebook/webhook — one-time verification
# ──────────────────────────────────────────────
@router.get("/webhook")
async def verify(
    mode: str = Query(alias="hub.mode", default=""),
    token: str = Query(alias="hub.verify_token", default=""),
    challenge: str = Query(alias="hub.challenge", default=""),
):
    result = verify_facebook_webhook(mode, token, challenge)
    if result is not None:
        return Response(content=result, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)


# ──────────────────────────────────────────────
# POST /facebook/webhook — receive messages
# ──────────────────────────────────────────────
@router.post("/webhook")
async def receive(request: Request):
    body = await request.body()

    # Optional: verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if signature and not verify_fb_signature(body, signature):
        logger.warning("Invalid Facebook signature")
        return Response(content="Invalid signature", status_code=403)

    data = await request.json()

    if data.get("object") != "page":
        return Response(content="Not a page event", status_code=404)

    # Return 200 immediately (Facebook requires response within 20s)
    # Process messages in background
    entries = data.get("entry", [])
    for entry in entries:
        for messaging_event in entry.get("messaging", []):
            asyncio.create_task(_process_fb_message(messaging_event))

    return {"status": "ok"}


async def _process_fb_message(event: dict) -> None:
    """Process a single Facebook messaging event in background."""
    start_time = time.time()
    psid = event.get("sender", {}).get("id")
    if not psid:
        return

    # Namespace user_id to avoid collision with LINE user IDs
    user_id = f"fb:{psid}"

    try:
        message = event.get("message", {})
        text = message.get("text", "").strip()

        # Skip non-text messages for now (Phase 1: text only)
        if not text:
            # Could be image, sticker, etc. — Phase 2
            if message.get("attachments"):
                await send_facebook_message(psid, "พี่ม้าบินยังไม่สามารถสแกนโรคพืชจากภาพได้ครับ พี่ม้าบินจะรับได้เฉพาะข้อความเท่านั้นนะครับ ขอบคุณครับ")
            return

        logger.info(f"FB message from {psid}: {text}")

        # Rate limit check
        if not await check_user_rate_limit(user_id):
            await send_facebook_message(psid, "ขออภัยครับ คุณส่งข้อความเร็วเกินไป กรุณารอสักครู่นะครับ")
            return

        # Ensure user exists
        from app.services.user_service import ensure_user_exists
        await ensure_user_exists(user_id)

        # Quick commands
        if text.lower() in ["ล้างความจำ", "reset", "clear"]:
            await clear_memory(user_id)
            await send_facebook_message(psid, "ล้างความจำเรียบร้อยครับ เริ่มต้นใหม่ได้เลย!")
            return

        # Send typing indicator
        await send_typing_on(psid)

        # Core conversation (platform-agnostic)
        answer = await handle_natural_conversation(user_id, text)

        # Split long messages for FB 2000-char limit
        chunks = split_message(answer)
        for chunk in chunks:
            await send_facebook_message(psid, chunk)

        logger.info(f"FB reply sent to {psid} ({len(chunks)} chunk(s)) in {time.time() - start_time:.2f}s")

    except Exception as e:
        logger.error(f"Error processing FB message from {psid}: {e}", exc_info=True)
        try:
            await send_facebook_message(psid, "ขออภัยครับ เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้งนะครับ")
        except Exception:
            pass
