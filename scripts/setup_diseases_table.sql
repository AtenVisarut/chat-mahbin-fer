-- ============================================================================
-- Diseases Table for RAG-based Disease Detection
-- ============================================================================
-- Run this in Supabase SQL Editor

-- Enable pgvector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Table: diseases
-- ============================================================================
CREATE TABLE IF NOT EXISTS diseases (
    id BIGSERIAL PRIMARY KEY,

    -- Basic Info
    disease_key TEXT UNIQUE NOT NULL,       -- e.g., "rice_blast", "brown_spot"
    name_th TEXT NOT NULL,                  -- ชื่อไทย
    name_en TEXT NOT NULL,                  -- English name
    category TEXT NOT NULL,                 -- 'fungal', 'bacterial', 'viral', 'insect', 'nutrient', 'weed'

    -- Pathogen / Cause
    pathogen TEXT,                          -- เชื้อสาเหตุ
    vector_pest TEXT,                       -- แมลงพาหะ (ถ้ามี)

    -- Host Plants
    host_plants TEXT[],                     -- Array: ['ข้าว', 'rice']

    -- Symptoms & Features (JSONB for flexibility)
    symptoms JSONB NOT NULL DEFAULT '[]',   -- ["อาการ1", "อาการ2", ...]
    key_features JSONB NOT NULL DEFAULT '[]', -- ["ลักษณะเด่น1", ...]
    distinguish_from TEXT,                  -- วิธีแยกจากโรคอื่น

    -- Affected Parts & Severity
    affected_parts TEXT[],                  -- ['ใบ', 'ลำต้น', 'ผล']
    severity_indicators JSONB DEFAULT '{}', -- {"เล็กน้อย": "...", "ปานกลาง": "...", "รุนแรง": "..."}

    -- Treatment (optional)
    treatment_methods JSONB DEFAULT '[]',   -- วิธีรักษา
    prevention_methods JSONB DEFAULT '[]',  -- วิธีป้องกัน
    recommended_products TEXT[],            -- รหัสสินค้าที่แนะนำ

    -- Vector Embedding (for semantic search)
    embedding VECTOR(1536),                 -- OpenAI text-embedding-3-small

    -- Full-text Search
    search_vector TSVECTOR,

    -- Metadata
    is_active BOOLEAN DEFAULT TRUE,
    priority_score INTEGER DEFAULT 50,      -- 1-100 for ranking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT,
    updated_by TEXT
);

-- ============================================================================
-- Indexes
-- ============================================================================

-- Vector similarity search index (IVFFlat)
CREATE INDEX IF NOT EXISTS idx_diseases_embedding ON diseases
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- Category filter
CREATE INDEX IF NOT EXISTS idx_diseases_category ON diseases(category);

-- Host plants (GIN for array contains)
CREATE INDEX IF NOT EXISTS idx_diseases_host_plants ON diseases USING GIN(host_plants);

-- Full-text search
CREATE INDEX IF NOT EXISTS idx_diseases_search_vector ON diseases USING GIN(search_vector);

-- Active diseases only
CREATE INDEX IF NOT EXISTS idx_diseases_active ON diseases(is_active) WHERE is_active = TRUE;

-- Disease key lookup
CREATE INDEX IF NOT EXISTS idx_diseases_key ON diseases(disease_key);

-- ============================================================================
-- Triggers
-- ============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_diseases_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS diseases_updated_at ON diseases;
CREATE TRIGGER diseases_updated_at
    BEFORE UPDATE ON diseases
    FOR EACH ROW EXECUTE FUNCTION update_diseases_timestamp();

