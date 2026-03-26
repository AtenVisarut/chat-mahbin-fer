-- ============================================================================
-- Update Hybrid Search to include pathogen_type
-- Run this SQL in Supabase SQL Editor
-- ============================================================================

-- 0. Drop existing functions (required because return type changed)
DROP FUNCTION IF EXISTS keyword_search_products(text, integer);
DROP FUNCTION IF EXISTS hybrid_search_products(vector, text, float, float, float, integer);

-- 1. Update keyword_search_products to include pathogen_type
CREATE OR REPLACE FUNCTION keyword_search_products(
    search_query text,
    match_count int DEFAULT 15
)
RETURNS TABLE (
    id bigint,
    product_name text,
    active_ingredient text,
    target_pest text,
    applicable_crops text,
    how_to_use text,
    usage_period text,
    usage_rate text,
    link_product text,
    pathogen_type text,
    rank float
)
LANGUAGE plpgsql
AS $$
DECLARE
    query_tsquery tsquery;
BEGIN
    query_tsquery := plainto_tsquery('simple', search_query);

    RETURN QUERY
    SELECT
        p.id,
        p.product_name,
        p.active_ingredient,
        p.target_pest,
        p.applicable_crops,
        p.how_to_use,
        p.usage_period,
        p.usage_rate,
        p.link_product,
        p.pathogen_type,
        ts_rank_cd(p.search_vector, query_tsquery)::float as rank
    FROM products p
    WHERE p.search_vector @@ query_tsquery
       OR p.product_name ILIKE '%' || search_query || '%'
       OR p.target_pest ILIKE '%' || search_query || '%'
       OR p.applicable_crops ILIKE '%' || search_query || '%'
       OR p.active_ingredient ILIKE '%' || search_query || '%'
    ORDER BY
        ts_rank_cd(p.search_vector, query_tsquery) DESC,
        CASE WHEN p.product_name ILIKE '%' || search_query || '%' THEN 1 ELSE 0 END DESC,
        CASE WHEN p.target_pest ILIKE '%' || search_query || '%' THEN 1 ELSE 0 END DESC
    LIMIT match_count;
END;
$$;

-- 2. Update hybrid_search_products to include pathogen_type
CREATE OR REPLACE FUNCTION hybrid_search_products(
    query_embedding vector(1536),
    search_query text,
    vector_weight float DEFAULT 0.6,
    keyword_weight float DEFAULT 0.4,
    match_threshold float DEFAULT 0.2,
    match_count int DEFAULT 15
)
RETURNS TABLE (
    id bigint,
    product_name text,
    active_ingredient text,
    target_pest text,
    applicable_crops text,
    how_to_use text,
    usage_period text,
    usage_rate text,
    link_product text,
    pathogen_type text,
    vector_score float,
    keyword_score float,
    hybrid_score float
)
LANGUAGE plpgsql
AS $$
DECLARE
    query_tsquery tsquery;
BEGIN
    query_tsquery := plainto_tsquery('simple', search_query);

    RETURN QUERY
    WITH vector_results AS (
        SELECT
            p.id,
            1 - (p.embedding <=> query_embedding) as v_score,
            ROW_NUMBER() OVER (ORDER BY p.embedding <=> query_embedding) as v_rank
        FROM products p
        WHERE 1 - (p.embedding <=> query_embedding) > match_threshold
        ORDER BY p.embedding <=> query_embedding
        LIMIT match_count * 2
    ),
    keyword_results AS (
        SELECT
            p.id,
            GREATEST(
                ts_rank_cd(p.search_vector, query_tsquery),
                CASE WHEN p.product_name ILIKE '%' || search_query || '%' THEN 0.5 ELSE 0 END,
                CASE WHEN p.target_pest ILIKE '%' || search_query || '%' THEN 0.4 ELSE 0 END,
                CASE WHEN p.applicable_crops ILIKE '%' || search_query || '%' THEN 0.3 ELSE 0 END
            ) as k_score,
            ROW_NUMBER() OVER (ORDER BY ts_rank_cd(p.search_vector, query_tsquery) DESC) as k_rank
        FROM products p
        WHERE p.search_vector @@ query_tsquery
           OR p.product_name ILIKE '%' || search_query || '%'
           OR p.target_pest ILIKE '%' || search_query || '%'
           OR p.applicable_crops ILIKE '%' || search_query || '%'
        LIMIT match_count * 2
    ),
    combined AS (
        SELECT
            COALESCE(v.id, k.id) as combined_id,
            COALESCE(v.v_score, 0) as vector_score,
            COALESCE(k.k_score, 0) as keyword_score,
            (
                vector_weight * COALESCE(v.v_score, 0) +
                keyword_weight * COALESCE(k.k_score, 0) +
                CASE WHEN v.id IS NOT NULL AND k.id IS NOT NULL THEN 0.1 ELSE 0 END
            ) as hybrid_score
        FROM vector_results v
        FULL OUTER JOIN keyword_results k ON v.id = k.id
    )
    SELECT
        p.id,
        p.product_name,
        p.active_ingredient,
        p.target_pest,
        p.applicable_crops,
        p.how_to_use,
        p.usage_period,
        p.usage_rate,
        p.link_product,
        p.pathogen_type,
        c.vector_score,
        c.keyword_score,
        c.hybrid_score
    FROM combined c
    JOIN products p ON p.id = c.combined_id
    ORDER BY c.hybrid_score DESC
    LIMIT match_count;
END;
$$;

-- 3. Grant permissions
GRANT EXECUTE ON FUNCTION keyword_search_products TO authenticated, anon;
GRANT EXECUTE ON FUNCTION hybrid_search_products TO authenticated, anon;
