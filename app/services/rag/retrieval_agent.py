"""
Retrieval Agent (Fertilizer Recommendation)

Responsibilities:
- Multi-query retrieval from mahbin_npk table
- De-duplication of results
- Re-ranking with LLM cross-encoder
- Relevance filtering based on threshold
"""

import logging
import asyncio
import re
import hashlib
import time
from typing import List, Dict

from app.services.rag import (
    QueryAnalysis,
    RetrievedDocument,
    RetrievalResult,
    IntentType
)
from app.config import LLM_MODEL_RERANKING, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_VECTOR_THRESHOLD = 0.25
DEFAULT_RERANK_THRESHOLD = 0.50
DEFAULT_TOP_K = 10
MIN_RELEVANT_DOCS = 3

# ============================================================================
# Embedding LRU Cache — avoids re-computing identical embeddings
# ============================================================================
_EMBEDDING_CACHE_MAX = 500
_EMBEDDING_CACHE_TTL = 3600  # 1 hour
_embedding_cache: Dict[str, dict] = {}  # key -> {"embedding": [...], "ts": float}


def _get_cached_embedding(text: str):
    """Return cached embedding list or None"""
    key = hashlib.md5(text.encode()).hexdigest()
    entry = _embedding_cache.get(key)
    if entry and (time.time() - entry["ts"]) < _EMBEDDING_CACHE_TTL:
        return entry["embedding"]
    return None


