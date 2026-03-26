-- ============================================================================
-- Table: conver_mem_mahbin
-- ประวัติสนทนา (conversation memory) เก็บข้อความ user + assistant
-- ============================================================================
--
-- ใช้โดย:
--   - app/services/memory.py  (add_to_memory, get_conversation_context,
--                               get_enhanced_context, cleanup_old_memory, etc.)
--
-- Flow:
--   User ส่งข้อความ → add_to_memory(user_id, "user", message)
--   Bot ตอบ         → add_to_memory(user_id, "assistant", answer)
--   ถามคำถามใหม่     → get_enhanced_context(user_id) ดึง 10 ข้อความล่าสุด
--   cleanup          → เก็บแค่ 50 ข้อความล่าสุดต่อ user (MAX_MEMORY_MESSAGES)
--
-- metadata ใช้เก็บข้อมูลเพิ่มเติม เช่น:
--   {"type": "product_recommendation", "products": [...]}

create table if not exists conver_mem_mahbin (
    id              bigint generated always as identity primary key,
    user_id         text not null,              -- LINE user ID หรือ fb:xxxxx
    role            text not null,              -- 'user' หรือ 'assistant'
    content         text not null,              -- ข้อความ (ตัดที่ 2000 ตัวอักษร)
    metadata        jsonb default '{}'::jsonb,  -- ข้อมูลเพิ่มเติม
    created_at      timestamptz default now()
);

-- Index สำหรับดึงข้อความตาม user (เรียงตามเวลา)
create index if not exists idx_conver_mem_user_created
    on conver_mem_mahbin (user_id, created_at desc);

-- Index สำหรับ cleanup (ลบข้อความเก่า)
create index if not exists idx_conver_mem_user_id
    on conver_mem_mahbin (user_id);
