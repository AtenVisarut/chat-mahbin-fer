-- ============================================================================
-- Table: dealers
-- ตัวแทนจำหน่ายปุ๋ย ICP ทั่วประเทศ (414 rows)
-- ============================================================================
--
-- ใช้โดย:
--   - app/services/dealer_lookup.py  (search by province/district/subdistrict)
--
-- Flow:
--   User ถาม "หาร้านค้าจังหวัดขอนแก่น"
--   → dealer_lookup.py → search_dealers(province="ขอนแก่น")
--   → query dealers table filter by province + dealer_type

create table if not exists dealers (
    id              bigint generated always as identity primary key,
    dealer_name     text not null,              -- ชื่อร้าน/บริษัท
    zone            text,                       -- โซน เช่น C01, C02, N01
    province        text not null,              -- จังหวัด เช่น เพชรบูรณ์, ขอนแก่น
    district        text,                       -- อำเภอ
    subdistrict     text,                       -- ตำบล
    phone           text,                       -- เบอร์โทร
    dealer_type     text default 'Dealer',      -- ประเภท: 'Dealer' หรือ 'Sub Dealer'
    created_at      timestamptz default now()
);

-- Index สำหรับค้นหาตามจังหวัด
create index if not exists idx_dealers_province
    on dealers (province);

-- Index สำหรับค้นหาตามประเภท
create index if not exists idx_dealers_type
    on dealers (dealer_type);

-- Composite index สำหรับ query ที่ filter ทั้ง province + dealer_type
create index if not exists idx_dealers_province_type
    on dealers (province, dealer_type);
