import logging
import asyncio
import re
from app.dependencies import supabase_client
from app.config import MAX_MEMORY_MESSAGES, MEMORY_CONTEXT_WINDOW, MEMORY_CONTENT_PREVIEW

logger = logging.getLogger(__name__)

# Lock to prevent concurrent cleanup_old_memory for the same user
_cleanup_locks: dict = {}

def _get_cleanup_lock(user_id: str) -> asyncio.Lock:
    """Get or create a per-user asyncio lock for memory cleanup"""
    if user_id not in _cleanup_locks:
        _cleanup_locks[user_id] = asyncio.Lock()
    return _cleanup_locks[user_id]

async def add_to_memory(user_id: str, role: str, content: str, metadata: dict = None):
    """Add message to conversation memory in Supabase"""
    try:
        if not supabase_client:
            logger.warning("Supabase not available, skipping memory storage")
            return
        
        # Truncate very long messages
        truncated_content = content[:2000] if len(content) > 2000 else content
        
        data = {
            "user_id": user_id,
            "role": role,  # "user" or "assistant"
            "content": truncated_content,
            "metadata": metadata or {}
        }
        
        result = supabase_client.table('conver_mem_doccrop').insert(data).execute()
        logger.info(f"✓ Added to memory: {role} message for user {user_id[:8]}...")
        
        # Clean up old messages (keep last N per user)
        await cleanup_old_memory(user_id)
        
    except Exception as e:
        logger.error(f"Failed to add to memory: {e}")

async def get_conversation_context(user_id: str, limit: int = MEMORY_CONTEXT_WINDOW) -> str:
    """Get conversation history as context string from Supabase"""
    try:
        if not supabase_client:
            return ""

        # Get last N messages for this user
        result = supabase_client.table('conver_mem_doccrop')\
            .select('role, content, metadata, created_at')\
            .eq('user_id', user_id)\
            .order('created_at', desc=True)\
            .limit(limit)\
            .execute()

        if not result.data:
            return ""

        # Reverse to get chronological order
        messages = list(reversed(result.data))

        context_parts = []
        for msg in messages:
            role = "ผู้ใช้" if msg["role"] == "user" else "พี่ม้าบิน"
            content = msg["content"][:MEMORY_CONTENT_PREVIEW]  # Use config value

            # Add product info from metadata if available
            metadata = msg.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("type") == "product_recommendation":
                products = metadata.get("products", [])
                if products:
                    product_names = [p.get("product_name", "") for p in products[:3]]
                    content += f" (สินค้าที่แนะนำ: {', '.join(product_names)})"

            context_parts.append(f"{role}: {content}")

        logger.info(f"✓ Retrieved {len(messages)} messages from memory")
        return "\n".join(context_parts)

    except Exception as e:
        logger.error(f"Failed to get conversation context: {e}")
        return ""

async def cleanup_old_memory(user_id: str):
    """Keep only last N messages per user (per-user lock prevents race conditions)"""
    lock = _get_cleanup_lock(user_id)
    if lock.locked():
        # Another cleanup is already running for this user — skip
        return

    async with lock:
        try:
            if not supabase_client:
                return

            # Get all message IDs for this user, ordered by created_at desc
            result = supabase_client.table('conver_mem_doccrop')\
                .select('id')\
                .eq('user_id', user_id)\
                .order('created_at', desc=True)\
                .execute()

            if not result.data or len(result.data) <= MAX_MEMORY_MESSAGES:
                return

            # Get IDs to delete (keep only last MAX_MEMORY_MESSAGES)
            ids_to_delete = [msg['id'] for msg in result.data[MAX_MEMORY_MESSAGES:]]

            if ids_to_delete:
                # Delete old messages
                supabase_client.table('conver_mem_doccrop')\
                    .delete()\
                    .in_('id', ids_to_delete)\
                    .execute()
                logger.info(f"✓ Cleaned up {len(ids_to_delete)} old messages for user {user_id[:8]}...")

        except Exception as e:
            logger.error(f"Failed to cleanup old memory: {e}")

