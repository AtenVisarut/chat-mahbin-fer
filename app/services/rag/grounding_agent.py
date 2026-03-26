"""
Grounding Agent (Fertilizer version)

Responsibilities:
- Verify that answer is grounded in retrieved documents
- Extract citations from documents
- Detect hallucinated/ungrounded claims
- Generate grounded answer when needed
"""

import logging
import json
import re
from typing import List, Dict

from app.services.rag import (
    RetrievedDocument,
    RetrievalResult,
    Citation,
    GroundingResult,
    QueryAnalysis,
    IntentType
)
from app.prompts import (
    GROUNDING_SYSTEM_PROMPT,
    PRODUCT_CTA,
    ERROR_NO_RELEVANT_DOCS,
    ERROR_GROUNDING_FAILED,
    ERROR_NO_DATA,
)
from app.config import LLM_MODEL_GROUNDING

logger = logging.getLogger(__name__)

# Configuration
MIN_GROUNDING_CONFIDENCE = 0.5
MAX_CITATIONS = 3


class GroundingAgent:
    """
    Agent 3: Grounding
    Ensures answers are grounded in retrieved knowledge
    """

    def __init__(self, openai_client=None):
        self.openai_client = openai_client

    async def ground(
        self,
        query_analysis: QueryAnalysis,
        retrieval_result: RetrievalResult,
        draft_answer: str = None
    ) -> GroundingResult:
        """
        Ground the answer in retrieved documents

        If draft_answer is provided, verify it against documents.
        Otherwise, generate a grounded answer from documents.

        Returns:
            GroundingResult with citations and grounding status
        """
        try:
            logger.info(f"GroundingAgent: Processing {len(retrieval_result.documents)} documents")

            # If no documents, cannot ground
            if not retrieval_result.documents:
                return GroundingResult(
                    is_grounded=False,
                    confidence=0.0,
                    citations=[],
                    ungrounded_claims=["ไม่พบข้อมูลในฐานข้อมูล"],
                    suggested_answer=ERROR_NO_RELEVANT_DOCS,
                    grounding_notes="No documents retrieved"
                )

            # Extract key information from documents
            doc_summaries = self._extract_document_info(retrieval_result.documents)

            # Generate grounded answer using LLM
            if self.openai_client:
                result = await self._llm_ground(
                    query_analysis,
                    retrieval_result.documents,
                    doc_summaries,
                    draft_answer
                )
                return result
            else:
                # Fallback: use documents directly
                return self._fallback_ground(retrieval_result.documents, query_analysis)

        except Exception as e:
            logger.error(f"GroundingAgent error: {e}", exc_info=True)
            return GroundingResult(
                is_grounded=False,
                confidence=0.0,
                citations=[],
                ungrounded_claims=[str(e)],
                suggested_answer=ERROR_GROUNDING_FAILED,
                grounding_notes=f"Error: {str(e)}"
            )

    def _extract_document_info(self, docs: List[RetrievedDocument]) -> List[Dict]:
        """Extract key information from documents for grounding"""
        summaries = []
        for doc in docs[:10]:  # Limit to top 10
            summary = {
                'id': doc.id,
                'title': doc.title,
                'source': doc.source,
                'content': doc.content[:300],
                'crop': doc.metadata.get('crop'),
                'growth_stage': doc.metadata.get('growth_stage'),
                'fertilizer_formula': doc.metadata.get('fertilizer_formula'),
                'usage_rate': doc.metadata.get('usage_rate'),
                'primary_nutrients': doc.metadata.get('primary_nutrients'),
                'benefits': doc.metadata.get('benefits'),
            }
            summaries.append(summary)
        return summaries

    async def _llm_ground(
        self,
        query_analysis: QueryAnalysis,
        docs: List[RetrievedDocument],
        doc_summaries: List[Dict],
        draft_answer: str = None
    ) -> GroundingResult:
        """Use LLM to verify retrieved documents are relevant (verify-only, no answer generation)"""

        # Build context from documents
        context_parts = []
        for i, summary in enumerate(doc_summaries, 1):
            part = f"[เอกสาร {i}]\n"
            part += f"หัวข้อ: {summary['title']}\n"
            if summary.get('crop'):
                part += f"พืช: {summary['crop']}\n"
            if summary.get('growth_stage'):
                part += f"ระยะ: {summary['growth_stage']}\n"
            if summary.get('fertilizer_formula'):
                part += f"สูตรปุ๋ย: {summary['fertilizer_formula']}\n"
            if summary.get('primary_nutrients'):
                part += f"ธาตุอาหารหลัก: {summary['primary_nutrients']}\n"
            if summary.get('usage_rate'):
                part += f"อัตราใช้: {summary['usage_rate']}\n"
            if summary.get('benefits'):
                part += f"ประโยชน์: {str(summary['benefits'])[:150]}\n"
            if summary.get('content'):
                part += f"เนื้อหา: {summary['content']}\n"
            context_parts.append(part)

        context = "\n".join(context_parts)

        # Build allowed products list
        allowed_products = []
        for summary in doc_summaries:
            if summary.get('fertilizer_formula'):
                allowed_products.append(summary['fertilizer_formula'])
        allowed_products_str = ", ".join(set(allowed_products)) if allowed_products else "(ไม่มี)"

        prompt = f"""ตรวจสอบว่าเอกสารที่ค้นได้มีข้อมูลเพียงพอที่จะตอบคำถามได้หรือไม่

คำถาม: "{query_analysis.original_query}"
Intent: {query_analysis.intent.value}
Entities: {json.dumps(query_analysis.entities, ensure_ascii=False)}

ข้อมูลจากฐานข้อมูล:
{context}

สูตรปุ๋ยที่พบ: [{allowed_products_str}]

ตอบเป็น JSON (ไม่มี markdown):
{{
    "is_grounded": true/false,
    "confidence": 0.0-1.0,
    "relevant_products": ["สูตรปุ๋ยที่เกี่ยวข้องกับคำถาม"],
    "available_fields": ["field ที่มีข้อมูล เช่น usage_rate, benefits, growth_stage"],
    "missing_info": ["ข้อมูลที่ขาดหาย"],
    "citations": [
        {{"doc_id": "X", "title": "...", "quoted_text": "ข้อความอ้างอิง"}}
    ]
}}

กฎ:
1. is_grounded=true ถ้ามีสูตรปุ๋ยอย่างน้อย 1 สูตรที่เกี่ยวข้องกับคำถาม
2. relevant_products ต้องมีเฉพาะสูตรปุ๋ยที่ตรงกับพืชและระยะที่ถาม
3. ถ้าถามเฉพาะพืช X แต่ไม่พบข้อมูลสำหรับ X → is_grounded=false
4. confidence สูง (>0.8) ถ้าพืชและระยะตรงเป๊ะ
5. ถ้ามีหลายสูตรสำหรับพืชเดียวกัน ทุกสูตรที่ตรงระยะถือว่าเกี่ยวข้อง"""

        response = await self.openai_client.chat.completions.create(
            model=LLM_MODEL_GROUNDING,
            messages=[
                {
                    "role": "system",
                    "content": GROUNDING_SYSTEM_PROMPT
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=500
        )

        response_text = response.choices[0].message.content.strip()

        try:
            # Remove markdown if present
            if response_text.startswith("```"):
                response_text = re.sub(r'^```(?:json)?\n?', '', response_text)
                response_text = re.sub(r'\n?```$', '', response_text)

            data = json.loads(response_text)

            # Build citations
            citations = []
            for cit in data.get("citations", [])[:MAX_CITATIONS]:
                citations.append(Citation(
                    doc_id=str(cit.get("doc_id", "")),
                    doc_title=cit.get("title", ""),
                    source="mahbin_npk",
                    quoted_text=cit.get("quoted_text", ""),
                    confidence=data.get("confidence", 0.5)
                ))

            relevant_products = data.get("relevant_products", list(set(allowed_products)))

            return GroundingResult(
                is_grounded=data.get("is_grounded", False),
                confidence=float(data.get("confidence", 0.5)),
                citations=citations,
                ungrounded_claims=data.get("missing_info", []),
                suggested_answer="",  # No longer generating answer here
                grounding_notes=f"LLM grounding with {len(doc_summaries)} docs, available_fields={data.get('available_fields', [])}",
                relevant_products=relevant_products
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse grounding response: {e}")
            return self._fallback_ground(docs, query_analysis)

    def _fallback_ground(
        self,
        docs: List[RetrievedDocument],
        query_analysis: QueryAnalysis
    ) -> GroundingResult:
        """Fallback grounding without LLM"""
        if not docs:
            return GroundingResult(
                is_grounded=False,
                confidence=0.0,
                citations=[],
                ungrounded_claims=["ไม่พบข้อมูล"],
                suggested_answer=ERROR_NO_DATA,
                grounding_notes="Fallback: no documents"
            )

        # Build answer from top documents
        answer_parts = ["จากข้อมูลในระบบ:\n"]

        for i, doc in enumerate(docs[:3], 1):
            formula = doc.metadata.get('fertilizer_formula') or doc.title
            crop = doc.metadata.get('crop', '')
            growth_stage = doc.metadata.get('growth_stage', '')
            nutrients = doc.metadata.get('primary_nutrients', '')

            display = f"{formula}"
            if nutrients:
                display = f"{formula} ({nutrients})"

            answer_parts.append(f"{i}. {display}")
            if crop:
                answer_parts.append(f"   - พืช: {crop}")
            if growth_stage:
                answer_parts.append(f"   - ระยะ: {growth_stage}")
            if doc.metadata.get('usage_rate'):
                answer_parts.append(f"   - อัตราใช้: {doc.metadata['usage_rate']}")
            answer_parts.append("")

        answer_parts.append(f"\n{PRODUCT_CTA}")

        # Build citations
        citations = []
        for doc in docs[:MAX_CITATIONS]:
            citations.append(Citation(
                doc_id=doc.id,
                doc_title=doc.title,
                source=doc.source,
                quoted_text=doc.content[:100],
                confidence=doc.similarity_score
            ))

        avg_score = sum(d.similarity_score for d in docs[:3]) / min(3, len(docs))

        return GroundingResult(
            is_grounded=avg_score >= MIN_GROUNDING_CONFIDENCE,
            confidence=avg_score,
            citations=citations,
            ungrounded_claims=[],
            suggested_answer="\n".join(answer_parts),
            grounding_notes="Fallback grounding"
        )
