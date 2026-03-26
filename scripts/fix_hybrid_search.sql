-- ============================================================================
-- FIX: hybrid_search_diseases function type mismatch
-- รันใน Supabase SQL Editor
-- ============================================================================

-- Drop existing function first
DROP FUNCTION IF EXISTS hybrid_search_diseases;

-- Recreate with correct types (DOUBLE PRECISION instead of FLOAT)
CREATE OR REPLACE FUNCTION hybrid_search_diseases(
    query_embedding VECTOR(1536),
    search_query TEXT,
    vector_weight DOUBLE PRECISION DEFAULT 0.6,
    keyword_weight DOUBLE PRECISION DEFAULT 0.4,
    match_threshold DOUBLE PRECISION DEFAULT 0.2,
    match_count INT DEFAULT 5,
    filter_category TEXT DEFAULT NULL
)
RETURNS TABLE (
    id BIGINT,
    disease_key TEXT,
    name_th TEXT,
    name_en TEXT,
    category TEXT,
    pathogen TEXT,
    symptoms JSONB,
    key_features JSONB,
    distinguish_from TEXT,
    severity_indicators JSONB,
    vector_score DOUBLE PRECISION,
    keyword_score DOUBLE PRECISION,
    hybrid_score DOUBLE PRECISION
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
            d.id,
            (1 - (d.embedding <=> query_embedding))::DOUBLE PRECISION AS v_score
        FROM diseases d
        WHERE d.is_active = TRUE
            AND d.embedding IS NOT NULL
            AND 1 - (d.embedding <=> query_embedding) > match_threshold
            AND (filter_category IS NULL OR d.category = filter_category)
        ORDER BY d.embedding <=> query_embedding
        LIMIT match_count * 3
    ),
    keyword_results AS (
        SELECT
            d.id,
            GREATEST(
                ts_rank_cd(d.search_vector, query_tsquery)::DOUBLE PRECISION,
                CASE WHEN d.name_th ILIKE '%' || search_query || '%' THEN 0.7 ELSE 0 END,
                CASE WHEN d.name_en ILIKE '%' || search_query || '%' THEN 0.6 ELSE 0 END,
                CASE WHEN d.pathogen ILIKE '%' || search_query || '%' THEN 0.5 ELSE 0 END,
                CASE WHEN d.distinguish_from ILIKE '%' || search_query || '%' THEN 0.3 ELSE 0 END
            )::DOUBLE PRECISION AS k_score
        FROM diseases d
        WHERE d.is_active = TRUE
            AND (
                d.search_vector @@ query_tsquery
                OR d.name_th ILIKE '%' || search_query || '%'
                OR d.name_en ILIKE '%' || search_query || '%'
                OR d.pathogen ILIKE '%' || search_query || '%'
            )
            AND (filter_category IS NULL OR d.category = filter_category)
        LIMIT match_count * 3
    ),
    combined AS (
        SELECT
            COALESCE(v.id, k.id) AS combined_id,
            COALESCE(v.v_score, 0)::DOUBLE PRECISION AS vector_score,
            COALESCE(k.k_score, 0)::DOUBLE PRECISION AS keyword_score,
            (
                vector_weight * COALESCE(v.v_score, 0) +
                keyword_weight * COALESCE(k.k_score, 0) +
                CASE WHEN v.id IS NOT NULL AND k.id IS NOT NULL THEN 0.1 ELSE 0 END
            )::DOUBLE PRECISION AS hybrid_score
        FROM vector_results v
        FULL OUTER JOIN keyword_results k ON v.id = k.id
    )
    SELECT
        d.id,
        d.disease_key,
        d.name_th,
        d.name_en,
        d.category,
        d.pathogen,
        d.symptoms,
        d.key_features,
        d.distinguish_from,
        d.severity_indicators,
        c.vector_score,
        c.keyword_score,
        c.hybrid_score
    FROM combined c
    JOIN diseases d ON d.id = c.combined_id
    WHERE c.hybrid_score > 0
    ORDER BY c.hybrid_score DESC
    LIMIT match_count;
END;
$$;

-- Grant permissions
GRANT EXECUTE ON FUNCTION hybrid_search_diseases TO anon, authenticated;

-- Verify
SELECT 'hybrid_search_diseases function fixed!' AS status;
