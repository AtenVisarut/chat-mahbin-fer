-- ============================================================================
-- เพิ่ม 10 columns ใน table products สำหรับข้อมูลเพิ่มเติมจาก CSV
-- ============================================================================

-- 1. เพิ่ม columns
ALTER TABLE products ADD COLUMN IF NOT EXISTS package_size text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS common_name_th text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS physical_form text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS selling_point text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS absorption_method text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS mechanism_of_action text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS action_characteristics text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS phytotoxicity text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS label_color_band text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS registration_expiry text;

-- 2. DROP ALL overloads ของ function เดิม
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT oid::regprocedure as sig FROM pg_proc WHERE proname = 'hybrid_search_products') LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || r.sig;
    END LOOP;
    FOR r IN (SELECT oid::regprocedure as sig FROM pg_proc WHERE proname = 'match_products') LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || r.sig;
    END LOOP;
END $$;

-- 3. สร้าง match_products ใหม่พร้อม columns ใหม่
CREATE OR REPLACE FUNCTION match_products (
  query_embedding vector(1536),
  match_threshold float,
  match_count int
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
  product_category text,
  package_size text,
  common_name_th text,
  physical_form text,
  selling_point text,
  absorption_method text,
  mechanism_of_action text,
  action_characteristics text,
  phytotoxicity text,
  label_color_band text,
  registration_expiry text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    products.id,
    products.product_name,
    products.active_ingredient,
    products.target_pest,
    products.applicable_crops,
    products.how_to_use,
    products.usage_period,
    products.usage_rate,
    products.link_product,
    products.product_category,
    products.package_size,
    products.common_name_th,
    products.physical_form,
    products.selling_point,
    products.absorption_method,
    products.mechanism_of_action,
    products.action_characteristics,
    products.phytotoxicity,
    products.label_color_band,
    products.registration_expiry,
    1 - (products.embedding <=> query_embedding) AS similarity
  FROM products
  WHERE 1 - (products.embedding <=> query_embedding) > match_threshold
  ORDER BY products.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- 4. สร้าง hybrid_search_products ใหม่
--    ใช้ search_vector pattern (เหมือน update_hybrid_search_pathogen.sql ที่ใช้งานได้)
--    + เพิ่ม 10 columns ใหม่
--    + คืน similarity column ที่ retrieval_agent ต้องการ
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
    product_category text,
    package_size text,
    common_name_th text,
    physical_form text,
    selling_point text,
    absorption_method text,
    mechanism_of_action text,
    action_characteristics text,
    phytotoxicity text,
    label_color_band text,
    registration_expiry text,
    similarity float,
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
            (1 - (p.embedding <=> query_embedding))::double precision as v_score,
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
                ts_rank_cd(p.search_vector, query_tsquery)::double precision,
                CASE WHEN p.product_name ILIKE '%' || search_query || '%' THEN 0.5 ELSE 0.0 END,
                CASE WHEN p.target_pest ILIKE '%' || search_query || '%' THEN 0.4 ELSE 0.0 END,
                CASE WHEN p.applicable_crops ILIKE '%' || search_query || '%' THEN 0.3 ELSE 0.0 END
            )::double precision as k_score,
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
            COALESCE(v.v_score, 0)::double precision as v_score_final,
            COALESCE(k.k_score, 0)::double precision as k_score_final,
            (
                vector_weight * COALESCE(v.v_score, 0) +
                keyword_weight * COALESCE(k.k_score, 0) +
                CASE WHEN v.id IS NOT NULL AND k.id IS NOT NULL THEN 0.1 ELSE 0 END
            )::double precision as h_score
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
        p.product_category,
        p.package_size,
        p.common_name_th,
        p.physical_form,
        p.selling_point,
        p.absorption_method,
        p.mechanism_of_action,
        p.action_characteristics,
        p.phytotoxicity,
        p.label_color_band,
        p.registration_expiry,
        c.v_score_final AS similarity,
        c.v_score_final AS vector_score,
        c.k_score_final AS keyword_score,
        c.h_score AS hybrid_score
    FROM combined c
    JOIN products p ON p.id = c.combined_id
    ORDER BY c.h_score DESC
    LIMIT match_count;
END;
$$;

-- 5. Grant permissions
GRANT ALL ON products TO authenticated;
GRANT ALL ON products TO anon;
GRANT EXECUTE ON FUNCTION match_products TO authenticated, anon;
GRANT EXECUTE ON FUNCTION hybrid_search_products TO authenticated, anon;
