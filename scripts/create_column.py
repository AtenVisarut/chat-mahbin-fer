"""
Script to create pathogen_type column in Supabase
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Try to execute SQL via rpc
sql = """
ALTER TABLE products ADD COLUMN IF NOT EXISTS pathogen_type TEXT;
"""

try:
    # Supabase client doesn't support raw SQL directly
    # We need to use the REST API with service role key
    print("Cannot run ALTER TABLE via Supabase client.")
    print("\nPlease run this SQL in Supabase Dashboard SQL Editor:")
    print("=" * 60)
    print("""
ALTER TABLE products ADD COLUMN IF NOT EXISTS pathogen_type TEXT;
CREATE INDEX IF NOT EXISTS idx_products_pathogen_type ON products(pathogen_type);
    """)
    print("=" * 60)
    print("\nAfter running the SQL, execute:")
    print("  python scripts/add_pathogen_type.py --auto")
except Exception as e:
    print(f"Error: {e}")
