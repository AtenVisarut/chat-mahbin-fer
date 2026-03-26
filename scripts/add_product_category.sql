-- ============================================================================
-- เพิ่ม column product_category ใน table products
-- ============================================================================

-- 1. เพิ่ม column
ALTER TABLE products
ADD COLUMN IF NOT EXISTS product_category text;

-- 2. สร้าง index เพื่อ query เร็วขึ้น
CREATE INDEX IF NOT EXISTS idx_products_category ON products(product_category);

-- 3. อัปเดต match_products function ให้ return product_category ด้วย
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
    1 - (products.embedding <=> query_embedding) AS similarity
  FROM products
  WHERE 1 - (products.embedding <=> query_embedding) > match_threshold
  ORDER BY products.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- 4. อัปเดต hybrid_search_products function (ถ้ามี)
CREATE OR REPLACE FUNCTION hybrid_search_products (
  query_embedding vector(1536),
  search_query text,
  vector_weight float DEFAULT 0.6,
  keyword_weight float DEFAULT 0.4,
  match_threshold float DEFAULT 0.15,
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
  vector_score float,
  keyword_score float,
  hybrid_score float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  WITH vector_search AS (
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
      1 - (p.embedding <=> query_embedding) AS similarity,
      ROW_NUMBER() OVER (ORDER BY p.embedding <=> query_embedding) AS rank
    FROM products p
    WHERE 1 - (p.embedding <=> query_embedding) > match_threshold
  ),
  keyword_search AS (
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
      ts_rank(
        to_tsvector('simple', COALESCE(p.product_name, '') || ' ' ||
                              COALESCE(p.target_pest, '') || ' ' ||
                              COALESCE(p.applicable_crops, '') || ' ' ||
                              COALESCE(p.active_ingredient, '')),
        plainto_tsquery('simple', search_query)
      ) AS rank_score,
      ROW_NUMBER() OVER (ORDER BY ts_rank(
        to_tsvector('simple', COALESCE(p.product_name, '') || ' ' ||
                              COALESCE(p.target_pest, '') || ' ' ||
                              COALESCE(p.applicable_crops, '') || ' ' ||
                              COALESCE(p.active_ingredient, '')),
        plainto_tsquery('simple', search_query)
      ) DESC) AS rank
    FROM products p
    WHERE
      p.product_name ILIKE '%' || search_query || '%' OR
      p.target_pest ILIKE '%' || search_query || '%' OR
      p.applicable_crops ILIKE '%' || search_query || '%' OR
      p.active_ingredient ILIKE '%' || search_query || '%'
  )
  SELECT
    COALESCE(v.id, k.id) AS id,
    COALESCE(v.product_name, k.product_name) AS product_name,
    COALESCE(v.active_ingredient, k.active_ingredient) AS active_ingredient,
    COALESCE(v.target_pest, k.target_pest) AS target_pest,
    COALESCE(v.applicable_crops, k.applicable_crops) AS applicable_crops,
    COALESCE(v.how_to_use, k.how_to_use) AS how_to_use,
    COALESCE(v.usage_period, k.usage_period) AS usage_period,
    COALESCE(v.usage_rate, k.usage_rate) AS usage_rate,
    COALESCE(v.link_product, k.link_product) AS link_product,
    COALESCE(v.product_category, k.product_category) AS product_category,
    COALESCE(v.similarity, 0)::float AS vector_score,
    COALESCE(k.rank_score, 0)::float AS keyword_score,
    (
      vector_weight * COALESCE(1.0 / (60 + v.rank), 0) +
      keyword_weight * COALESCE(1.0 / (60 + k.rank), 0)
    )::float AS hybrid_score
  FROM vector_search v
  FULL OUTER JOIN keyword_search k ON v.id = k.id
  ORDER BY hybrid_score DESC
  LIMIT match_count;
END;
$$;

-- 5. Grant permissions
GRANT ALL ON products TO authenticated;
GRANT ALL ON products TO anon;
