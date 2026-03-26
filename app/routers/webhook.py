import logging
import asyncio
import json
import time
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse

from app.services.welcome import (
    get_welcome_message,
    get_usage_guide,
    get_product_catalog_message,
    get_help_menu
)
from app.services.memory import clear_memory
from app.services.chat.handler import handle_natural_conversation
from app.services.cache import get_pending_context, delete_pending_context
from app.services.dealer_lookup import extract_location_llm, search_dealers, format_dealer_response, search_dealers_with_fallback
from app.services.cache import save_pending_context as save_pending_ctx
from app.utils.line.helpers import (
    verify_line_signature,
    reply_line,
)
from app.utils.rate_limiter import check_user_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def callback(request: Request, x_line_signature: str = Header(None)):
    """
    LINE Webhook endpoint - returns 200 immediately to prevent timeout.
    Actual processing happens in background via asyncio.create_task.
    """
    if not x_line_signature:
        raise HTTPException(status_code=400, detail="Missing X-Line-Signature header")

    body = await request.body()
    body_str = body.decode('utf-8')

    # Verify signature
    try:
        if not verify_line_signature(body, x_line_signature):
            logger.warning("Invalid signature")
            raise HTTPException(status_code=400, detail="Invalid signature")
    except HTTPException:
        raise
    except Exception as sig_err:
        logger.error(f"Signature verification error: {sig_err}", exc_info=True)
        raise HTTPException(status_code=500, detail="Signature verification failed")

    # Parse events
    try:
        events = json.loads(body_str).get("events", [])
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse webhook body: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # FIX: Return 200 IMMEDIATELY to prevent LINE timeout (499)
    # Process events in background - reply_token valid for ~30 seconds
    if events:
        asyncio.create_task(_process_webhook_events(events))

    return JSONResponse(content={"status": "success"})


