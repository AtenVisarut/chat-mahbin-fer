"""
Agentic RAG Orchestrator

Main entry point for the 4-agent RAG pipeline:
1. QueryUnderstandingAgent - Semantic intent detection, entity extraction
2. RetrievalAgent - Multi-query retrieval with re-ranking
3. GroundingAgent - Citation extraction, hallucination detection
4. ResponseGeneratorAgent - Answer synthesis with confidence scoring

Usage:
    from app.services.rag.orchestrator import AgenticRAG

    rag = AgenticRAG()
    response = await rag.process("ปุ๋ยนาข้าว ช่วงเร่งต้น ใช้สูตรอะไร")
    print(response.answer)
    print(f"Confidence: {response.confidence}")
    print(f"Citations: {len(response.citations)}")
"""

import logging
import time
import re
import json
from typing import Optional

from app.dependencies import openai_client, supabase_client
from app.services.rag import (
    IntentType,
    QueryAnalysis,
    AgenticRAGResponse
)
from app.services.rag.query_understanding_agent import QueryUnderstandingAgent
from app.services.rag.retrieval_agent import RetrievalAgent
from app.services.rag.grounding_agent import GroundingAgent
from app.services.rag.response_generator_agent import ResponseGeneratorAgent
from app.config import AGENTIC_RAG_CONFIG, LLM_MODEL_ENTITY_EXTRACTION

logger = logging.getLogger(__name__)

# Pattern for fertilizer formula extraction (e.g. "46-0-0", "16-20-0")
_FORMULA_PATTERN = re.compile(r'\b(\d{1,2})\s*[-\u2013]\s*(\d{1,2})\s*[-\u2013]\s*(\d{1,2})\b')

# Known crop aliases for pre-detection
_CROP_ALIASES = {
    "ข้าว": "นาข้าว", "นาข้าว": "นาข้าว", "ทำนา": "นาข้าว", "นา": "นาข้าว",
    "ข้าวโพด": "ข้าวโพด", "โพด": "ข้าวโพด",
    "อ้อย": "อ้อย", "ไร่อ้อย": "อ้อย",
    "มันสำปะหลัง": "มันสำปะหลัง", "มันสำ": "มันสำปะหลัง", "ไร่มัน": "มันสำปะหลัง",
    "ปาล์มน้ำมัน": "ปาล์มน้ำมัน", "ปาล์ม": "ปาล์มน้ำมัน", "สวนปาล์ม": "ปาล์มน้ำมัน",
    "ยางพารา": "ยางพารา", "ยาง": "ยางพารา", "สวนยาง": "ยางพารา", "ต้นยาง": "ยางพารา",
}

# Growth stage keywords for pre-detection
_GROWTH_STAGE_KEYWORDS = [
    "เร่งต้น", "แตกกอ", "รับรวง", "รองพื้น", "แต่งหน้า",
    "บำรุงต้น", "เร่งผลผลิต", "เสริมผลผลิต", "ตั้งท้อง",
    "ย้ายปลูก", "งอก", "ระยะต้นอ่อน",
]


def _extract_crop_from_text(text: str) -> Optional[str]:
    """Extract crop name from text using alias dictionary (longest match first)."""
    text_lower = text.lower()
    for alias in sorted(_CROP_ALIASES.keys(), key=len, reverse=True):
        if alias in text_lower:
            return _CROP_ALIASES[alias]
    return None


def _extract_formula_from_text(text: str) -> Optional[str]:
    """Extract fertilizer formula pattern (X-X-X) from text."""
    m = _FORMULA_PATTERN.search(text)
    if m:
        n, p, k = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{n}-{p}-{k}"
    return None


def _extract_growth_stage_from_text(text: str) -> Optional[str]:
    """Extract growth stage keyword from text."""
    text_lower = text.lower()
    for stage in _GROWTH_STAGE_KEYWORDS:
        if stage in text_lower:
            return stage
    return None


