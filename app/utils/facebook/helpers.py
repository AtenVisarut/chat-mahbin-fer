import logging
import hmac
import hashlib
import httpx
from app.config import FB_PAGE_ACCESS_TOKEN, FB_VERIFY_TOKEN, FB_APP_SECRET

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v21.0"


def verify_facebook_webhook(mode: str, token: str, challenge: str) -> str | None:
    """Verify webhook subscription (GET request from Facebook — once during setup)."""
    if mode == "subscribe" and token == FB_VERIFY_TOKEN:
        logger.info("Facebook webhook verified successfully")
        return challenge
    logger.warning(f"Facebook webhook verification failed: mode={mode}")
    return None


def verify_fb_signature(body: bytes, signature: str) -> bool:
    """Verify X-Hub-Signature-256 header on incoming POST requests."""
    if not FB_APP_SECRET:
        logger.warning("FB_APP_SECRET not set, skipping signature verification")
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        FB_APP_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


async def send_facebook_message(psid: str, text: str) -> None:
    """Send a text message to a Facebook user via Send API."""
    url = f"{GRAPH_API}/me/messages"
    headers = {"Content-Type": "application/json"}
    params = {"access_token": FB_PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, params=params, json=payload)
            if response.status_code != 200:
                logger.error(f"FB Send API error: {response.status_code} - {response.text}")
            response.raise_for_status()
        logger.info(f"Message sent to FB user {psid}")
    except Exception as e:
        logger.error(f"Error sending FB message to {psid}: {e}", exc_info=True)


async def send_typing_on(psid: str) -> None:
    """Send typing indicator to Facebook user."""
    url = f"{GRAPH_API}/me/messages"
    params = {"access_token": FB_PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": psid},
        "sender_action": "typing_on",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, params=params, json=payload)
    except Exception:
        pass  # typing indicator is best-effort


def split_message(text: str, max_len: int = 2000) -> list[str]:
    """Split long text into chunks of at most max_len chars, breaking at newlines."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        # If a single line exceeds max_len, hard-split it
        if len(line) > max_len:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(line), max_len):
                chunks.append(line[i : i + max_len])
            continue

        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= max_len:
            current = candidate
        else:
            chunks.append(current)
            current = line

    if current:
        chunks.append(current)

    return chunks
