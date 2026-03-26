"""
Query Understanding Agent for พี่ม้าบิน (Fertilizer Recommendation Chatbot)

Responsibilities:
- Semantic intent detection using LLM (not keyword matching)
- Entity extraction: crop, growth_stage, fertilizer_formula
- Query expansion for multi-query retrieval
- Determine required sources: mahbin_npk
"""

import logging
import json
import re
from typing import List, Dict

from app.services.rag import IntentType, QueryAnalysis
from app.config import LLM_MODEL_QUERY_UNDERSTANDING

logger = logging.getLogger(__name__)

# 6 crops in the mahbin_npk table
SUPPORTED_CROPS = ["นาข้าว", "ข้าวโพด", "อ้อย", "มันสำปะหลัง", "ปาล์มน้ำมัน", "ยางพารา"]

# Fertilizer-related keywords for fallback analysis
FERTILIZER_KEYWORDS = [
    "ปุ๋ย", "สูตร", "N-P-K", "NPK",
    "ไนโตรเจน", "ฟอสฟอรัส", "โพแทสเซียม",
    "เร่งต้น", "แตกกอ", "รับรวง", "เสริมผลผลิต",
    "ใส่ปุ๋ย", "แนะนำปุ๋ย", "ธาตุอาหาร", "บำรุง",
]

# Pattern to match fertilizer formulas like "46-0-0", "16-20-0", etc.
FORMULA_PATTERN = re.compile(r'\b(\d{1,2})-(\d{1,2})-(\d{1,2})\b')


