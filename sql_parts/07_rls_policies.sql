-- ============================================================================
-- RLS (Row Level Security) Policies
-- ============================================================================
--
-- Supabase ใช้ anon key สำหรับ API calls
-- ต้องตั้ง RLS policy ให้ anon อ่าน/เขียนได้ตาม table
--
-- สำคัญ: ถ้า RLS เปิดแต่ไม่มี policy → query จะได้ 0 rows
-- (เคยเป็น bug ที่ dealers table — RLS เปิดแต่ไม่มี SELECT policy)

-- ============================================================================
-- mahbin_npk — อ่านได้อย่างเดียว (bot ไม่ต้องเขียน, admin เขียนผ่าน service key)
-- ============================================================================
alter table mahbin_npk enable row level security;

create policy "Allow public read mahbin_npk"
    on mahbin_npk for select
    using (true);

-- ============================================================================
-- dealers — อ่านได้อย่างเดียว
-- ============================================================================
alter table dealers enable row level security;

create policy "Allow public read dealers"
    on dealers for select
    using (true);

-- ============================================================================
-- user_fer(LINE,FACE) — อ่าน + เขียน (bot ต้อง insert/update user)
-- ============================================================================
alter table "user_fer(LINE,FACE)" enable row level security;

create policy "Allow public read user_fer"
    on "user_fer(LINE,FACE)" for select
    using (true);

create policy "Allow public insert user_fer"
    on "user_fer(LINE,FACE)" for insert
    with check (true);

create policy "Allow public update user_fer"
    on "user_fer(LINE,FACE)" for update
    using (true);

-- ============================================================================
-- conver_mem_doccrop — อ่าน + เขียน + ลบ (memory management)
-- ============================================================================
alter table conver_mem_doccrop enable row level security;

create policy "Allow public read conver_mem"
    on conver_mem_doccrop for select
    using (true);

create policy "Allow public insert conver_mem"
    on conver_mem_doccrop for insert
    with check (true);

create policy "Allow public delete conver_mem"
    on conver_mem_doccrop for delete
    using (true);

-- ============================================================================
-- cache — อ่าน + เขียน + ลบ (cache management)
-- ============================================================================
alter table cache enable row level security;

create policy "Allow public read cache"
    on cache for select
    using (true);

create policy "Allow public insert cache"
    on cache for insert
    with check (true);

create policy "Allow public update cache"
    on cache for update
    using (true);

create policy "Allow public delete cache"
    on cache for delete
    using (true);
