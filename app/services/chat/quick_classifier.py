"""
Quick Classifier Service
จำแนกประเภทปัญหาพืชจากภาพอย่างรวดเร็ว (~1-2 วินาที)
ใช้ Claude Haiku หรือ Gemini Flash (เร็ว + ถูก)
"""

import logging
import base64
import json
import asyncio
from typing import Optional
from dataclasses import dataclass
from enum import Enum

import httpx
from openai import AsyncOpenAI

import os
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

logger = logging.getLogger(__name__)


class ProblemCategory(str, Enum):
    """ประเภทปัญหาพืช"""
    FUNGAL = "fungal"           # โรคเชื้อรา
    BACTERIAL = "bacterial"     # โรคแบคทีเรีย
    VIRAL = "viral"             # โรคไวรัส
    INSECT = "insect"           # แมลงศัตรูพืช
    NUTRIENT = "nutrient"       # ขาดธาตุอาหาร
    WEED = "weed"               # วัชพืช
    HEALTHY = "healthy"         # ไม่พบปัญหา
    UNKNOWN = "unknown"         # ไม่แน่ใจ


@dataclass
class ClassificationResult:
    """ผลลัพธ์การจำแนกประเภท"""
    category: ProblemCategory
    plant_type: str
    confidence: float
    keywords: list
    summary: str


# Initialize Haiku client via OpenRouter
haiku_client = None
if OPENROUTER_API_KEY:
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=10.0,
            read=20.0,
            write=20.0,
            pool=20.0
        )
    )
    haiku_client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
        http_client=http_client
    )
    logger.info("Quick Classifier (Haiku) initialized")


CLASSIFIER_PROMPT = """คุณคือระบบจำแนกปัญหาพืชอย่างรวดเร็ว

ดูภาพและตอบเป็น JSON เท่านั้น (ไม่ต้องใส่ ```json):

{
  "category": "fungal|bacterial|viral|insect|nutrient|weed|healthy|unknown",
  "plant_type": "ชนิดพืช เช่น ข้าว, ทุเรียน, มะม่วง, อ้อย, ข้าวโพด",
  "confidence": 0.0-1.0,
  "keywords": ["คำสำคัญ 3-5 คำ ที่อธิบายปัญหา/อาการ"],
  "summary": "สรุปสั้นๆ 1 บรรทัด"
}

หมวดหมู่:
- fungal: โรคเชื้อรา (จุด, ไหม้, ราขาว, ราดำ, ราสนิม, กาบใบแห้ง, เน่า)
- bacterial: โรคแบคทีเรีย (เน่าเละ, เหี่ยว, แผลฉ่ำน้ำ, ขอบใบแห้ง, ใบขีด)
- viral: โรคไวรัส (ด่าง, หงิก, บิดงอ, แคระ, ใบม้วน, สีเหลืองผิดปกติ)
- insect: แมลง (เพลี้ย, หนอน, ด้วง, ไร, รอยกัด, รอยเจาะ)
- nutrient: ขาดธาตุ (เหลืองสม่ำเสมอทั้งใบ, ขอบใบไหม้, เส้นใบเขียวแต่พื้นใบเหลือง)
- weed: วัชพืช
- healthy: ไม่พบปัญหา พืชแข็งแรง
- unknown: ไม่แน่ใจ ภาพไม่ชัด

ตอบเร็วและกระชับ!"""


