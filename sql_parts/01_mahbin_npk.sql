-- ============================================================================
-- Table: mahbin_npk
-- ข้อมูลปุ๋ย ICP Fertilizer + vector embeddings สำหรับ RAG search
-- ============================================================================
--
-- ใช้โดย:
--   - app/services/rag/retrieval_agent.py  (vector search + keyword search)
--   - app/services/product/registry.py      (load product catalog)
--   - app/services/product/recommendation.py (hybrid search)
--   - app/services/chat/handler.py          (fetch product by formula)
--   - app/routers/admin.py                  (admin regenerate embeddings)
--
-- ข้อมูลตัวอย่าง (19 rows):
--   crop=อ้อย, growth_stage=รองพื้น/บำรุง, formula=16-20-0, usage_rate=50กก./ไร่
--   crop=นาข้าว, growth_stage=เร่งต้น/แตกกอ, formula=46-0-0, usage_rate=25-30กก./ไร่

create table if not exists mahbin_npk (
    id                  bigint generated always as identity primary key,
    crop                text not null,          -- ชื่อพืช เช่น นาข้าว, อ้อย, ข้าวโพด
    growth_stage        text,                   -- ระยะการเจริญเติบโต เช่น เร่งต้น/แตกกอ
    fertilizer_formula  text,                   -- สูตรปุ๋ย เช่น 16-20-0 หรือ 16-8-8
    usage_rate          text,                   -- อัตราใช้ เช่น 50 กก./ไร่
    primary_nutrients   text,                   -- ธาตุอาหารหลัก เช่น N, N P K Mg S
    benefits            text,                   -- ประโยชน์ เช่น กอใหญ่ ใบเขียว ยึดข้อปล้อง
    embedding           vector(1536),           -- OpenAI text-embedding-3-small
    search_vector       tsvector,               -- Full-text search vector (auto-generated)
    created_at          timestamptz default now()
);

-- Index สำหรับ vector similarity search (ivfflat)
create index if not exists idx_mahbin_npk_embedding
    on mahbin_npk using ivfflat (embedding vector_cosine_ops)
    with (lists = 5);

-- Index สำหรับ full-text search
create index if not exists idx_mahbin_npk_search_vector
    on mahbin_npk using gin (search_vector);

-- Index สำหรับ filter by crop
create index if not exists idx_mahbin_npk_crop
    on mahbin_npk (crop);

-- Auto-generate search_vector เมื่อ insert/update
create or replace function mahbin_npk_search_vector_trigger()
returns trigger as $$
begin
    new.search_vector := to_tsvector('simple',
        coalesce(new.crop, '') || ' ' ||
        coalesce(new.growth_stage, '') || ' ' ||
        coalesce(new.fertilizer_formula, '') || ' ' ||
        coalesce(new.primary_nutrients, '') || ' ' ||
        coalesce(new.benefits, '')
    );
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_mahbin_npk_search_vector on mahbin_npk;
create trigger trg_mahbin_npk_search_vector
    before insert or update on mahbin_npk
    for each row execute function mahbin_npk_search_vector_trigger();