async def clear_memory(user_id: str):
    """Clear all conversation memory + all cache layers for user"""
    try:
        if not supabase_client:
            logger.warning("Supabase not available")
            return

        # 1. Delete from conver_mem_doccrop table
        supabase_client.table('conver_mem_doccrop')\
            .delete()\
            .eq('user_id', user_id)\
            .execute()

        logger.info(f"✓ Cleared memory for user {user_id[:8]}...")

    except Exception as e:
        logger.error(f"Failed to clear memory: {e}")

async def get_memory_stats(user_id: str) -> dict:
    """Get memory statistics for user"""
    try:
        if not supabase_client:
            return {"total": 0, "user_messages": 0, "assistant_messages": 0}

        result = supabase_client.table('conver_mem_doccrop')\
            .select('role')\
            .eq('user_id', user_id)\
            .execute()

        if not result.data:
            return {"total": 0, "user_messages": 0, "assistant_messages": 0}

        user_count = sum(1 for msg in result.data if msg['role'] == 'user')
        assistant_count = sum(1 for msg in result.data if msg['role'] == 'assistant')

        return {
            "total": len(result.data),
            "user_messages": user_count,
            "assistant_messages": assistant_count
        }

    except Exception as e:
        logger.error(f"Failed to get memory stats: {e}")
        return {"total": 0, "user_messages": 0, "assistant_messages": 0}


async def get_recommended_products(user_id: str, limit: int = 5) -> list:
    """
    ดึงข้อมูลสินค้าที่แนะนำล่าสุดจาก memory
    สำหรับตอบคำถามวิธีใช้/การพ่นยา
    """
    try:
        if not supabase_client:
            return []

        # ค้นหาข้อความที่มี metadata เป็น product_recommendation
        result = supabase_client.table('conver_mem_doccrop')\
            .select('content, metadata, created_at')\
            .eq('user_id', user_id)\
            .order('created_at', desc=True)\
            .limit(20)\
            .execute()

        if not result.data:
            return []

        # หา product recommendations จาก metadata
        all_products = []
        for msg in result.data:
            metadata = msg.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("type") == "product_recommendation":
                products = metadata.get("products", [])
                if products:
                    all_products.extend(products)
                    # ได้สินค้าพอแล้ว
                    if len(all_products) >= limit:
                        break

        # ลบ duplicate
        seen = set()
        unique_products = []
        for p in all_products:
            name = p.get("product_name", "")
            if name and name not in seen:
                seen.add(name)
                unique_products.append(p)

        logger.info(f"✓ Retrieved {len(unique_products)} products from memory for user {user_id[:8]}...")
        return unique_products[:limit]

    except Exception as e:
        logger.error(f"Failed to get recommended products: {e}")
        return []