async def _llm_entity_extraction(query: str, crop_list: list, openai_client_instance) -> dict:
    """
    LLM fallback: extract fertilizer-related entities when dictionary scan finds nothing.
    Returns dict with keys: crop, growth_stage, fertilizer_formula (all optional).
    """
    try:
        crops_str = ", ".join(crop_list)
        prompt = f"""จากคำถามเกษตรกรรมต่อไปนี้ ให้ดึง entity ที่เกี่ยวข้อง

คำถาม: "{query}"

พืชในฐานข้อมูล: [{crops_str}]

ตอบเป็น JSON เท่านั้น (ไม่มี markdown):
{{
    "crop": "<ชื่อพืชจากรายชื่อข้างบน ถ้ามี หรือ null>",
    "growth_stage": "<ระยะการเจริญเติบโต ถ้ามี หรือ null>",
    "fertilizer_formula": "<สูตรปุ๋ย X-X-X ถ้ามี หรือ null>"
}}

กฎ:
- crop ต้องเป็นชื่อจากรายชื่อข้างบนเท่านั้น ถ้าไม่มีให้ใส่ null
- ถ้าผู้ใช้พูดถึง "ข้าว" → "นาข้าว", "ปาล์ม" → "ปาล์มน้ำมัน", "ยาง" → "ยางพารา", "มัน" → "มันสำปะหลัง"
- ตอบ JSON เท่านั้น ห้ามมี text อื่น"""

        response = await openai_client_instance.chat.completions.create(
            model=LLM_MODEL_ENTITY_EXTRACTION,
            messages=[
                {"role": "system", "content": "คุณเป็นผู้เชี่ยวชาญด้านเกษตรและปุ๋ย ดึง entity จากคำถาม ตอบ JSON เท่านั้น"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_completion_tokens=200
        )

        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\n?', '', text)
            text = re.sub(r'\n?```$', '', text)

        data = json.loads(text)
        result = {k: v for k, v in data.items() if v is not None}
        logger.info(f"  - LLM entity extraction: {result}")
        return result

    except Exception as e:
        logger.warning(f"LLM entity extraction failed: {e}")
        return {}


class AgenticRAG:
    """
    Agentic RAG Pipeline Orchestrator

    Coordinates the 4-agent pipeline for fertilizer Q&A:
    Query -> Understanding -> Retrieval -> Grounding -> Response
    """

    def __init__(
        self,
        openai_client_instance=None,
        supabase_client_instance=None,
        config: dict = None
    ):
        self.openai_client = openai_client_instance or openai_client
        self.supabase_client = supabase_client_instance or supabase_client
        self.config = config or AGENTIC_RAG_CONFIG

        # Initialize agents
        self.query_agent = QueryUnderstandingAgent(
            openai_client=self.openai_client
        )
        self.retrieval_agent = RetrievalAgent(
            supabase_client=self.supabase_client,
            openai_client=self.openai_client,
            vector_threshold=self.config.get('VECTOR_THRESHOLD', 0.35),
            rerank_threshold=self.config.get('RERANK_THRESHOLD', 0.50)
        )
        self.grounding_agent = GroundingAgent(
            openai_client=self.openai_client
        )
        self.response_agent = ResponseGeneratorAgent(
            openai_client=self.openai_client
        )

        logger.info("AgenticRAG initialized with config: %s", self.config)

    async def process(
        self,
        query: str,
        context: str = "",
        user_id: str = None
    ) -> AgenticRAGResponse:
        """
        Process a user query through the 4-agent pipeline

        Args:
            query: User's question
            context: Optional conversation context
            user_id: Optional user ID for personalization

        Returns:
            AgenticRAGResponse with answer, citations, confidence, etc.
        """
        start_time = time.time()

        try:
            logger.info(f"AgenticRAG.process: '{query[:50]}...'")

            # =================================================================
            # Stage 0: Pre-detect hints using keyword/pattern extraction
            # =================================================================
            hints = {}
            try:
                # --- Pre-extract crop name ---
                detected_crop = _extract_crop_from_text(query)
                if detected_crop:
                    hints['crop'] = detected_crop
                    logger.info(f"  - Pre-extracted crop: '{detected_crop}'")

                # --- Pre-extract fertilizer formula ---
                detected_formula = _extract_formula_from_text(query)
                if detected_formula:
                    hints['fertilizer_formula'] = detected_formula
                    logger.info(f"  - Pre-extracted formula: '{detected_formula}'")

                # --- Pre-extract growth stage ---
                detected_stage = _extract_growth_stage_from_text(query)
                if detected_stage:
                    hints['growth_stage'] = detected_stage
                    logger.info(f"  - Pre-extracted growth stage: '{detected_stage}'")

                # --- Context-based crop/formula extraction for follow-up queries ---
                if not hints.get('crop') and not hints.get('fertilizer_formula') and context:
                    # Scan recent context for crop/formula mentioned by พี่ม้าบิน
                    context_lines = context.strip().split('\n')
                    for line in reversed(context_lines):
                        if line.startswith('[') and ']' in line:
                            continue
                        # Try to extract crop from context
                        if not hints.get('crop'):
                            ctx_crop = _extract_crop_from_text(line)
                            if ctx_crop:
                                hints['crop'] = ctx_crop
                                logger.info(f"  - Crop from context: '{ctx_crop}'")
                        # Try to extract formula from context
                        if not hints.get('fertilizer_formula'):
                            ctx_formula = _extract_formula_from_text(line)
                            if ctx_formula:
                                hints['fertilizer_formula'] = ctx_formula
                                logger.info(f"  - Formula from context: '{ctx_formula}'")
                        # Stop after finding both or reaching a role prefix
                        if hints.get('crop') and hints.get('fertilizer_formula'):
                            break
                        if line.startswith("ผู้ใช้:") or line.startswith("พี่ม้าบิน:"):
                            break

                # --- LLM Fallback Entity Extraction ---
                _has_any_entity = hints.get('crop') or hints.get('fertilizer_formula')
                if not _has_any_entity and len(query.strip()) >= 10:
                    from app.services.product.registry import ProductRegistry
                    registry = ProductRegistry.get_instance()
                    crop_list = registry.get_crops() if registry.loaded else list(_CROP_ALIASES.values())
                    crop_list = sorted(set(crop_list))

                    llm_entities = await _llm_entity_extraction(
                        query, crop_list, self.openai_client
                    )
                    if llm_entities:
                        for key in ('crop', 'growth_stage', 'fertilizer_formula'):
                            if llm_entities.get(key) and not hints.get(key):
                                hints[key] = llm_entities[key]
                        logger.info(f"  - LLM fallback entities applied: {llm_entities}")

                logger.info(f"  - Hints: {hints}")
            except Exception as e:
                logger.warning(f"Stage 0 hint extraction error: {e}")

            # =================================================================
            # Stage 1: Query Understanding
            # =================================================================
            query_analysis = await self.query_agent.analyze(query, context=context, hints=hints)

            # Handle greeting intent directly
            if query_analysis.intent == IntentType.GREETING:
                response = await self.response_agent.generate(
                    query_analysis=query_analysis,
                    retrieval_result=None,
                    grounding_result=None
                )
                response.processing_time_ms = (time.time() - start_time) * 1000
                return response

            # Handle dealer inquiry — short-circuit, let handler do dealer lookup
            if query_analysis.intent == IntentType.DEALER_INQUIRY:
                logger.info("DEALER_INQUIRY detected, returning to handler for dealer lookup")
                return AgenticRAGResponse(
                    answer=None,
                    confidence=query_analysis.confidence,
                    citations=[],
                    intent=query_analysis.intent,
                    is_grounded=False,
                    sources_used=[],
                    query_analysis=query_analysis,
                    processing_time_ms=(time.time() - start_time) * 1000
                )

            # Handle unknown intent with low confidence
            fertilizer_keywords = ["ปุ๋ย", "สูตร", "ใส่", "ธาตุอาหาร", "บำรุง", "อัตรา", "กิโล", "ไร่"]
            has_fertilizer_keywords = any(kw in query for kw in fertilizer_keywords)
            if query_analysis.intent == IntentType.UNKNOWN and query_analysis.confidence < 0.3 and not has_fertilizer_keywords:
                logger.info("Low confidence unknown intent, routing to general chat")
                return AgenticRAGResponse(
                    answer=None,  # Signal to use general chat
                    confidence=query_analysis.confidence,
                    citations=[],
                    intent=query_analysis.intent,
                    is_grounded=False,
                    sources_used=[],
                    query_analysis=query_analysis,
                    processing_time_ms=(time.time() - start_time) * 1000
                )
            elif query_analysis.intent == IntentType.UNKNOWN and has_fertilizer_keywords:
                logger.info("Unknown intent but has fertilizer keywords, forcing retrieval")
                query_analysis.required_sources = ["mahbin_npk"]

            # =================================================================
            # Stage 2: Retrieval
            # =================================================================
            retrieval_result = await self.retrieval_agent.retrieve(
                query_analysis=query_analysis,
                top_k=self.config.get('RETRIEVAL_TOP_K', 10)
            )

            # =================================================================
            # Stage 3: Grounding
            # =================================================================
            if self.config.get('ENABLE_GROUNDING', True):
                grounding_result = await self.grounding_agent.ground(
                    query_analysis=query_analysis,
                    retrieval_result=retrieval_result
                )
            else:
                from app.services.rag import GroundingResult
                grounding_result = GroundingResult(
                    is_grounded=bool(retrieval_result.documents),
                    confidence=retrieval_result.avg_similarity,
                    citations=[],
                    ungrounded_claims=[],
                    suggested_answer=""
                )

            # =================================================================
            # Stage 4: Response Generation
            # =================================================================
            response = await self.response_agent.generate(
                query_analysis=query_analysis,
                retrieval_result=retrieval_result,
                grounding_result=grounding_result,
                context=context
            )

            response.processing_time_ms = (time.time() - start_time) * 1000
            logger.info(f"AgenticRAG completed in {response.processing_time_ms:.0f}ms")
            logger.info(f"  - Answer length: {len(response.answer) if response.answer else 0}")
            logger.info(f"  - Confidence: {response.confidence:.2f}")
            logger.info(f"  - Grounded: {response.is_grounded}")

            return response

        except Exception as e:
            logger.error(f"AgenticRAG.process error: {e}", exc_info=True)
            return AgenticRAGResponse(
                answer="ขออภัยครับ เกิดข้อผิดพลาดในการประมวลผล กรุณาลองใหม่อีกครั้งนะครับ",
                confidence=0.0,
                citations=[],
                intent=IntentType.UNKNOWN,
                is_grounded=False,
                sources_used=[],
                processing_time_ms=(time.time() - start_time) * 1000
            )

    async def process_simple(self, query: str) -> str:
        """Simple interface that returns just the answer string"""
        response = await self.process(query)
        return response.answer


# Global singleton instance
_agentic_rag_instance: Optional[AgenticRAG] = None


def get_agentic_rag() -> AgenticRAG:
    """Get or create the global AgenticRAG instance"""
    global _agentic_rag_instance
    if _agentic_rag_instance is None:
        _agentic_rag_instance = AgenticRAG()
    return _agentic_rag_instance


async def process_with_agentic_rag(query: str, context: str = "") -> AgenticRAGResponse:
    """Convenience function to process a query with the global AgenticRAG instance"""
    rag = get_agentic_rag()
    return await rag.process(query, context)
