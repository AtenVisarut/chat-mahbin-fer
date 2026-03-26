-- SQL script to add pathogen_type column to products table
-- Run this in Supabase SQL Editor

-- Step 1: Add pathogen_type column
ALTER TABLE products ADD COLUMN IF NOT EXISTS pathogen_type TEXT;

-- Step 2: Create index for faster filtering
CREATE INDEX IF NOT EXISTS idx_products_pathogen_type ON products(pathogen_type);

-- Step 3: Add comment for documentation
COMMENT ON COLUMN products.pathogen_type IS 'Type of pathogen/pest this product targets: oomycetes, fungi, bacteria, insect, herbicide, pgr, fertilizer';