async def get_conversation_summary(user_id: str) -> dict:
    """
    สรุปบทสนทนา: หัวข้อที่คุย, สินค้าที่แนะนำ, พืชที่ถาม
    ใช้สำหรับให้ AI เข้าใจ context ได้ดีขึ้น
    """
    try:
        if not supabase_client:
            return {}

        result = supabase_client.table('conver_mem_doccrop')\
            .select('role, content, metadata, created_at')\
            .eq('user_id', user_id)\
            .order('created_at', desc=True)\
            .limit(MEMORY_CONTEXT_WINDOW)\
            .execute()

        if not result.data:
            return {}

        # Extract topics and products from conversation
        topics = []
        products_mentioned = []
        plants_mentioned = []
        last_question = ""

        # Plant keywords
        plant_keywords = [
            "ข้าว", "ทุเรียน", "มะม่วง", "ส้ม", "พริก", "ข้าวโพด", "อ้อย",
            "ลำไย", "มันสำปะหลัง", "ยางพารา", "ปาล์ม", "ถั่ว", "ผัก"
        ]

        for msg in result.data:
            content = msg.get("content", "")
            metadata = msg.get("metadata", {})

            # Get last user question
            if msg["role"] == "user" and not last_question:
                last_question = content[:200]

            # Extract products from metadata
            if isinstance(metadata, dict) and metadata.get("type") == "product_recommendation":
                products = metadata.get("products", [])
                for p in products:
                    name = p.get("product_name", "")
                    if name and name not in products_mentioned:
                        products_mentioned.append(name)

            # Extract plants from content
            for plant in plant_keywords:
                if plant in content and plant not in plants_mentioned:
                    plants_mentioned.append(plant)

            # Extract topics (simple keyword detection)
            if msg["role"] == "user":
                if any(kw in content for kw in ["โรค", "รักษา", "ป้องกัน"]):
                    if "โรคพืช" not in topics:
                        topics.append("โรคพืช")
                if any(kw in content for kw in ["แมลง", "เพลี้ย", "หนอน", "กำจัด"]):
                    if "แมลงศัตรูพืช" not in topics:
                        topics.append("แมลงศัตรูพืช")
                if any(kw in content for kw in ["หญ้า", "วัชพืช"]):
                    if "วัชพืช" not in topics:
                        topics.append("วัชพืช")
                if any(kw in content for kw in ["บำรุง", "ธาตุ", "ปุ๋ย", "ติดดอก", "ติดผล"]):
                    if "การบำรุง" not in topics:
                        topics.append("การบำรุง")
                if any(kw in content for kw in ["วิธีใช้", "อัตรา", "ผสม"]):
                    if "วิธีใช้สินค้า" not in topics:
                        topics.append("วิธีใช้สินค้า")

        # Fallback: if no products found via metadata, scan assistant message text
        if not products_mentioned:
            try:
                from app.services.chat.handler import ICP_PRODUCT_NAMES
                for msg in result.data:
                    if msg["role"] != "assistant":
                        continue
                    content_lower = msg.get("content", "").lower()
                    for product_name, aliases in ICP_PRODUCT_NAMES.items():
                        for alias in aliases:
                            if alias.lower() in content_lower and product_name not in products_mentioned:
                                products_mentioned.append(product_name)
                    if products_mentioned:
                        break  # got products from most recent assistant message
            except ImportError:
                logger.warning("Could not import ICP_PRODUCT_NAMES for fallback product extraction")

        summary = {
            "topics": topics[:5],
            "products_mentioned": products_mentioned[:10],
            "plants_mentioned": plants_mentioned[:5],
            "last_question": last_question,
            "total_messages": len(result.data)
        }

        logger.info(f"✓ Conversation summary: {len(topics)} topics, {len(products_mentioned)} products")
        return summary

    except Exception as e:
        logger.error(f"Failed to get conversation summary: {e}")
        return {}


