"""
Response Generator Agent (Fertilizer version)

Responsibilities:
- Synthesize final answer from grounded/verified fertilizer data
- Generate formatted response using LLM with "พี่ม้าบิน" persona
- Format citations for readability
- Add confidence indicators when needed
- Handle fallback responses when no data found
"""

import logging
import json

from app.services.rag import (
    QueryAnalysis,
    RetrievalResult,
    GroundingResult,
    AgenticRAGResponse,
    IntentType
)
from app.utils.text_processing import post_process_answer
from app.config import LLM_MODEL_RESPONSE_GEN
from app.prompts import (
    PRODUCT_QA_PROMPT,
    GREETINGS,
    PRODUCT_CTA,
    ERROR_PROCESSING,
    ERROR_NO_DATA,
    LOW_CONFIDENCE_NOTE,
    get_no_data_response,
)

logger = logging.getLogger(__name__)

# Configuration
LOW_CONFIDENCE_THRESHOLD = 0.5


class ResponseGeneratorAgent:
    """
    Agent 4: Response Generation
    Creates the final user-facing response using LLM with verified fertilizer data
    """

    def __init__(self, openai_client=None):
        self.openai_client = openai_client

    async def generate(
        self,
        query_analysis: QueryAnalysis,
        retrieval_result: RetrievalResult,
        grounding_result: GroundingResult,
        context: str = ""
    ) -> AgenticRAGResponse:
        """
        Generate final response from pipeline results using LLM

        Returns:
            AgenticRAGResponse with answer, citations, and metadata
        """
        try:
            logger.info(f"ResponseGeneratorAgent: Generating response")
            logger.info(f"  - Grounded: {grounding_result.is_grounded}")
            logger.info(f"  - Confidence: {grounding_result.confidence:.2f}")

            # Handle special intents
            if query_analysis.intent == IntentType.GREETING:
                return self._generate_greeting_response(query_analysis)

            # Track final confidence/grounded
            final_confidence = grounding_result.confidence
            final_grounded = grounding_result.is_grounded

            # Handle no data case
            if not grounding_result.is_grounded:
                has_documents = bool(retrieval_result.documents)

                # Check if crop query matched
                has_crop_match = False
                crop = query_analysis.entities.get('crop', query_analysis.entities.get('plant_type', ''))
                if crop and has_documents:
                    for doc in retrieval_result.documents[:5]:
                        doc_crop = str(doc.metadata.get('crop', '')).lower()
                        if crop.lower() in doc_crop or doc_crop in crop.lower():
                            has_crop_match = True
                            logger.info(f"  - Crop match override: '{crop}' found in {doc.title}")
                            break

                if not has_documents or (
                    grounding_result.confidence < 0.2
                    and not has_crop_match
                ):
                    return self._generate_no_data_response(query_analysis)

                # Override confidence when crop matched
                if has_crop_match:
                    final_confidence = max(final_confidence, 0.65)
                    final_grounded = True
                    logger.info(f"  - Confidence override: crop match → {final_confidence:.2f}")

            # Generate answer from verified data using LLM
            answer = await self._generate_llm_response(
                query_analysis, retrieval_result, grounding_result, context
            )

            # Post-process answer (remove markdown artifacts)
            answer = post_process_answer(answer)

            # Add low confidence indicator if needed
            if final_confidence < LOW_CONFIDENCE_THRESHOLD:
                answer = self._add_low_confidence_note(answer)

            return AgenticRAGResponse(
                answer=answer,
                confidence=final_confidence,
                citations=grounding_result.citations,
                intent=query_analysis.intent,
                is_grounded=final_grounded,
                sources_used=retrieval_result.sources_used,
                query_analysis=query_analysis,
                retrieval_result=retrieval_result,
                grounding_result=grounding_result
            )

        except Exception as e:
            logger.error(f"ResponseGeneratorAgent error: {e}", exc_info=True)
            return AgenticRAGResponse(
                answer=ERROR_PROCESSING,
                confidence=0.0,
                citations=[],
                intent=query_analysis.intent,
                is_grounded=False,
                sources_used=[]
            )

    async def _generate_llm_response(
        self,
        query_analysis: QueryAnalysis,
        retrieval_result: RetrievalResult,
        grounding_result: GroundingResult,
        context: str = ""
    ) -> str:
        """Generate formatted response using LLM with verified fertilizer data"""

        if not self.openai_client:
            return self._build_fallback_answer(retrieval_result, grounding_result)

        # Use top 5 documents
        docs_to_use = retrieval_result.documents[:5]

        # Build fertilizer data context from retrieval results
        product_context_parts = []
        for i, doc in enumerate(docs_to_use, 1):
            meta = doc.metadata
            part = f"[ปุ๋ย {i}] สูตร {meta.get('fertilizer_formula', doc.title)}"
            if meta.get('primary_nutrients'):
                part += f" (ธาตุอาหารหลัก: {meta['primary_nutrients']})"
            part += "\n"
            if meta.get('crop'):
                part += f"  พืช: {meta['crop']}\n"
            if meta.get('growth_stage'):
                part += f"  ระยะ: {meta['growth_stage']}\n"
            if meta.get('usage_rate'):
                part += f"  อัตราใช้: {meta['usage_rate']}\n"
            if meta.get('benefits'):
                part += f"  ประโยชน์: {str(meta['benefits'])}\n"
            product_context_parts.append(part)

        product_context = "\n".join(product_context_parts)

        # Relevant products from grounding
        relevant = list(grounding_result.relevant_products)
        relevant_str = ", ".join(relevant) if relevant else "(ทั้งหมดที่ค้นพบ)"

        # Build context section for follow-up questions
        context_section = ""
        if context:
            context_section = f"""บริบทการสนทนาก่อนหน้า:
{context[:1500]}

สำคัญมาก:
1. ถ้าผู้ใช้ถามต่อเนื่อง (เช่น "ใส่กี่กก" "ใช้ช่วงไหน") ต้องตอบเกี่ยวกับสูตรปุ๋ยตัวเดิม
2. ถ้าผู้ใช้เปลี่ยนพืชหรือระยะ ให้ค้นหาสูตรใหม่

"""

        prompt = f"""{context_section}คำถาม: "{query_analysis.original_query}"
Intent: {query_analysis.intent.value}
Entities: {json.dumps(query_analysis.entities, ensure_ascii=False)}

ข้อมูลสินค้าที่ผ่านการตรวจสอบแล้ว:
{product_context}

สินค้าที่เกี่ยวข้องกับคำถาม: [{relevant_str}]

สร้างคำตอบจากข้อมูลด้านบน

สำคัญมาก — ตรวจสอบ Entities ก่อนตอบ:
- ถ้า Entities มีชนิดพืชหรือระยะอยู่แล้ว (หรือคำถามระบุพืช/อายุ/ระยะ) → ตอบเลย ห้ามถามซ้ำ
- ถ้าผู้ใช้ไม่ได้บอกชนิดพืชและระยะเลย (ทั้งสองอย่าง) → ถามสั้นๆ ว่า "ปลูกพืชอะไร อายุประมาณกี่วันครับ?"

ถ้าผู้ใช้ถามปริมาณการใช้สำหรับพื้นที่ (เช่น 10 ไร่, 20 ไร่) ให้คำนวณจากอัตราใช้ต่อไร่

[ห้ามมั่วข้อมูลเด็ดขาด]
- ตอบเฉพาะข้อมูลที่ปรากฏในข้อมูลสินค้าด้านบน ห้ามแต่งเอง
- ห้ามเดาตัวเลขอัตราการใช้ น้ำหนัก ราคา
- ถ้าข้อมูลที่ถามไม่มีในข้อมูลด้านบน ให้ตอบว่า "ขออภัยครับ ไม่มีข้อมูลส่วนนี้ในระบบ"
- ห้ามใช้ความรู้ทั่วไปมาตอบแทนข้อมูลจริง"""

        system_prompt = PRODUCT_QA_PROMPT

        try:
            response = await self.openai_client.chat.completions.create(
                model=LLM_MODEL_RESPONSE_GEN,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=700
            )
            answer = response.choices[0].message.content.strip()
            return answer
        except Exception as e:
            logger.error(f"LLM response generation failed: {e}")
            return self._build_fallback_answer(retrieval_result, grounding_result)

    def _build_fallback_answer(
        self,
        retrieval_result: RetrievalResult,
        grounding_result: GroundingResult
    ) -> str:
        """Build answer without LLM from raw fertilizer data"""
        if not retrieval_result.documents:
            return ERROR_NO_DATA

        parts = ["จากข้อมูลในระบบ:\n"]
        for i, doc in enumerate(retrieval_result.documents[:3], 1):
            meta = doc.metadata
            formula = meta.get('fertilizer_formula') or doc.title
            nutrients = meta.get('primary_nutrients', '')
            if nutrients:
                formula = f"{formula} ({nutrients})"
            parts.append(f"{i}. สูตร {formula}")
            if meta.get('crop'):
                parts.append(f"   - พืช: {meta['crop']}")
            if meta.get('growth_stage'):
                parts.append(f"   - ระยะ: {meta['growth_stage']}")
            if meta.get('usage_rate'):
                parts.append(f"   - อัตราใช้: {meta['usage_rate']}")
            if meta.get('benefits'):
                parts.append(f"   - ประโยชน์: {str(meta['benefits'])[:100]}")
            parts.append("")

        parts.append(f"\n{PRODUCT_CTA}")
        return "\n".join(parts)

    def _generate_greeting_response(self, query_analysis: QueryAnalysis) -> AgenticRAGResponse:
        """Generate response for greeting intent"""
        import random
        answer = random.choice(GREETINGS)

        return AgenticRAGResponse(
            answer=answer,
            confidence=1.0,
            citations=[],
            intent=IntentType.GREETING,
            is_grounded=True,
            sources_used=[]
        )

    def _generate_no_data_response(self, query_analysis: QueryAnalysis) -> AgenticRAGResponse:
        """Generate response when no relevant data found"""
        answer = get_no_data_response(
            query_analysis.intent.value,
            query_analysis.entities
        )

        return AgenticRAGResponse(
            answer=answer,
            confidence=0.0,
            citations=[],
            intent=query_analysis.intent,
            is_grounded=False,
            sources_used=[]
        )

    def _add_low_confidence_note(self, answer: str) -> str:
        """Add note when confidence is low"""
        note = f"\n\n{LOW_CONFIDENCE_NOTE}"
        if note not in answer:
            answer += note
        return answer
