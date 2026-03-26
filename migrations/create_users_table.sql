-- Create users table for LINE user profile tracking
CREATE TABLE IF NOT EXISTS users (
    line_user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    picture_url TEXT,
    status_message TEXT,
    phone_number TEXT,  -- For future LIFF form integration
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    total_interactions INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_users_line_user_id ON users(line_user_id);

-- Create index for last_seen_at for activity tracking
CREATE INDEX IF NOT EXISTS idx_users_last_seen_at ON users(last_seen_at DESC);

-- Comment on table
COMMENT ON TABLE users IS 'Stores LINE user profile information and activity tracking';

-- Comments on columns
COMMENT ON COLUMN users.line_user_id IS 'LINE User ID (primary key)';
COMMENT ON COLUMN users.display_name IS 'Display name from LINE profile';
COMMENT ON COLUMN users.picture_url IS 'Profile picture URL from LINE';
COMMENT ON COLUMN users.status_message IS 'Status message from LINE profile';
COMMENT ON COLUMN users.phone_number IS 'Phone number (optional, from LIFF form)';
COMMENT ON COLUMN users.first_seen_at IS 'First time user interacted with bot';
COMMENT ON COLUMN users.last_seen_at IS 'Last time user interacted with bot';
COMMENT ON COLUMN users.total_interactions IS 'Total number of interactions';
