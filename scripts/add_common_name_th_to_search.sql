-- ============================================================================
-- Add common_name_th to search_vector for hybrid search
-- Run this SQL in Supabase SQL Editor
-- ============================================================================

-- 1. Update search_vector to include common_name_th (Weight 'A' = highest)
UPDATE products SET search_vector =
    setweight(to_tsvector('simple', coalesce(product_name, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(target_pest, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(common_name_th, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(active_ingredient, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(applicable_crops, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(how_to_use, '')), 'C');

-- 2. Update trigger to include common_name_th
CREATE OR REPLACE FUNCTION products_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('simple', coalesce(NEW.product_name, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.target_pest, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.common_name_th, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.active_ingredient, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(NEW.applicable_crops, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(NEW.how_to_use, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