def compute_active_topic(formatted_messages: list, current_query: str) -> tuple:
    """
    แบ่ง messages ออกเป็น active topic (เกี่ยวกับคำถามปัจจุบัน) กับ past topics.

    Scan จากหลังมาหน้า (ล่าสุดก่อน). ข้อความเป็น active topic จนกว่าจะเจอ
    topic boundary — คือข้อความที่พูดถึงสินค้า/โรค/แมลงตัวอื่น หรือมีคำบ่งชี้เปลี่ยนหัวข้อ.

    Args:
        formatted_messages: list of dicts with keys: role, content, metadata
                            (chronological order, oldest first)
        current_query: คำถามปัจจุบันของ user

    Returns:
        (active_messages: list[str], past_summary: str, recent_products: list[str])
        active_messages = formatted strings "ผู้ใช้: ..." or "พี่ม้าบิน: ..."
        past_summary = short summary of past topics (or "")
        recent_products = product names from the last assistant recommendation in active topic
    """
    try:
        from app.services.chat.handler import extract_product_name_from_question, ICP_PRODUCT_NAMES
    except ImportError:
        # Fallback: return all messages as active, no past summary
        all_formatted = []
        for msg in formatted_messages:
            role = "ผู้ใช้" if msg["role"] == "user" else "พี่ม้าบิน"
            content = msg["content"][:MEMORY_CONTENT_PREVIEW]
            metadata = msg.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("type") == "product_recommendation":
                products = metadata.get("products", [])
                if products:
                    pnames = [p.get("product_name", "") for p in products[:3]]
                    content += f" (สินค้าที่แนะนำ: {', '.join(pnames)})"
            all_formatted.append(f"{role}: {content}")
        return all_formatted, "", []

    # --- Extract entities from current query ---
    current_product = extract_product_name_from_question(current_query)

    # Topic-change keywords (user is done with previous topic)
    _TOPIC_BOUNDARY_WORDS = [
        "ขอบคุณ", "โอเค", "oke", "ok", "อีกเรื่อง", "เปลี่ยนเรื่อง",
        "ถามเรื่องอื่น", "เรื่องอื่น", "หัวข้ออื่น",
    ]

    # Format all messages first
    formatted = []
    for msg in formatted_messages:
        role = "ผู้ใช้" if msg["role"] == "user" else "พี่ม้าบิน"
        content = msg["content"][:MEMORY_CONTENT_PREVIEW]
        metadata = msg.get("metadata", {})
        if isinstance(metadata, dict) and metadata.get("type") == "product_recommendation":
            products = metadata.get("products", [])
            if products:
                pnames = [p.get("product_name", "") for p in products[:3]]
                content += f" (สินค้าที่แนะนำ: {', '.join(pnames)})"
        formatted.append({
            "text": f"{role}: {content}",
            "role": msg["role"],
            "content": msg["content"],
            "metadata": metadata,
        })

    if not formatted:
        return [], ""

    # --- Scan from newest to oldest to find topic boundary ---
    boundary_idx = -1  # index in formatted (chronological) where boundary is found
    for i in range(len(formatted) - 1, -1, -1):
        entry = formatted[i]
        raw_content = entry["content"]

        # Only user messages can be topic boundaries
        if entry["role"] != "user":
            continue

        # Check for topic-change keywords
        content_lower = raw_content.lower()
        if any(word in content_lower for word in _TOPIC_BOUNDARY_WORDS):
            boundary_idx = i
            break

        # Check if user mentioned a DIFFERENT product than current query
        msg_product = extract_product_name_from_question(raw_content)
        if msg_product and current_product and msg_product != current_product:
            boundary_idx = i
            break

        # Check if current query has a product but this old user message asks about
        # a different topic (disease/pest) without the current product
        if current_product and not msg_product:
            # This older message is about something else — could be same topic or not
            # We only break if we already found active messages below this
            pass

    # --- Helper: extract recent products from active entries (newest assistant msg) ---
    def _extract_recent_products(entries):
        """Find product names from the last assistant message with product metadata."""
        for entry in reversed(entries):
            if entry["role"] != "assistant":
                continue
            metadata = entry.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("type") == "product_recommendation":
                products = metadata.get("products", [])
                pnames = [p.get("product_name", "") for p in products if p.get("product_name")]
                if pnames:
                    return pnames
        return []

    # --- Split into active / past ---
    if boundary_idx < 0:
        # No boundary found — all messages are active topic
        active_texts = [f["text"] for f in formatted]
        recent_products = _extract_recent_products(formatted)
        return active_texts, "", recent_products

    active_texts = [f["text"] for f in formatted[boundary_idx + 1:]]
    past_entries = formatted[:boundary_idx + 1]

    # If active is empty (boundary is the very last msg), include boundary msg itself
    if not active_texts:
        active_texts = [formatted[boundary_idx]["text"]]
        past_entries = formatted[:boundary_idx]

    # Extract recent products from active topic entries only
    active_entries = formatted[boundary_idx + 1:] if boundary_idx >= 0 else formatted
    recent_products = _extract_recent_products(active_entries)

    # --- Build past summary ---
    past_products = set()
    past_topics = []
    for entry in past_entries:
        # Extract products from metadata
        metadata = entry.get("metadata", {})
        if isinstance(metadata, dict) and metadata.get("type") == "product_recommendation":
            for p in metadata.get("products", []):
                name = p.get("product_name", "")
                if name:
                    past_products.add(name)
        # Extract products from text
        p = extract_product_name_from_question(entry["content"])
        if p:
            past_products.add(p)
        # Collect user questions as topic hints
        if entry["role"] == "user":
            q = entry["content"][:80].strip()
            if q and q not in past_topics:
                past_topics.append(q)

    summary_parts = []
    if past_topics:
        # Show at most 3 past user questions
        for q in past_topics[-3:]:
            summary_parts.append(f"- เคยถามเรื่อง: {q}")
    if past_products:
        summary_parts.append(f"- สินค้าที่แนะนำ: {', '.join(sorted(past_products))}")

    past_summary = "\n".join(summary_parts) if summary_parts else ""
    return active_texts, past_summary, recent_products