def _set_cached_embedding(text: str, embedding: list):
    """Store embedding in cache, evict oldest if full"""
    key = hashlib.md5(text.encode()).hexdigest()
    if len(_embedding_cache) >= _EMBEDDING_CACHE_MAX:
        # Evict oldest 10%
        sorted_keys = sorted(_embedding_cache, key=lambda k: _embedding_cache[k]["ts"])
        for k in sorted_keys[:max(1, len(sorted_keys) // 10)]:
            del _embedding_cache[k]
    _embedding_cache[key] = {"embedding": embedding, "ts": time.time()}


class RetrievalAgent:
    """
    Agent 2: Retrieval
    Performs multi-query retrieval with re-ranking for fertilizer recommendations.
    Data source: mahbin_npk table (19 rows, 6 crops).
    """

    def __init__(
        self,
        supabase_client=None,
        openai_client=None,
        vector_threshold: float = DEFAULT_VECTOR_THRESHOLD,
        rerank_threshold: float = DEFAULT_RERANK_THRESHOLD
    ):
        self.supabase = supabase_client
        self.openai_client = openai_client
        self.vector_threshold = vector_threshold
        self.rerank_threshold = rerank_threshold

    @staticmethod
    def _build_doc_from_row(item: dict, similarity: float, content_extra: str = "") -> 'RetrievedDocument':
        """Build a RetrievedDocument from a mahbin_npk DB row dict."""
        crop = item.get('crop', '')
        growth_stage = item.get('growth_stage', '')
        fertilizer_formula = item.get('fertilizer_formula', '')
        primary_nutrients = item.get('primary_nutrients', '')
        usage_rate = item.get('usage_rate', '')
        benefits = item.get('benefits', '')

        content = (
            f"พืช: {crop}\n"
            f"ระยะ: {growth_stage}\n"
            f"สูตรปุ๋ย: {fertilizer_formula}\n"
            f"ธาตุอาหารหลัก: {primary_nutrients}\n"
            f"อัตราใช้: {usage_rate}\n"
            f"ประโยชน์: {benefits}"
        )
        if content_extra:
            content += f"\n{content_extra}"

        # Title: combine crop + growth_stage + formula for display
        title = f"{crop} - {growth_stage} - {fertilizer_formula}" if growth_stage else f"{crop} - {fertilizer_formula}"

        return RetrievedDocument(
            id=str(item.get('id', '')),
            title=title,
            content=content,
            source="mahbin_npk",
            similarity_score=similarity,
            metadata={
                'crop': crop,
                'growth_stage': growth_stage,
                'fertilizer_formula': fertilizer_formula,
                'usage_rate': usage_rate,
                'primary_nutrients': primary_nutrients,
                'benefits': benefits,
            }
        )

    async def _direct_product_lookup(self, query_analysis: QueryAnalysis) -> List[RetrievedDocument]:
        """Direct database lookup by crop name or fertilizer formula (exact/ilike match)."""
        if not self.supabase:
            return []

        try:
            docs = []

            # Try lookup by crop name
            crop = query_analysis.entities.get('crop') or query_analysis.entities.get('plant_type') or ''
            growth_stage = query_analysis.entities.get('growth_stage', '')
            formula = query_analysis.entities.get('fertilizer_formula', '')

            if crop:
                query_builder = self.supabase.table('mahbin_npk') \
                    .select('*') \
                    .ilike('crop', f'%{crop}%')
                if growth_stage:
                    query_builder = query_builder.ilike('growth_stage', f'%{growth_stage}%')
                result = query_builder.limit(10).execute()

                if result.data:
                    for item in result.data:
                        doc = self._build_doc_from_row(item, similarity=1.0)
                        doc.rerank_score = 1.0
                        docs.append(doc)

            # Also try lookup by fertilizer formula if provided
            if formula and not docs:
                result = self.supabase.table('mahbin_npk') \
                    .select('*') \
                    .ilike('fertilizer_formula', f'%{formula}%') \
                    .limit(10) \
                    .execute()

                if result.data:
                    for item in result.data:
                        doc = self._build_doc_from_row(item, similarity=1.0)
                        doc.rerank_score = 1.0
                        docs.append(doc)

            if docs:
                logger.info(f"    Direct lookup: {len(docs)} docs for crop='{crop}' stage='{growth_stage}' formula='{formula}'")
            return docs

        except Exception as e:
            logger.error(f"Direct lookup error: {e}")
            return []

    async def _fallback_keyword_search(self, query: str, top_k: int = 5) -> List[RetrievedDocument]:
        """Fallback keyword search when vector search returns no results."""
        if not self.supabase:
            return []

        try:
            # Extract potential keywords from query
            keywords = re.findall(r'[\u0E00-\u0E7F]+|[a-zA-Z]+|\d+-\d+-\d+', query)
            keywords = [kw for kw in keywords if len(kw) >= 2]

            if not keywords:
                return []

            # Build OR filter for ilike search across fertilizer-relevant columns
            or_conditions = []
            for kw in keywords[:4]:  # Limit to 4 keywords
                or_conditions.append(f"crop.ilike.%{kw}%")
                or_conditions.append(f"growth_stage.ilike.%{kw}%")
                or_conditions.append(f"fertilizer_formula.ilike.%{kw}%")
                or_conditions.append(f"benefits.ilike.%{kw}%")

            or_filter = ",".join(or_conditions)

            result = self.supabase.table('mahbin_npk') \
                .select('*') \
                .or_(or_filter) \
                .limit(top_k) \
                .execute()

            if not result.data:
                return []

            docs = [self._build_doc_from_row(item, similarity=0.5) for item in result.data]

            logger.info(f"    Fallback keyword search: {len(docs)} docs for '{query[:30]}...'")
            return docs

        except Exception as e:
            logger.error(f"Fallback keyword search error: {e}")
            return []

    async def retrieve(
        self,
        query_analysis: QueryAnalysis,
        top_k: int = DEFAULT_TOP_K
    ) -> RetrievalResult:
        """
        Perform retrieval based on query analysis.

        Stages:
        1. Direct lookup by crop/formula
        2. Multi-source retrieval (vector search via RPC)
        3. Fallback keyword search if no results
        4. De-duplication
        5. Re-ranking (crop + growth_stage match quality)
        6. Relevance filtering

        Returns:
            RetrievalResult with ranked documents
        """
        try:
            logger.info(f"RetrievalAgent: Starting retrieval for '{query_analysis.original_query[:50]}...'")
            logger.info(f"  - Intent: {query_analysis.intent}")
            logger.info(f"  - Sources: {query_analysis.required_sources}")
            logger.info(f"  - Expanded queries: {len(query_analysis.expanded_queries)}")

            # Stage 1: Direct lookup by crop/formula
            all_docs = []
            direct_lookup_ids = set()
            direct_docs = await self._direct_product_lookup(query_analysis)
            if direct_docs:
                all_docs.extend(direct_docs)
                direct_lookup_ids = {doc.id for doc in direct_docs}
                logger.info(f"  - Direct lookup found: {len(direct_docs)} docs")

            # Stage 2: Multi-source retrieval (vector search via RPC)
            multi_docs = await self._multi_source_retrieval(query_analysis, top_k)
            all_docs.extend(multi_docs)

            # Stage 3: Fallback keyword search if no results
            if not all_docs:
                fallback_docs = await self._fallback_keyword_search(query_analysis.original_query, top_k)
                all_docs.extend(fallback_docs)
                if fallback_docs:
                    logger.info(f"  - Fallback keyword search found: {len(fallback_docs)} docs")

            total_retrieved = len(all_docs)
            logger.info(f"  - Total retrieved: {total_retrieved}")

            if not all_docs:
                return RetrievalResult(
                    documents=[],
                    total_retrieved=0,
                    total_after_rerank=0,
                    avg_similarity=0.0,
                    avg_rerank_score=0.0,
                    sources_used=query_analysis.required_sources
                )

            # Stage 4: De-duplication
            unique_docs = self._deduplicate(all_docs)
            logger.info(f"  - After dedup: {len(unique_docs)}")

            # Stage 5: Re-ranking with LLM
            if self.openai_client and len(unique_docs) > MIN_RELEVANT_DOCS:
                reranked_docs = await self._rerank_with_llm(
                    query_analysis.original_query,
                    unique_docs,
                    query_analysis
                )
            else:
                # Sort by similarity score if no LLM
                reranked_docs = sorted(unique_docs, key=lambda x: x.similarity_score, reverse=True)

            # Boost direct lookup docs to top (user asked about specific crop/formula)
            if direct_lookup_ids:
                boosted = [doc for doc in reranked_docs if doc.id in direct_lookup_ids]
                others = [doc for doc in reranked_docs if doc.id not in direct_lookup_ids]
                reranked_docs = boosted + others
                logger.info(f"  - Boosted {len(boosted)} direct lookup docs to top")

            # Stage 6: Filter by rerank threshold
            filtered_docs = [
                doc for doc in reranked_docs
                if doc.rerank_score >= self.rerank_threshold
                or doc.similarity_score >= self.vector_threshold
                or doc.id in direct_lookup_ids
            ]

            # Ensure we have at least some results
            if len(filtered_docs) < MIN_RELEVANT_DOCS and len(reranked_docs) > 0:
                filtered_docs = reranked_docs[:MIN_RELEVANT_DOCS]

            total_after_rerank = len(filtered_docs)
            avg_similarity = sum(d.similarity_score for d in filtered_docs) / len(filtered_docs) if filtered_docs else 0
            avg_rerank_score = sum(d.rerank_score for d in filtered_docs) / len(filtered_docs) if filtered_docs else 0

            logger.info(f"  - After filter: {total_after_rerank}")
            logger.info(f"  - Avg similarity: {avg_similarity:.3f}, Avg rerank: {avg_rerank_score:.3f}")

            return RetrievalResult(
                documents=filtered_docs[:top_k],
                total_retrieved=total_retrieved,
                total_after_rerank=total_after_rerank,
                avg_similarity=avg_similarity,
                avg_rerank_score=avg_rerank_score,
                sources_used=list(set(d.source for d in filtered_docs))
            )

        except Exception as e:
            logger.error(f"RetrievalAgent error: {e}", exc_info=True)
            return RetrievalResult(
                documents=[],
                total_retrieved=0,
                total_after_rerank=0,
                avg_similarity=0.0,
                avg_rerank_score=0.0,
                sources_used=[]
            )

    async def _multi_source_retrieval(
        self,
        query_analysis: QueryAnalysis,
        top_k: int
    ) -> List[RetrievedDocument]:
        """Retrieve from multiple expanded queries in parallel via hybrid search."""
        all_docs = []
        tasks = []

        # Build retrieval tasks for each expanded query
        for query in query_analysis.expanded_queries:
            tasks.append(self._search_fertilizers(query, top_k))

        # Execute all searches in parallel
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_docs.extend(result)
                elif isinstance(result, Exception):
                    logger.warning(f"Search task failed: {result}")

        return all_docs

    async def _search_fertilizers(
        self,
        query: str,
        top_k: int
    ) -> List[RetrievedDocument]:
        """Search mahbin_npk table with hybrid vector + keyword similarity."""
        if not self.supabase or not self.openai_client:
            return []

        try:
            # Generate embedding
            embedding = await self._generate_embedding(query)
            if not embedding:
                return []

            # Call hybrid search RPC
            rpc_params = {
                'query_embedding': embedding,
                'search_query': query,
                'vector_weight': 0.6,
                'keyword_weight': 0.4,
                'match_count': top_k * 2
            }

            result = self.supabase.rpc('hybrid_search_mahbin_npk', rpc_params).execute()

            if not result.data:
                return []

            # Convert to RetrievedDocument with filtering
            docs = []
            for item in result.data:
                similarity = float(item.get('similarity', 0))

                # Filter by threshold
                if similarity < self.vector_threshold:
                    continue

                doc = self._build_doc_from_row(item, similarity=similarity)
                docs.append(doc)

            logger.info(f"    Fertilizer search: {len(docs)} docs for '{query[:30]}...'")

            return docs

        except Exception as e:
            logger.error(f"Fertilizer search error: {e}")
            return []

    async def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for search query (with LRU cache)."""
        # Check cache first
        cached = _get_cached_embedding(text)
        if cached is not None:
            return cached

        try:
            response = await self.openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text,
                encoding_format="float"
            )
            embedding = response.data[0].embedding
            _set_cached_embedding(text, embedding)
            return embedding
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return []

    def _deduplicate(self, docs: List[RetrievedDocument]) -> List[RetrievedDocument]:
        """Remove duplicate documents based on ID or title."""
        seen_ids = set()
        seen_titles = set()
        unique_docs = []

        for doc in docs:
            # Deduplicate by ID first, then by title
            if doc.id and doc.id in seen_ids:
                continue
            title_key = doc.title.lower().strip()
            if title_key in seen_titles:
                continue
            if doc.id:
                seen_ids.add(doc.id)
            seen_titles.add(title_key)
            unique_docs.append(doc)

        return unique_docs

    async def _rerank_with_llm(
        self,
        query: str,
        docs: List[RetrievedDocument],
        query_analysis: QueryAnalysis
    ) -> List[RetrievedDocument]:
        """Re-rank documents using LLM. Focus on crop, growth stage, fertilizer relevance."""
        if not self.openai_client or len(docs) <= 1:
            return docs

        try:
            # Prepare document summaries
            doc_texts = []
            for i, doc in enumerate(docs[:15], 1):  # Limit to top 15
                text = f"[{i}] {doc.title}"
                if doc.metadata.get('crop'):
                    text += f" | พืช: {doc.metadata['crop']}"
                if doc.metadata.get('growth_stage'):
                    text += f" | ระยะ: {doc.metadata['growth_stage']}"
                if doc.metadata.get('fertilizer_formula'):
                    text += f" | สูตร: {doc.metadata['fertilizer_formula']}"
                if doc.metadata.get('primary_nutrients'):
                    text += f" | ธาตุอาหาร: {str(doc.metadata['primary_nutrients'])[:80]}"
                if doc.metadata.get('benefits'):
                    text += f" | ประโยชน์: {str(doc.metadata['benefits'])[:80]}"
                doc_texts.append(text)

            docs_str = "\n".join(doc_texts)

            # Build intent-specific hint
            intent_hint = ""
            if query_analysis.intent == IntentType.FERTILIZER_RECOMMENDATION:
                intent_hint = "\nผู้ใช้ต้องการคำแนะนำสูตรปุ๋ยที่เหมาะกับพืชและระยะการเจริญเติบโต"
            elif query_analysis.intent == IntentType.USAGE_INSTRUCTION:
                intent_hint = "\nผู้ใช้ต้องการทราบวิธีใช้/อัตราการใส่ปุ๋ย"
            elif query_analysis.intent == IntentType.PRODUCT_INQUIRY:
                intent_hint = "\nผู้ใช้ถามเกี่ยวกับสูตรปุ๋ยเฉพาะ"

            prompt = f"""จัดอันดับความเกี่ยวข้องของเอกสารกับคำถาม

คำถาม: "{query}"{intent_hint}

เอกสาร:
{docs_str}

จัดอันดับจากเกี่ยวข้องมากที่สุดไปน้อยที่สุด
พิจารณา:
1. พืชตรงกับที่ผู้ใช้ถามหรือไม่
2. ระยะการเจริญเติบโตตรงกันหรือไม่
3. สูตรปุ๋ยเหมาะสมกับความต้องการหรือไม่
4. ประโยชน์/ธาตุอาหารตอบโจทย์ผู้ใช้หรือไม่

ตอบเฉพาะตัวเลขเรียงลำดับ คั่นด้วย comma เช่น: 3,1,5,2,4"""

            response = await self.openai_client.chat.completions.create(
                model=LLM_MODEL_RERANKING,
                messages=[
                    {"role": "system", "content": "ตอบเฉพาะตัวเลขเรียงลำดับ คั่นด้วย comma"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=100
            )

            ranking_text = response.choices[0].message.content.strip()
            logger.info(f"    Rerank response: {ranking_text}")

            # Parse ranking
            numbers = re.findall(r'\d+', ranking_text)
            ranking_indices = [int(n) - 1 for n in numbers if 0 < int(n) <= len(docs)]

            # Build reranked list with scores
            reranked = []
            seen_indices = set()
            for rank, idx in enumerate(ranking_indices):
                if idx not in seen_indices and idx < len(docs):
                    doc = docs[idx]
                    # Assign rerank score based on position (higher = better)
                    doc.rerank_score = 1.0 - (rank / len(ranking_indices))
                    reranked.append(doc)
                    seen_indices.add(idx)

            # Add remaining docs with lower scores
            for i, doc in enumerate(docs):
                if i not in seen_indices:
                    doc.rerank_score = 0.3  # Default low score
                    reranked.append(doc)

            return reranked

        except Exception as e:
            logger.warning(f"LLM rerank failed: {e}, using similarity scores")
            return sorted(docs, key=lambda x: x.similarity_score, reverse=True)
