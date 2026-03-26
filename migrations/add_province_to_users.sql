-- Add province column to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS province TEXT;

-- Comment on column
COMMENT ON COLUMN users.province IS 'จังหวัดที่เกษตรกรอาศัยอยู่';
