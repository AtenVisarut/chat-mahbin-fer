-- สร้างตาราง dealers สำหรับเก็บข้อมูลตัวแทนจำหน่ายม้าบิน
CREATE TABLE IF NOT EXISTS dealers (
    id BIGSERIAL PRIMARY KEY,
    dealer_name TEXT NOT NULL,
    zone TEXT,
    province TEXT NOT NULL,
    district TEXT,
    subdistrict TEXT,
    phone TEXT,
    dealer_type TEXT NOT NULL,  -- 'Dealer' / 'Sub Dealer'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dealers_province ON dealers(province);
CREATE INDEX IF NOT EXISTS idx_dealers_type ON dealers(dealer_type);