async def get_enhanced_context(user_id: str, current_query: str = "") -> str:
    """
    สร้าง context แบบ enhanced สำหรับ AI
    รวม: บทสนทนาปัจจุบัน (topic-aware) + สรุปหัวข้อก่อนหน้า + สินค้าที่แนะนำ
    ใช้ structured format เพื่อให้ AI เข้าใจง่ายขึ้น

    Args:
        user_id: User identifier
        current_query: คำถามปัจจุบันของ user (ใช้สำหรับแยก active topic)
    """
    try:
        if not supabase_client:
            return ""

        # Fetch raw messages from DB
        result = supabase_client.table('conver_mem_doccrop')\
            .select('role, content, metadata, created_at')\
            .eq('user_id', user_id)\
            .order('created_at', desc=True)\
            .limit(MEMORY_CONTEXT_WINDOW)\
            .execute()

        if not result.data:
            return ""

        # Chronological order (oldest first)
        messages = list(reversed(result.data))

        # --- Topic-aware splitting ---
        recent_products = []
        if current_query:
            active_texts, past_summary, recent_products = compute_active_topic(messages, current_query)
        else:
            # No current query — format all messages as before (backward compat)
            active_texts = []
            for msg in messages:
                role = "ผู้ใช้" if msg["role"] == "user" else "พี่ม้าบิน"
                content = msg["content"][:MEMORY_CONTENT_PREVIEW]
                metadata = msg.get("metadata", {})
                if isinstance(metadata, dict) and metadata.get("type") == "product_recommendation":
                    products = metadata.get("products", [])
                    if products:
                        pnames = [p.get("product_name", "") for p in products[:3]]
                        content += f" (สินค้าที่แนะนำ: {', '.join(pnames)})"
                active_texts.append(f"{role}: {content}")
            past_summary = ""

        # Build structured enhanced context
        parts = []

        # Section 1: Active topic conversation
        if active_texts:
            parts.append("[บทสนทนาปัจจุบัน]")
            parts.append("\n".join(active_texts))

        # Section 1.5: Recent products from metadata (most reliable source)
        if recent_products:
            parts.append("")
            parts.append(f"[สินค้าล่าสุดในบทสนทนา] {', '.join(recent_products)}")

        # Section 2: Past topic summary (from compute_active_topic)
        if past_summary:
            parts.append("")
            parts.append("[สรุปหัวข้อก่อนหน้า]")
            parts.append(past_summary)

        # Section 3: Get conversation summary for products/topics metadata
        summary = await get_conversation_summary(user_id)

        if summary:
            if summary.get("products_mentioned"):
                parts.append("")
                parts.append(f"[สินค้าที่แนะนำไปแล้ว] {', '.join(summary['products_mentioned'][:5])}")

            topic_parts = []
            if summary.get("topics"):
                topic_parts.append(f"หัวข้อ: {', '.join(summary['topics'])}")
            if summary.get("plants_mentioned"):
                topic_parts.append(f"พืช: {', '.join(summary['plants_mentioned'])}")
            if topic_parts:
                parts.append("")
                parts.append(f"[หัวข้อที่กำลังคุย] {' | '.join(topic_parts)}")

        logger.info(f"✓ Enhanced context: {len(active_texts)} active msgs, past_summary={'yes' if past_summary else 'no'}")
        return "\n".join(parts)

    except Exception as e:
        logger.error(f"Failed to get enhanced context: {e}")
        return ""