class QueryUnderstandingAgent:
    """
    Agent 1: Query Understanding
    Uses LLM to semantically understand user queries about fertilizer recommendations
    """

    def __init__(self, openai_client=None):
        self.openai_client = openai_client

    async def analyze(self, query: str, context: str = "", hints: dict = None) -> QueryAnalysis:
        """
        Analyze user query to extract intent, entities, and generate expanded queries

        Args:
            query: Current user message
            context: Conversation history for understanding follow-up messages
            hints: Pre-detected hints dict with keys: crop, growth_stage, fertilizer_formula

        Returns:
            QueryAnalysis with intent, entities, expanded_queries, required_sources
        """
        try:
            logger.info(f"QueryUnderstandingAgent: Analyzing '{query[:50]}...'")

            # Build hints from external detection functions if not provided
            if hints is None:
                hints = {}

            if not self.openai_client:
                logger.warning("OpenAI client not available, using fallback analysis")
                return self._fallback_analysis(query)

            # Use LLM for semantic understanding with hints
            result = await self._llm_analyze(query, context=context, hints=hints)
            logger.info(f"QueryUnderstandingAgent: intent={result.intent}, confidence={result.confidence:.2f}")
            return result

        except Exception as e:
            logger.error(f"QueryUnderstandingAgent error: {e}", exc_info=True)
            return self._fallback_analysis(query)

    async def _llm_analyze(self, query: str, context: str = "", hints: dict = None) -> QueryAnalysis:
        """Use LLM for semantic query analysis with conversation context and hints"""

        if hints is None:
            hints = {}

        context_section = ""
        if context:
            context_section = f"""บริบทการสนทนาก่อนหน้า:
{context[:4000]}

สำคัญ: ถ้าคำถามเป็นการถามต่อเนื่อง (เช่น "ใส่ตอนไหน" "ใส่เท่าไหร่" "ใช้สูตรอะไร") ต้องดูว่าก่อนหน้านี้พูดถึงพืชหรือสูตรปุ๋ยอะไร แล้วใส่ใน entities ให้ครบ

"""

        # Build hint/constraint sections
        # [CONSTRAINT] = dictionary-matched, LLM must NOT override
        # [HINT] = softer suggestion, LLM may adjust
        hint_section = ""
        if hints.get('crop'):
            hint_section += f"\n[CONSTRAINT] ระบบตรวจพบชื่อพืช: \"{hints['crop']}\" — ใช้ชื่อนี้ใน entities.crop"
        if hints.get('growth_stage'):
            hint_section += f"\n[HINT] ระบบตรวจพบระยะการเจริญเติบโต: \"{hints['growth_stage']}\" — ใช้ใน entities.growth_stage"
        if hints.get('fertilizer_formula'):
            hint_section += f"\n[CONSTRAINT] ระบบตรวจพบสูตรปุ๋ย: \"{hints['fertilizer_formula']}\" — ใช้ใน entities.fertilizer_formula"
        if hints.get('resolved_slang'):
            hint_section += f"\n[HINT] ภาษาชาวบ้าน: {hints['resolved_slang']}"

        crops_str = ", ".join(SUPPORTED_CROPS)

        prompt = f"""{context_section}วิเคราะห์คำถามของผู้ใช้และตอบเป็น JSON
ถ้าคำถามเป็นข้อความสั้นหรือเป็นการถามต่อ (เช่น 'ใส่ตอนไหน' 'ใส่เท่าไหร่' 'ใช้สูตรอะไร' 'ใส่กี่กิโล'):
- ดูบริบทก่อนหน้าเพื่อหาพืชและสูตรปุ๋ยที่พี่ม้าบินแนะนำล่าสุด
- ใส่ชื่อพืชนั้นใน entities.crop
- intent ควรเป็น usage_instruction
{hint_section}

พืชในฐานข้อมูล: [{crops_str}]
(ฐานข้อมูลมี 19 แถว ครอบคลุม 6 พืช พร้อมสูตรปุ๋ย อัตราใส่ และระยะการใส่)

คำถาม: "{query}"

ตอบเป็น JSON format เท่านั้น (ไม่มี markdown):
{{
    "intent": "<intent_type>",
    "confidence": <0.0-1.0>,
    "entities": {{
        "crop": "<ชื่อพืชถ้ามี หรือ null>",
        "growth_stage": "<ระยะการเจริญเติบโตถ้ามี หรือ null>",
        "fertilizer_formula": "<สูตรปุ๋ย เช่น 46-0-0 ถ้ามี หรือ null>"
    }},
    "expanded_queries": ["<คำค้นหาภาษาไทย1>", "<คำค้นหาภาษาไทย2>", "<คำค้นหาภาษาไทย3>"],
    "required_sources": ["mahbin_npk"]
}}

intent_type ที่เป็นไปได้:
- fertilizer_recommendation: ขอแนะนำปุ๋ยสำหรับพืช/ระยะ (เช่น "ปุ๋ยอ้อย ใส่อะไรดี", "แนะนำปุ๋ยนาข้าว", "ปุ๋ยรองพื้นข้าวโพด")
- usage_instruction: วิธีใช้/อัตราใส่ปุ๋ย (เช่น "ใส่ปุ๋ยกี่กิโลต่อไร่", "46-0-0 ใส่ตอนไหน", "อัตราใส่ปุ๋ยมันสำปะหลัง")
- product_inquiry: ถามเกี่ยวกับสูตรปุ๋ยเฉพาะ (เช่น "สูตร 46-0-0 คืออะไร", "ปุ๋ย 15-15-15 ใช้กับอะไร")
- general_agriculture: คำถามเกษตรทั่วไป (เช่น "ดินเปรี้ยว แก้ยังไง", "ข้าวใบเหลือง")
- dealer_inquiry: ถามหาตัวแทนจำหน่าย/ร้านค้า/จุดขาย (เช่น "ใกล้อำเภอนี้มีไหม", "มีร้านที่จังหวัดลพบุรีไหม", "ร้านค้าใกล้ฉัน", "ซื้อที่ไหน")
- greeting: ทักทาย (เช่น "สวัสดี", "ดีจ้า")
- unknown: ไม่เกี่ยวกับเกษตรหรือปุ๋ย

required_sources:
- ใช้ ["mahbin_npk"] เสมอ (ข้อมูลปุ๋ยแนะนำเป็นแหล่งหลักเพียงแหล่งเดียว)

กฎสำคัญ:
- [CONSTRAINT] คือข้อมูลที่ระบบตรวจจับได้จากพจนานุกรม — ห้ามเปลี่ยนแปลง ต้องใส่ค่าตามที่ระบุเท่านั้น
- [HINT] คือคำแนะนำ — สามารถปรับได้ตามบริบท
- ถ้าคำถามมีคำว่า "ปุ๋ย", "สูตร", "ใส่อะไร", "ใส่ปุ๋ย", "แนะนำปุ๋ย" → ต้องเป็น fertilizer-related intent (ห้ามเป็น unknown)
- ถ้าคำถามพูดถึงระยะพืช (เช่น เร่งต้น, แตกกอ, รับรวง, รองพื้น, แต่งหน้า, บำรุงต้น, เร่งผลผลิต) → ใส่ใน growth_stage
- ถ้าคำถามมีสูตร X-X-X (เช่น 46-0-0, 16-20-0) → ใส่ใน fertilizer_formula
- ชื่อพืชในฐานข้อมูลคือ: {crops_str} — ถ้าผู้ใช้พูดถึงพืชเหล่านี้ ให้ใช้ชื่อตรงตามฐานข้อมูล (เช่น "ข้าว" → "นาข้าว", "ปาล์ม" → "ปาล์มน้ำมัน", "ยาง" → "ยางพารา", "มัน"/"มันสำ" → "มันสำปะหลัง")
- ห้ามสร้าง query ภาษาอังกฤษ (ฐานข้อมูลเป็นภาษาไทย)
- สร้างคำค้นหาภาษาไทยเท่านั้น
- รวมชื่อพืช + สูตรปุ๋ย + ระยะการใส่ ในรูปแบบต่างๆ

ตัวอย่าง:
1. "ปุ๋ยนาข้าว ใส่อะไรดี" → intent=fertilizer_recommendation, crop="นาข้าว", expanded_queries=["ปุ๋ยนาข้าว", "สูตรปุ๋ยนาข้าว", "ปุ๋ยแนะนำ นาข้าว"]
2. "สูตร 46-0-0 ใช้กับอะไร" → intent=product_inquiry, fertilizer_formula="46-0-0", expanded_queries=["ปุ๋ย 46-0-0", "สูตร 46-0-0 พืช", "46-0-0 วิธีใช้"]
3. "สวัสดีครับ" → intent=greeting, confidence=0.95
4. "ปุ๋ยข้าวโพด ช่วงเร่งต้น" → intent=fertilizer_recommendation, crop="ข้าวโพด", growth_stage="เร่งต้น", expanded_queries=["ปุ๋ยข้าวโพด เร่งต้น", "สูตรปุ๋ย ข้าวโพด รองพื้น", "ปุ๋ยข้าวโพด"]
5. "ใส่ปุ๋ยอ้อยกี่กิโลต่อไร่" → intent=usage_instruction, crop="อ้อย", expanded_queries=["อัตราใส่ปุ๋ย อ้อย", "ปุ๋ยอ้อย กิโลต่อไร่", "วิธีใส่ปุ๋ย อ้อย"]
6. "ปุ๋ยรองพื้นมันสำปะหลัง" → intent=fertilizer_recommendation, crop="มันสำปะหลัง", growth_stage="รองพื้น", expanded_queries=["ปุ๋ยรองพื้น มันสำปะหลัง", "สูตรปุ๋ย มันสำปะหลัง รองพื้น", "ปุ๋ยมันสำปะหลัง"]
7. "ปาล์มน้ำมัน ใส่ปุ๋ยตอนไหน" → intent=usage_instruction, crop="ปาล์มน้ำมัน", expanded_queries=["ช่วงใส่ปุ๋ย ปาล์มน้ำมัน", "ปุ๋ยปาล์มน้ำมัน ระยะใส่", "ปุ๋ยปาล์ม"]
8. "ยางพารา แนะนำสูตรปุ๋ย" → intent=fertilizer_recommendation, crop="ยางพารา", expanded_queries=["สูตรปุ๋ย ยางพารา", "ปุ๋ยยางพารา แนะนำ", "ปุ๋ยยางพารา"]
9. "16-20-0 ใส่ข้าวได้ไหม" → intent=product_inquiry, crop="นาข้าว", fertilizer_formula="16-20-0", expanded_queries=["ปุ๋ย 16-20-0 นาข้าว", "สูตร 16-20-0", "ปุ๋ยนาข้าว"]
10. "มีร้านที่จังหวัดลพบุรีไหม" → intent=dealer_inquiry, confidence=0.90
11. "ใกล้อำเภอคำพราน มีไหม" → intent=dealer_inquiry, confidence=0.85
"""

        response = await self.openai_client.chat.completions.create(
            model=LLM_MODEL_QUERY_UNDERSTANDING,
            messages=[
                {
                    "role": "system",
                    "content": "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์คำถามเกี่ยวกับปุ๋ยและการเกษตร ตอบเป็น JSON เท่านั้น ไม่มี markdown"
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_completion_tokens=500
        )

        response_text = response.choices[0].message.content.strip()

        # Parse JSON response
        try:
            # Remove markdown code blocks if present
            if response_text.startswith("```"):
                response_text = re.sub(r'^```(?:json)?\n?', '', response_text)
                response_text = re.sub(r'\n?```$', '', response_text)

            data = json.loads(response_text)

            # Map intent string to IntentType enum
            intent_map = {
                "fertilizer_recommendation": IntentType.FERTILIZER_RECOMMENDATION,
                "product_inquiry": IntentType.PRODUCT_INQUIRY,
                "product_recommendation": IntentType.PRODUCT_RECOMMENDATION,
                "usage_instruction": IntentType.USAGE_INSTRUCTION,
                "general_agriculture": IntentType.GENERAL_AGRICULTURE,
                "greeting": IntentType.GREETING,
                "dealer_inquiry": IntentType.DEALER_INQUIRY,
                "unknown": IntentType.UNKNOWN,
            }

            intent = intent_map.get(data.get("intent", "unknown"), IntentType.UNKNOWN)

            # Clean entities (remove null values)
            entities = {k: v for k, v in data.get("entities", {}).items() if v is not None}

            # Post-LLM override: pre-extracted entities take priority
            if hints.get('crop') and not entities.get('crop'):
                entities['crop'] = hints['crop']
            if hints.get('growth_stage') and not entities.get('growth_stage'):
                entities['growth_stage'] = hints['growth_stage']
            if hints.get('fertilizer_formula') and not entities.get('fertilizer_formula'):
                entities['fertilizer_formula'] = hints['fertilizer_formula']

            # Get expanded queries
            expanded_queries = data.get("expanded_queries", [query])
            if not expanded_queries:
                expanded_queries = [query]

            # Inject extra search terms from farmer slang resolution
            if hints.get('extra_search_terms'):
                crop = entities.get('crop', '')
                for term in hints['extra_search_terms']:
                    search_q = f"{term} {crop}".strip() if crop else term
                    if search_q not in expanded_queries:
                        expanded_queries.append(search_q)

            # Force mahbin_npk-only source
            required_sources = ["mahbin_npk"]

            return QueryAnalysis(
                original_query=query,
                intent=intent,
                confidence=float(data.get("confidence", 0.5)),
                entities=entities,
                expanded_queries=expanded_queries,
                required_sources=required_sources
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            return self._fallback_analysis(query)

    def _fallback_analysis(self, query: str) -> QueryAnalysis:
        """Fallback to keyword-based analysis when LLM is not available"""
        query_lower = query.lower()

        # Intent detection using keywords
        intent = IntentType.UNKNOWN
        confidence = 0.5
        entities = {}

        # Extract fertilizer formula (X-X-X pattern) first
        formula_match = FORMULA_PATTERN.search(query)
        if formula_match:
            entities["fertilizer_formula"] = formula_match.group(0)
            intent = IntentType.PRODUCT_INQUIRY
            confidence = 0.8

        # Fertilizer recommendation patterns
        fertilizer_rec_keywords = [
            "แนะนำปุ๋ย", "ใส่ปุ๋ยอะไร", "ใส่อะไรดี", "ปุ๋ยอะไรดี",
            "ใช้ปุ๋ยอะไร", "สูตรปุ๋ย", "เลือกปุ๋ย",
        ]
        if any(kw in query_lower for kw in fertilizer_rec_keywords):
            if intent == IntentType.UNKNOWN or intent == IntentType.PRODUCT_INQUIRY:
                intent = IntentType.FERTILIZER_RECOMMENDATION
                confidence = 0.8

        # General fertilizer keywords (if not already matched)
        if intent == IntentType.UNKNOWN:
            if any(kw in query_lower for kw in FERTILIZER_KEYWORDS):
                intent = IntentType.FERTILIZER_RECOMMENDATION
                confidence = 0.7

        # Usage instruction patterns
        usage_keywords = ["วิธีใส่", "อัตราใส่", "ใส่กี่กิโล", "ใส่เท่าไหร่", "ใส่ตอนไหน",
                          "วิธีใช้", "อัตรา", "กิโลต่อไร่", "ใช้ยังไง"]
        if any(kw in query_lower for kw in usage_keywords):
            if intent == IntentType.UNKNOWN:
                intent = IntentType.USAGE_INSTRUCTION
                confidence = 0.7

        # Greeting patterns
        greeting_keywords = ["สวัสดี", "ดีจ้า", "หวัดดี", "hello", "ดีครับ", "ดีค่ะ"]
        if any(kw in query_lower for kw in greeting_keywords):
            intent = IntentType.GREETING
            confidence = 0.9

        # Extract crop name
        crop_aliases = {
            "ข้าว": "นาข้าว",
            "นาข้าว": "นาข้าว",
            "ข้าวโพด": "ข้าวโพด",
            "อ้อย": "อ้อย",
            "มันสำปะหลัง": "มันสำปะหลัง",
            "มันสำ": "มันสำปะหลัง",
            "ปาล์มน้ำมัน": "ปาล์มน้ำมัน",
            "ปาล์ม": "ปาล์มน้ำมัน",
            "ยางพารา": "ยางพารา",
            "ยาง": "ยางพารา",
        }
        # Sort by length descending so longer aliases match first (e.g., "มันสำปะหลัง" before "มันสำ")
        for alias in sorted(crop_aliases.keys(), key=len, reverse=True):
            if alias in query_lower:
                entities["crop"] = crop_aliases[alias]
                break

        # Extract growth stage keywords
        growth_stage_keywords = [
            "เร่งต้น", "แตกกอ", "รับรวง", "รองพื้น", "แต่งหน้า",
            "บำรุงต้น", "เร่งผลผลิต", "เสริมผลผลิต", "ตั้งท้อง",
        ]
        for stage in growth_stage_keywords:
            if stage in query_lower:
                entities["growth_stage"] = stage
                break

        return QueryAnalysis(
            original_query=query,
            intent=intent,
            confidence=confidence,
            entities=entities,
            expanded_queries=[query],
            required_sources=self._determine_sources(intent)
        )

    def _determine_sources(self, intent: IntentType) -> List[str]:
        """Determine which data sources to query based on intent — mahbin_npk only"""
        if intent == IntentType.GREETING:
            return []
        return ["mahbin_npk"]
