-- Add additional fields to users table for LIFF registration
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS address TEXT,
ADD COLUMN IF NOT EXISTS crops_grown TEXT[],
ADD COLUMN IF NOT EXISTS province TEXT,
ADD COLUMN IF NOT EXISTS registration_completed BOOLEAN DEFAULT FALSE;

-- Create index for registration_completed
CREATE INDEX IF NOT EXISTS idx_users_registration_completed ON users(registration_completed);

-- Add comments
COMMENT ON COLUMN users.address IS 'User address (from LIFF form)';
COMMENT ON COLUMN users.crops_grown IS 'Array of crops the user grows';
COMMENT ON COLUMN users.province IS 'User province';
COMMENT ON COLUMN users.registration_completed IS 'Whether user completed LIFF registration';
