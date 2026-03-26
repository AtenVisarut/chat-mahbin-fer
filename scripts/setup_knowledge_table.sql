-- =============================================================================
-- Knowledge Table Setup for ICP Ladda Chatbot
-- =============================================================================
-- รัน SQL นี้ใน Supabase SQL Editor เพื่อสร้าง knowledge table

-- 1. Enable vector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create knowledge table
CREATE TABLE IF NOT EXISTS knowledge (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    plant_type TEXT DEFAULT '',
    source TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}',
    embedding vector(1536),  -- OpenAI text-embedding-3-small dimension
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Create indexes for better search performance
CREATE INDEX IF NOT EXISTS knowledge_category_idx ON knowledge(category);
CREATE INDEX IF NOT EXISTS knowledge_plant_type_idx ON knowledge(plant_type);
CREATE INDEX IF NOT EXISTS knowledge_embedding_idx ON knowledge
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- 4. Create full-text search index for Thai
CREATE INDEX IF NOT EXISTS knowledge_content_fts_idx ON knowledge
    USING gin(to_tsvector('simple', content));

-- 5. Create vector search function
CREATE OR REPLACE FUNCTION match_knowledge(
    query_embedding vector(1536),
    match_threshold float DEFAULT 0.4,
    match_count int DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    title TEXT,
    content TEXT,
    category TEXT,
    plant_type TEXT,
    source TEXT,
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
        k.source,
        1 - (k.embedding <=> query_embedding) AS similarity
    FROM knowledge k
    WHERE 1 - (k.embedding <=> query_embedding) > match_threshold
    ORDER BY k.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- 6. Create hybrid search function (Vector + Keyword)
CREATE OR REPLACE FUNCTION hybrid_search_knowledge(
    query_embedding vector(1536),
    search_query TEXT,
    vector_weight float DEFAULT 0.6,
    keyword_weight float DEFAULT 0.4,
    match_threshold float DEFAULT 0.3,
    match_count int DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    title TEXT,
    content TEXT,
    category TEXT,
    plant_type TEXT,
    source TEXT,
    vector_score float,
    keyword_score float,
    hybrid_score float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT
            k.id,
            k.title,
            k.content,
            k.category,
            k.plant_type,
            k.source,
            1 - (k.embedding <=> query_embedding) AS v_score,
            ROW_NUMBER() OVER (ORDER BY k.embedding <=> query_embedding) AS v_rank
        FROM knowledge k
        WHERE 1 - (k.embedding <=> query_embedding) > match_threshold * 0.5
        LIMIT match_count * 3
    ),
    keyword_results AS (
        SELECT
            k.id,
            ts_rank(to_tsvector('simple', k.content), plainto_tsquery('simple', search_query)) +
            ts_rank(to_tsvector('simple', k.title), plainto_tsquery('simple', search_query)) AS k_score,
            ROW_NUMBER() OVER (
                ORDER BY ts_rank(to_tsvector('simple', k.content), plainto_tsquery('simple', search_query)) DESC
            ) AS k_rank
        FROM knowledge k
        WHERE
            k.content ILIKE '%' || search_query || '%'
            OR k.title ILIKE '%' || search_query || '%'
        LIMIT match_count * 3
    ),
    combined AS (
        SELECT
            COALESCE(vr.id, kr_data.id) AS id,
            COALESCE(vr.title, kr_data.title) AS title,
            COALESCE(vr.content, kr_data.content) AS content,
            COALESCE(vr.category, kr_data.category) AS category,
            COALESCE(vr.plant_type, kr_data.plant_type) AS plant_type,
            COALESCE(vr.source, kr_data.source) AS source,
            COALESCE(vr.v_score, 0) AS vector_score,
            COALESCE(kr.k_score, 0) AS keyword_score,
            (COALESCE(vr.v_score, 0) * vector_weight) +
            (COALESCE(kr.k_score, 0) * keyword_weight * 0.5) AS hybrid_score
        FROM vector_results vr
        FULL OUTER JOIN keyword_results kr ON vr.id = kr.id
        LEFT JOIN knowledge kr_data ON kr.id = kr_data.id
    )
    SELECT
        c.id,
        c.title,
        c.content,
        c.category,
        c.plant_type,
        c.source,
        c.vector_score,
        c.keyword_score,
        c.hybrid_score
    FROM combined c
    WHERE c.hybrid_score > match_threshold * 0.5
    ORDER BY c.hybrid_score DESC
    LIMIT match_count;
END;
$$;

-- 7. Create update timestamp trigger
CREATE OR REPLACE FUNCTION update_knowledge_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS knowledge_updated_at ON knowledge;
CREATE TRIGGER knowledge_updated_at
    BEFORE UPDATE ON knowledge
    FOR EACH ROW
    EXECUTE FUNCTION update_knowledge_timestamp();

-- 8. Grant permissions (adjust as needed)
-- ALTER TABLE knowledge ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- Sample Categories
-- =============================================================================
-- หมวดหมู่ที่แนะนำสำหรับ knowledge:
-- - disease        : โรคพืช (เชื้อรา, ไวรัส, แบคทีเรีย)
-- - pest           : ศัตรูพืช (แมลง, ไร, หนอน)
-- - crop_care      : การดูแลพืช (ปุ๋ย, น้ำ, การตัดแต่ง)
-- - product_usage  : วิธีใช้ผลิตภัณฑ์
-- - prevention     : การป้องกัน
-- - harvest        : การเก็บเกี่ยว
-- - general        : ความรู้ทั่วไป

-- =============================================================================
-- Verify Setup
-- =============================================================================
SELECT
    'knowledge' as table_name,
    COUNT(*) as row_count
FROM knowledge;
