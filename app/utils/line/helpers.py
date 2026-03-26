import logging
import hmac
import hashlib
import base64
import httpx
from typing import Union, Dict, List
from app.config import LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN

logger = logging.getLogger(__name__)

def verify_line_signature(body: bytes, signature: str) -> bool:
    if not LINE_CHANNEL_SECRET:
        logger.warning("LINE_CHANNEL_SECRET not set, skipping signature verification")
        return True
    hash_digest = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(hash_digest).decode('utf-8')
    return hmac.compare_digest(signature, expected_signature)

async def get_image_content_from_line(message_id: str) -> bytes:
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.content

async def reply_line(reply_token: str, message: Union[str, Dict, List], with_sticker: bool = False) -> None:
    """Reply to LINE with text message, dict, list of messages, and optionally a sticker"""
    try:
        logger.info(f"Replying to LINE token: {reply_token[:10]}...")
        url = "https://api.line.me/v2/bot/message/reply"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
        }
        
        # Build messages array
        messages = []
        if isinstance(message, str):
            messages.append({"type": "text", "text": message})
        elif isinstance(message, dict):
            messages.append(message)
        elif isinstance(message, list):
            for item in message:
                if isinstance(item, str):
                    messages.append({"type": "text", "text": item})
                elif isinstance(item, dict):
                    messages.append(item)
            
        # Add sticker if requested
        if with_sticker:
            # Use LINE's free sticker packages
            # Package 446: Brown & Cony's Friendly Stickers
            sticker_message = {
                "type": "sticker",
                "packageId": "446",
                "stickerId": "1988"  # Thumbs up sticker
            }
            messages.append(sticker_message)
        
        payload = {"replyToken": reply_token, "messages": messages}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"LINE API error: {response.status_code} - {response.text}")
            response.raise_for_status()
        logger.info("Reply sent to LINE")
    except Exception as e:
        logger.error(f"Error sending LINE reply: {e}", exc_info=True)
        # Don't raise exception here to avoid crashing the webhook handler

async def push_line(user_id: str, message: Union[str, Dict, List], with_sticker: bool = False) -> None:
    """Push message to LINE user (use when reply token is already consumed)"""
    try:
        logger.info(f"Pushing message to LINE user: {user_id[:10]}...")
        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
        }

        # Build messages array (same logic as reply_line)
        messages = []
        if isinstance(message, str):
            messages.append({"type": "text", "text": message})
        elif isinstance(message, dict):
            messages.append(message)
        elif isinstance(message, list):
            for item in message:
                if isinstance(item, str):
                    messages.append({"type": "text", "text": item})
                elif isinstance(item, dict):
                    messages.append(item)

        # Add sticker if requested
        if with_sticker:
            sticker_message = {
                "type": "sticker",
                "packageId": "446",
                "stickerId": "1988"
            }
            messages.append(sticker_message)

        # LINE API limit: max 5 messages per call
        if len(messages) > 5:
            logger.warning(f"Too many messages ({len(messages)}), truncating to 5")
            messages = messages[:5]

        payload = {"to": user_id, "messages": messages}

        # Debug: log message count and types
        logger.info(f"Sending {len(messages)} messages to LINE")
        for i, msg in enumerate(messages):
            msg_type = msg.get('type', 'unknown')
            alt_text = msg.get('altText', 'N/A')
            if alt_text and len(alt_text) > 50:
                alt_text = alt_text[:50]
            logger.info(f"  Message {i+1}: type={msg_type}, altText={alt_text}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)

            # Log error details if not successful
            if response.status_code != 200:
                logger.error(f"LINE API error: {response.status_code}")
                logger.error(f"LINE API response: {response.text}")

            response.raise_for_status()
        logger.info("Push message sent to LINE")
    except Exception as e:
        logger.error(f"Error sending LINE push message: {e}", exc_info=True)
        # Try to send a simple fallback message
        try:
            simple_payload = {
                "to": user_id,
                "messages": [{"type": "text", "text": "ขออภัยครับ เกิดข้อผิดพลาดในการส่งข้อความ กรุณาลองใหม่อีกครั้ง 🙏"}]
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, headers=headers, json=simple_payload)
        except Exception:
            pass  # Silent fail for fallback

