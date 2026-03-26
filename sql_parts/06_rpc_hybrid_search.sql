-- ============================================================================
-- RPC Function: hybrid_search_mahbin_npk
-- Hybrid Search = Vector Search + Full-Text Keyword Search
-- ============================================================================
--
-- ใช้โดย:
--   - app/services/rag/retrieval_agent.py      (main RAG pipeline)
--   - app/services/product/recommendation.py   (hybrid_search_products fallback)
--
-- Parameters:
--   query_embedding  vector(1536)  — embedding จาก OpenAI text-embedding-3-small
--   search_query     text          — คำค้นหาเดิม (ภาษาไทย)
--   vector_weight    float         — น้ำหนัก vector score (default 0.6)
--   keyword_weight   float         — น้ำหนัก keyword score (default 0.4)
--   match_count      int           — จำนวนผลลัพธ์สูงสุด
--
-- Returns:
--   id, crop, growth_stage, fertilizer_formula, usage_rate,
--   primary_nutrients, benefits, similarity

create or replace function hybrid_search_mahbin_npk(
    query_embedding vector(1536),
    search_query text,
    vector_weight float default 0.6,
    keyword_weight float default 0.4,
    match_count int default 10
)
returns table (
    id bigint,
    crop text,
    growth_stage text,
    fertilizer_formula text,
    usage_rate text,
    primary_nutrients text,
    benefits text,
    similarity float
)
language plpgsql
as $$
begin
    return query
    with vector_search as (
        select
            m.id,
            m.crop,
            m.growth_stage,
            m.fertilizer_formula,
            m.usage_rate,
            m.primary_nutrients,
            m.benefits,
            1 - (m.embedding <=> query_embedding) as vector_score
        from mahbin_npk m
        order by m.embedding <=> query_embedding
        limit match_count * 3
    ),
    keyword_search as (
        select
            m.id,
            m.crop,
            m.growth_stage,
            m.fertilizer_formula,
            m.usage_rate,
            m.primary_nutrients,
            m.benefits,
            ts_rank(m.search_vector, plainto_tsquery('simple', search_query)) as keyword_score
        from mahbin_npk m
        where m.search_vector @@ plainto_tsquery('simple', search_query)
        order by keyword_score desc
        limit match_count * 3
    ),
    combined as (
        select
            coalesce(v.id, k.id) as id,
            coalesce(v.crop, k.crop) as crop,
            coalesce(v.growth_stage, k.growth_stage) as growth_stage,
            coalesce(v.fertilizer_formula, k.fertilizer_formula) as fertilizer_formula,
            coalesce(v.usage_rate, k.usage_rate) as usage_rate,
            coalesce(v.primary_nutrients, k.primary_nutrients) as primary_nutrients,
            coalesce(v.benefits, k.benefits) as benefits,
            (coalesce(v.vector_score, 0) * vector_weight +
             coalesce(k.keyword_score, 0) * keyword_weight) as similarity
        from vector_search v
        full outer join keyword_search k on v.id = k.id
    )
    select
        c.id, c.crop, c.growth_stage, c.fertilizer_formula,
        c.usage_rate, c.primary_nutrients, c.benefits, c.similarity
    from combined c
    order by c.similarity desc
    limit match_count;
end;
$$;
