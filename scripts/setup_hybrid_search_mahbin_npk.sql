-- ============================================================================
-- Hybrid Search Setup สำหรับ mahbin_npk (Vector + Full-Text/BM25)
-- รัน SQL นี้ใน Supabase SQL Editor
-- ============================================================================

-- ============================================================================
-- 1. เพิ่ม search_vector column (ถ้ายังไม่มี)
-- ============================================================================
ALTER TABLE mahbin_npk ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- ============================================================================
-- 2. อัพเดต search_vector ด้วยข้อมูลปุ๋ย
-- ============================================================================
UPDATE mahbin_npk SET search_vector =
    setweight(to_tsvector('simple', coalesce(crop, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(growth_stage, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(fertilizer_formula, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(primary_nutrients, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(benefits, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(usage_rate, '')), 'C');

-- ============================================================================
-- 3. สร้าง GIN index สำหรับ full-text search
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_mahbin_npk_search_vector
    ON mahbin_npk USING GIN(search_vector);

-- ============================================================================
-- 4. สร้าง trigger เพื่อ auto-update search_vector เมื่อมีการเปลี่ยนแปลงข้อมูล
-- ============================================================================
CREATE OR REPLACE FUNCTION mahbin_npk_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('simple', coalesce(NEW.crop, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.growth_stage, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.fertilizer_formula, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.primary_nutrients, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(NEW.benefits, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(NEW.usage_rate, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS mahbin_npk_search_vector_trigger ON mahbin_npk;
CREATE TRIGGER mahbin_npk_search_vector_trigger
    BEFORE INSERT OR UPDATE ON mahbin_npk
    FOR EACH ROW EXECUTE FUNCTION mahbin_npk_search_vector_update();

-- ============================================================================
-- 5. Hybrid Search Function (Vector + Keyword)
--    Parameters ตรงกับที่ retrieval_agent.py เรียก:
--      query_embedding, search_query, vector_weight, keyword_weight, match_count
--    Returns: id, crop, growth_stage, fertilizer_formula, usage_rate,
--             primary_nutrients, benefits, similarity
-- ============================================================================
DROP FUNCTION IF EXISTS hybrid_search_mahbin_npk;

CREATE OR REPLACE FUNCTION hybrid_search_mahbin_npk(
    query_embedding VECTOR(1536),
    search_query TEXT,
    vector_weight DOUBLE PRECISION DEFAULT 0.6,
    keyword_weight DOUBLE PRECISION DEFAULT 0.4,
    match_count INT DEFAULT 15
)
RETURNS TABLE (
    id BIGINT,
    crop TEXT,
    growth_stage TEXT,
    fertilizer_formula TEXT,
    usage_rate TEXT,
    primary_nutrients TEXT,
    benefits TEXT,
    similarity DOUBLE PRECISION
)
LANGUAGE plpgsql
AS $$
DECLARE
    query_tsquery TSQUERY;
BEGIN
    query_tsquery := plainto_tsquery('simple', search_query);

    RETURN QUERY
    WITH vector_results AS (
        SELECT
            m.id,
            (1 - (m.embedding <=> query_embedding))::DOUBLE PRECISION AS v_score
        FROM mahbin_npk m
        WHERE m.embedding IS NOT NULL
          AND 1 - (m.embedding <=> query_embedding) > 0.15
        ORDER BY m.embedding <=> query_embedding
        LIMIT match_count * 3
    ),
    keyword_results AS (
        SELECT
            m.id,
            GREATEST(
                ts_rank_cd(m.search_vector, query_tsquery)::DOUBLE PRECISION,
                CASE WHEN m.crop ILIKE '%' || search_query || '%' THEN 0.7 ELSE 0 END,
                CASE WHEN m.growth_stage ILIKE '%' || search_query || '%' THEN 0.6 ELSE 0 END,
                CASE WHEN m.fertilizer_formula ILIKE '%' || search_query || '%' THEN 0.5 ELSE 0 END,
                CASE WHEN m.benefits ILIKE '%' || search_query || '%' THEN 0.3 ELSE 0 END
            )::DOUBLE PRECISION AS k_score
        FROM mahbin_npk m
        WHERE m.search_vector @@ query_tsquery
           OR m.crop ILIKE '%' || search_query || '%'
           OR m.growth_stage ILIKE '%' || search_query || '%'
           OR m.fertilizer_formula ILIKE '%' || search_query || '%'
           OR m.benefits ILIKE '%' || search_query || '%'
        LIMIT match_count * 3
    ),
    combined AS (
        SELECT
            COALESCE(v.id, k.id) AS combined_id,
            COALESCE(v.v_score, 0)::DOUBLE PRECISION AS v_score,
            COALESCE(k.k_score, 0)::DOUBLE PRECISION AS k_score,
            (
                vector_weight * COALESCE(v.v_score, 0) +
                keyword_weight * COALESCE(k.k_score, 0) +
                -- Bonus ถ้าเจอทั้ง vector + keyword
                CASE WHEN v.id IS NOT NULL AND k.id IS NOT NULL THEN 0.1 ELSE 0 END
            )::DOUBLE PRECISION AS hybrid_score
        FROM vector_results v
        FULL OUTER JOIN keyword_results k ON v.id = k.id
    )
    SELECT
        m.id,
        m.crop,
        m.growth_stage,
        m.fertilizer_formula,
        m.usage_rate,
        m.primary_nutrients,
        m.benefits,
        c.hybrid_score AS similarity
    FROM combined c
    JOIN mahbin_npk m ON m.id = c.combined_id
    WHERE c.hybrid_score > 0
    ORDER BY c.hybrid_score DESC
    LIMIT match_count;
END;
$$;

-- ============================================================================
-- 6. Grant permissions
-- ============================================================================
GRANT EXECUTE ON FUNCTION hybrid_search_mahbin_npk TO anon, authenticated;

-- ============================================================================
-- 7. Verify
-- ============================================================================
SELECT 'hybrid_search_mahbin_npk created successfully!' AS status;