-- Auto-update search_vector for full-text search
CREATE OR REPLACE FUNCTION diseases_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('simple', COALESCE(NEW.name_th, '')), 'A') ||
        setweight(to_tsvector('simple', COALESCE(NEW.name_en, '')), 'A') ||
        setweight(to_tsvector('simple', COALESCE(NEW.pathogen, '')), 'B') ||
        setweight(to_tsvector('simple', COALESCE(array_to_string(NEW.host_plants, ' '), '')), 'B') ||
        setweight(to_tsvector('simple', COALESCE(NEW.distinguish_from, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS diseases_search_vector_trigger ON diseases;
CREATE TRIGGER diseases_search_vector_trigger
    BEFORE INSERT OR UPDATE ON diseases
    FOR EACH ROW EXECUTE FUNCTION diseases_search_vector_update();

-- ============================================================================
-- RPC Function: match_diseases (Vector Search)
-- ============================================================================
CREATE OR REPLACE FUNCTION match_diseases(
    query_embedding VECTOR(1536),
    match_threshold FLOAT DEFAULT 0.3,
    match_count INT DEFAULT 5,
    filter_category TEXT DEFAULT NULL,
    filter_host_plant TEXT DEFAULT NULL
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
    affected_parts TEXT[],
    severity_indicators JSONB,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
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
        d.affected_parts,
        d.severity_indicators,
        1 - (d.embedding <=> query_embedding) AS similarity
    FROM diseases d
    WHERE d.is_active = TRUE
        AND d.embedding IS NOT NULL
        AND 1 - (d.embedding <=> query_embedding) > match_threshold
        AND (filter_category IS NULL OR d.category = filter_category)
        AND (filter_host_plant IS NULL OR filter_host_plant = ANY(d.host_plants))
    ORDER BY d.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============================================================================
-- RPC Function: hybrid_search_diseases (Vector + Keyword Search)
-- ============================================================================
CREATE OR REPLACE FUNCTION hybrid_search_diseases(
    query_embedding VECTOR(1536),
    search_query TEXT,
    vector_weight FLOAT DEFAULT 0.6,
    keyword_weight FLOAT DEFAULT 0.4,
    match_threshold FLOAT DEFAULT 0.2,
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
    vector_score FLOAT,
    keyword_score FLOAT,
    hybrid_score FLOAT
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
            1 - (d.embedding <=> query_embedding) AS v_score
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
                ts_rank_cd(d.search_vector, query_tsquery),
                CASE WHEN d.name_th ILIKE '%' || search_query || '%' THEN 0.7 ELSE 0 END,
                CASE WHEN d.name_en ILIKE '%' || search_query || '%' THEN 0.6 ELSE 0 END,
                CASE WHEN d.pathogen ILIKE '%' || search_query || '%' THEN 0.5 ELSE 0 END,
                CASE WHEN d.distinguish_from ILIKE '%' || search_query || '%' THEN 0.3 ELSE 0 END
            ) AS k_score
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
            COALESCE(v.v_score, 0) AS vector_score,
            COALESCE(k.k_score, 0) AS keyword_score,
            (
                vector_weight * COALESCE(v.v_score, 0) +
                keyword_weight * COALESCE(k.k_score, 0) +
                -- Bonus for appearing in both searches
                CASE WHEN v.id IS NOT NULL AND k.id IS NOT NULL THEN 0.1 ELSE 0 END
            ) AS hybrid_score
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

-- ============================================================================
-- RPC Function: keyword_search_diseases (Keyword Only)
-- ============================================================================
CREATE OR REPLACE FUNCTION keyword_search_diseases(
    search_query TEXT,
    match_count INT DEFAULT 10,
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
    rank_score FLOAT
)
LANGUAGE plpgsql
AS $$
DECLARE
    query_tsquery TSQUERY;
BEGIN
    query_tsquery := plainto_tsquery('simple', search_query);

    RETURN QUERY
    SELECT
        d.id,
        d.disease_key,
        d.name_th,
        d.name_en,
        d.category,
        d.pathogen,
        d.symptoms,
        d.key_features,
        GREATEST(
            ts_rank_cd(d.search_vector, query_tsquery),
            CASE WHEN d.name_th ILIKE '%' || search_query || '%' THEN 0.8 ELSE 0 END,
            CASE WHEN d.name_en ILIKE '%' || search_query || '%' THEN 0.7 ELSE 0 END
        ) AS rank_score
    FROM diseases d
    WHERE d.is_active = TRUE
        AND (
            d.search_vector @@ query_tsquery
            OR d.name_th ILIKE '%' || search_query || '%'
            OR d.name_en ILIKE '%' || search_query || '%'
            OR d.pathogen ILIKE '%' || search_query || '%'
        )
        AND (filter_category IS NULL OR d.category = filter_category)
    ORDER BY rank_score DESC
    LIMIT match_count;
END;
$$;

-- ============================================================================
-- Permissions
-- ============================================================================
GRANT SELECT ON diseases TO anon, authenticated;
GRANT INSERT, UPDATE, DELETE ON diseases TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE diseases_id_seq TO authenticated;
GRANT EXECUTE ON FUNCTION match_diseases TO anon, authenticated;
GRANT EXECUTE ON FUNCTION hybrid_search_diseases TO anon, authenticated;
GRANT EXECUTE ON FUNCTION keyword_search_diseases TO anon, authenticated;

-- ============================================================================
-- Comments
-- ============================================================================
COMMENT ON TABLE diseases IS 'Disease database for RAG-based plant disease detection';
COMMENT ON COLUMN diseases.disease_key IS 'Unique identifier like rice_blast, brown_spot';
COMMENT ON COLUMN diseases.category IS 'fungal, bacterial, viral, insect, nutrient, weed';
COMMENT ON COLUMN diseases.embedding IS 'OpenAI text-embedding-3-small (1536 dimensions)';
COMMENT ON FUNCTION match_diseases IS 'Vector similarity search for diseases';
COMMENT ON FUNCTION hybrid_search_diseases IS 'Combined vector + keyword search with weighted scoring';
