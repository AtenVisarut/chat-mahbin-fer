-- ============================================================================
-- Table: user_fer(LINE,FACE)
-- User tracking สำหรับ LINE และ Facebook Messenger
-- ============================================================================
--
-- ใช้โดย:
--   - app/services/user_service.py  (register_user_fer, ensure_user_exists)
--
-- Flow:
--   User ส่งข้อความ → webhook → ensure_user_exists()
--   → register_user_fer(user_id, display_name)
--     → User ใหม่: INSERT
--     → User เดิม: UPDATE display_name + updated_at
--
-- หมายเหตุ:
--   ชื่อ table มีวงเล็บเพราะรวม LINE + Facebook ไว้ table เดียว
--   line_user_id เก็บทั้ง LINE user ID (Uxxxxx) และ Facebook PSID (fb:xxxxx)

create table if not exists "user_fer(LINE,FACE)" (
    id              bigint generated always as identity primary key,
    line_user_id    text unique,                -- LINE: Uxxxxxxx / Facebook: fb:xxxxxxx
    display_name    text,                       -- ชื่อจาก LINE/FB Profile API
    created_at      timestamptz default now(),  -- วันที่เข้ามาครั้งแรก
    updated_at      timestamptz                 -- วันที่ส่งข้อความล่าสุด
);

-- Index สำหรับ lookup by user ID (unique constraint สร้าง index ให้แล้ว)
-- แต่เพิ่ม explicit index เผื่อ unique constraint ไม่ได้สร้าง
create index if not exists idx_user_fer_line_user_id
    on "user_fer(LINE,FACE)" (line_user_id);