async def _process_webhook_events(events: list):
    """Process webhook events in background task (per-event error isolation)"""
    start_time = time.time()
    try:
        for event in events:
            event_type = event.get("type")
            reply_token = event.get("replyToken")
            user_id = event.get("source", {}).get("userId")

            if not reply_token or not user_id:
                continue

            # Check rate limit
            if not await check_user_rate_limit(user_id):
                await reply_line(reply_token, "ขออภัยครับ คุณส่งข้อความเร็วเกินไป กรุณารอสักครู่นะครับ")
                continue

            # Ensure user exists (auto-register new users)
            from app.services.user_service import ensure_user_exists
            await ensure_user_exists(user_id)

            # 1. Handle Follow Event (Welcome Message)
            if event_type == "follow":
                logger.info(f"User {user_id} followed the bot")
                welcome_text = get_welcome_message()
                await reply_line(reply_token, welcome_text)
                continue

            # 2. Handle Image Message — ปฏิเสธ (ไม่มีฟีเจอร์สแกนโรคพืช)
            if event_type == "message" and event.get("message", {}).get("type") == "image":
                await reply_line(reply_token, "ขออภัยครับ พี่ม้าบินรับได้เฉพาะข้อความเท่านั้นนะครับ ถ้ามีคำถามเรื่องปุ๋ยหรือการดูแลพืช พิมพ์ถามมาได้เลยครับ")
                continue

            # 3. Handle Text Message
            elif event_type == "message" and event.get("message", {}).get("type") == "text":
                text = event["message"]["text"].strip()
                logger.info(f"Received text from {user_id}: {text}")

                # ============================================================================#
                # Pending Context Check (e.g. awaiting dealer province)
                # ============================================================================#
                ctx = await get_pending_context(user_id)
                if ctx and ctx.get("state") == "awaiting_dealer_province":
                    province, district, subdistrict = await extract_location_llm(text)
                    if not province:
                        province = text.strip()

                    # Merge saved district/subdistrict from pending context
                    saved_district = ctx.get("district")
                    saved_subdistrict = ctx.get("subdistrict")
                    if saved_district and not district:
                        district = saved_district
                    if saved_subdistrict and not subdistrict:
                        subdistrict = saved_subdistrict

                    dealers, fallback_prov, missed_location = await search_dealers_with_fallback(province, district, subdistrict)

                    if dealers:
                        if missed_location and not fallback_prov:
                            answer = f"ยังไม่พบตัวแทนใน {missed_location} โดยตรง\n"
                            answer += f"แต่พบตัวแทนในจังหวัด{province} ครับ\n\n"
                            answer += format_dealer_response(dealers, province)
                        elif fallback_prov:
                            answer = f"ยังไม่พบตัวแทนใน จ.{province} โดยตรง\nแต่มีในจังหวัดใกล้เคียง ({fallback_prov}) ครับ\n\n"
                            answer += format_dealer_response(dealers, fallback_prov)
                        else:
                            answer = format_dealer_response(dealers, province)
                        await delete_pending_context(user_id)
                        await reply_line(reply_token, answer)
                    elif not ctx.get("retried"):
                        # ครั้งแรกที่ไม่เจอ → ถามซ้ำ
                        ctx["retried"] = True
                        await save_pending_ctx(user_id, ctx)
                        await reply_line(reply_token,
                            f"ขออภัยครับ ไม่พบ '{text}' ในข้อมูลตัวแทนจำหน่าย\nลองพิมพ์ชื่อจังหวัดใหม่อีกครั้งนะครับ เช่น สุพรรณบุรี, ลพบุรี, นครราชสีมา 😊")
                    else:
                        # ถามซ้ำแล้วยังไม่เจอ → จบ flow
                        await delete_pending_context(user_id)
                        await reply_line(reply_token,
                            f"ขออภัยครับ ยังไม่พบตัวแทนจำหน่ายใน{province} ลองติดต่อสอบถามที่เพจม้าบินได้เลยนะครับ 😊")
                    continue

                # ============================================================================#
                # Quick Commands
                # ============================================================================#
                logger.info(f"Processing text: '{text}'")

                # 0. Check for usage guide request
                if text in ["วิธีใช้งาน", "วิธีใช้", "ช่วยเหลือ", "help"]:
                    logger.info(f"User {user_id} requested usage guide")
                    usage_guide = get_usage_guide()
                    await reply_line(reply_token, usage_guide)
                    continue

                # 0.1 Check for product catalog request
                if text in ["ดูผลิตภัณฑ์", "ผลิตภัณฑ์", "สินค้า", "products"]:
                    logger.info(f"User {user_id} requested product catalog")
                    catalog = get_product_catalog_message()
                    await reply_line(reply_token, catalog)
                    continue

                # ============================================================================#

                # Normal text message handling
                if text.lower() in ["ล้างความจำ", "reset", "clear"]:
                    await clear_memory(user_id)
                    await reply_line(reply_token, "ล้างความจำเรียบร้อยครับ เริ่มต้นใหม่ได้เลย!")

                elif text.lower() in ["ช่วยเหลือ", "help", "เมนู"]:
                    # Use Flex Message for help menu
                    help_flex = get_help_menu()
                    await reply_line(reply_token, help_flex)

                else:
                    # Q&A Chat - Vector Search from products, knowledge
                    answer = await handle_natural_conversation(user_id, text)
                    await reply_line(reply_token, answer)

            # 4. Handle Sticker (Just for fun)
            elif event_type == "message" and event.get("message", {}).get("type") == "sticker":
                await reply_line(reply_token, "ขอบคุณครับ!", with_sticker=True)

        logger.info(f"Background webhook processing completed in {time.time() - start_time:.2f}s")

    except Exception as e:
        logger.error(f"Background webhook error: {e}", exc_info=True)
        # Try to send error reply if we have a valid reply_token
        try:
            if 'reply_token' in dir() and reply_token:
                await reply_line(reply_token, "ขออภัยครับ เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้งนะครับ")
        except Exception:
            pass  # reply_token may have expired
