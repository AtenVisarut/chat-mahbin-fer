-- ============================================================================
-- Table: cache
-- L2 Cache (Supabase) — key-value store พร้อม TTL
-- ============================================================================
--
-- ใช้โดย:
--   - app/services/cache.py  (get_from_cache, set_to_cache, delete_from_cache,
--                              cleanup_expired_cache)
--
-- Architecture:
--   L1 = In-Memory cache (เร็ว ~0.1ms, หายเมื่อ restart)
--   L2 = Supabase cache (ช้ากว่า ~50-200ms, แต่ persist)
--
--   get: L1 hit? → return / L1 miss → check L2 → populate L1
--   set: write L1 + L2 พร้อมกัน
--
-- key format: "{type}:{hash}"
--   เช่น response:5f5d0711..., context:Uxxxxxxx

create table if not exists cache (
    key             text primary key,           -- cache key เช่น response:xxxx
    value           jsonb,                      -- cached data (any JSON)
    expires_at      timestamptz not null         -- หมดอายุเมื่อไร
);

-- Index สำหรับ cleanup expired entries
create index if not exists idx_cache_expires
    on cache (expires_at);
