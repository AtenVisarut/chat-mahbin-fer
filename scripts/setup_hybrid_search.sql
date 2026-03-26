-- ============================================================================
-- Hybrid Search Setup (Vector + Full-Text/BM25)
-- Run this SQL in Supabase SQL Editor
-- ============================================================================

-- 1. Add Full-Text Search column to products table
ALTER TABLE products ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- 2. Update search_vector with product content (Thai + English)
UPDATE products SET search_vector =
    setweight(to_tsvector('simple', coalesce(product_name, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(target_pest, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(active_ingredient, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(applicable_crops, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(how_to_use, '')), 'C');

-- 3. Create index for full-text search
CREATE INDEX IF NOT EXISTS idx_products_search_vector ON products USING GIN(search_vector);

-- 4. Create trigger to auto-update search_vector
CREATE OR REPLACE FUNCTION products_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('simple', coalesce(NEW.product_name, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.target_pest, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.active_ingredient, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(NEW.applicable_crops, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(NEW.how_to_use, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS products_search_vector_trigger ON products;
CREATE TRIGGER products_search_vector_trigger
    BEFORE INSERT OR UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION products_search_vector_update();

-- 5. Full-Text Search function (BM25-like ranking)
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
    rank float
)
LANGUAGE plpgsql
AS $$
DECLARE
    query_tsquery tsquery;
BEGIN
    -- Convert search query to tsquery (split by space, combine with OR)
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

-- 6. Hybrid Search function (combines Vector + Keyword)
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
            -- Reciprocal Rank Fusion (RRF) style scoring
            (
                vector_weight * COALESCE(v.v_score, 0) +
                keyword_weight * COALESCE(k.k_score, 0) +
                -- RRF bonus for appearing in both
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
        c.vector_score,
        c.keyword_score,
        c.hybrid_score
    FROM combined c
    JOIN products p ON p.id = c.combined_id
    ORDER BY c.hybrid_score DESC
    LIMIT match_count;
END;
$$;

-- 7. Grant permissions
GRANT EXECUTE ON FUNCTION keyword_search_products TO authenticated, anon;
GRANT EXECUTE ON FUNCTION hybrid_search_products TO authenticated, anon;