async def quick_classify(
    image_bytes: bytes,
    extra_info: Optional[str] = None
) -> ClassificationResult:
    """
    Quick classification of plant problem from image.
    Uses Claude Haiku for speed (~1-2 seconds).

    Args:
        image_bytes: รูปภาพ (bytes)
        extra_info: ข้อมูลเพิ่มเติมจากผู้ใช้ (optional)

    Returns:
        ClassificationResult with category, plant_type, confidence, keywords, summary
    """
    if not haiku_client:
        logger.warning("Haiku client not available, returning unknown")
        return ClassificationResult(
            category=ProblemCategory.UNKNOWN,
            plant_type="",
            confidence=0.0,
            keywords=[],
            summary="ไม่สามารถวิเคราะห์ได้ (API not configured)"
        )

    try:
        # Encode image
        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        # Build prompt
        prompt = CLASSIFIER_PROMPT
        if extra_info:
            prompt += f"\n\nข้อมูลเพิ่มเติมจากผู้ใช้: {extra_info}"

        # Call Haiku via OpenRouter
        response = await asyncio.wait_for(
            haiku_client.chat.completions.create(
                model="anthropic/claude-3-haiku",  # Fast & cheap
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                            }
                        ]
                    }
                ],
                max_tokens=300,
                temperature=0.1,
                extra_headers={
                    "HTTP-Referer": "https://ladda-chatbot.railway.app",
                    "X-Title": "Ladda Quick Classifier",
                }
            ),
            timeout=15
        )

        raw_text = response.choices[0].message.content.strip()
        logger.debug(f"Quick classifier response: {raw_text[:200]}")

        # Parse JSON
        try:
            # Clean markdown if present
            json_str = raw_text
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
            if json_str.endswith("```"):
                json_str = json_str[:-3]

            data = json.loads(json_str.strip())

            # Parse category
            category_str = data.get("category", "unknown").lower()
            try:
                category = ProblemCategory(category_str)
            except ValueError:
                category = ProblemCategory.UNKNOWN

            return ClassificationResult(
                category=category,
                plant_type=data.get("plant_type", ""),
                confidence=float(data.get("confidence", 0.5)),
                keywords=data.get("keywords", []),
                summary=data.get("summary", "")
            )

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse classifier response: {e}")
            # Try to extract info from raw text
            return ClassificationResult(
                category=ProblemCategory.UNKNOWN,
                plant_type="",
                confidence=0.3,
                keywords=[],
                summary=raw_text[:100] if raw_text else "ไม่สามารถวิเคราะห์ได้"
            )

    except asyncio.TimeoutError:
        logger.error("Quick classifier timeout (15s)")
        return ClassificationResult(
            category=ProblemCategory.UNKNOWN,
            plant_type="",
            confidence=0.0,
            keywords=[],
            summary="Timeout - กรุณาลองใหม่"
        )

    except httpx.ConnectError as e:
        logger.error(f"Quick classifier connection error: {e}")
        return ClassificationResult(
            category=ProblemCategory.UNKNOWN,
            plant_type="",
            confidence=0.0,
            keywords=[],
            summary="Connection Error"
        )

    except Exception as e:
        logger.error(f"Quick classifier error: {e}", exc_info=True)
        return ClassificationResult(
            category=ProblemCategory.UNKNOWN,
            plant_type="",
            confidence=0.0,
            keywords=[],
            summary=str(e)[:50]
        )


async def quick_classify_with_fallback(
    image_bytes: bytes,
    extra_info: Optional[str] = None
) -> ClassificationResult:
    """
    Quick classify with fallback to Gemini Flash if Haiku fails.
    """
    # Try Haiku first
    result = await quick_classify(image_bytes, extra_info)

    # If failed and we have fallback, try Gemini Flash
    if result.category == ProblemCategory.UNKNOWN and result.confidence == 0.0:
        logger.info("Haiku failed, trying Gemini Flash fallback")
        result = await _classify_with_gemini_flash(image_bytes, extra_info)

    return result


async def _classify_with_gemini_flash(
    image_bytes: bytes,
    extra_info: Optional[str] = None
) -> ClassificationResult:
    """Fallback classifier using Gemini Flash"""
    if not haiku_client:  # Reuse the same OpenRouter client
        return ClassificationResult(
            category=ProblemCategory.UNKNOWN,
            plant_type="",
            confidence=0.0,
            keywords=[],
            summary="No API client"
        )

    try:
        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        prompt = CLASSIFIER_PROMPT
        if extra_info:
            prompt += f"\n\nข้อมูลเพิ่มเติม: {extra_info}"

        response = await asyncio.wait_for(
            haiku_client.chat.completions.create(
                model="google/gemini-flash-1.5",  # Fast Gemini
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                            }
                        ]
                    }
                ],
                max_tokens=300,
                temperature=0.1
            ),
            timeout=20
        )

        raw_text = response.choices[0].message.content.strip()

        # Parse JSON (same as above)
        json_str = raw_text
        if json_str.startswith("```"):
            json_str = json_str.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]

        data = json.loads(json_str.strip())

        category_str = data.get("category", "unknown").lower()
        try:
            category = ProblemCategory(category_str)
        except ValueError:
            category = ProblemCategory.UNKNOWN

        return ClassificationResult(
            category=category,
            plant_type=data.get("plant_type", ""),
            confidence=float(data.get("confidence", 0.5)),
            keywords=data.get("keywords", []),
            summary=data.get("summary", "")
        )

    except Exception as e:
        logger.error(f"Gemini Flash fallback error: {e}")
        return ClassificationResult(
            category=ProblemCategory.UNKNOWN,
            plant_type="",
            confidence=0.0,
            keywords=[],
            summary=str(e)[:50]
        )
