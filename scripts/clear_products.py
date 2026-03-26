"""
Clear all products from Supabase
"""
import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def clear_products():
    """Delete all products from database"""
    try:
        print("Clearing all products from database...")
        
        # Delete all rows
        response = supabase.table('products').delete().neq('id', 0).execute()
        
        print("✓ All products cleared successfully!")
        
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    confirm = input("Are you sure you want to delete all products? (yes/no): ")
    if confirm.lower() == 'yes':
        clear_products()
    else:
        print("Cancelled.")
