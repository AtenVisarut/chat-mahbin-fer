-- =============================================================================
-- แก้ไข match_knowledge RPC Function ให้ return ทุก fields ที่จำเป็น
-- =============================================================================
-- วันที่: 2026-02-02
-- ปัญหา: RPC function ไม่ได้ return product_name, usage_rate, how_to_use, target_pest
-- =============================================================================

-- Drop existing function
DROP FUNCTION IF EXISTS match_knowledge(vector(1536), float, int);

-- Create new function with all fields
CREATE OR REPLACE FUNCTION match_knowledge(
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.2,
  match_count int DEFAULT 10
)
RETURNS TABLE (
  id uuid,
  title text,
  content text,
  category text,
  plant_type text,
  product_name text,
  chemical_name text,
  target_pest text,
  usage_rate text,
  how_to_use text,
  usage_period text,
  properties text,
  source text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    k.id,
    k.title,
    k.content,
    k.category,
    k.plant_type,
    k.product_name,
    k.chemical_name,
    k.target_pest,
    k.usage_rate,
    k.how_to_use,
    k.usage_period,
    k.properties,
    k.source,
    1 - (k.embedding <=> query_embedding) AS similarity
  FROM knowledge k
  WHERE k.embedding IS NOT NULL
    AND 1 - (k.embedding <=> query_embedding) > match_threshold
  ORDER BY k.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- Grant execute permission
GRANT EXECUTE ON FUNCTION match_knowledge(vector(1536), float, int) TO anon, authenticated, service_role;

-- Test the function
-- SELECT * FROM match_knowledge(
--   (SELECT embedding FROM knowledge LIMIT 1),
--   0.2,
--   5
-- );
