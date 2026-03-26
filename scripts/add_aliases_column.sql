-- Add aliases column to products table for product nicknames/aliases.
-- Run this in Supabase SQL Editor.
-- Format: comma-separated Thai aliases, e.g. "กล่องเขียว, เขียวพุ่งไว, ชุดเขียว"
ALTER TABLE products ADD COLUMN IF NOT EXISTS aliases text;
