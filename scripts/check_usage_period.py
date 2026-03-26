"""
Check if usage_period column exists and has data
"""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def check_usage_period():
    print("=" * 60)
    print("Checking usage_period column in Supabase")
    print("=" * 60)
    
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Check if data exists
    print("\n1. Checking products table...")
    result = supabase.table('products').select('product_name, usage_period, usage_rate').limit(10).execute()
    
    if result.data:
        print(f"✓ Found {len(result.data)} products")
        print("\nSample data:")
        for idx, p in enumerate(result.data, 1):
            print(f"\n[{idx}] {p.get('product_name', 'N/A')}")
            print(f"    usage_period: {p.get('usage_period', 'NULL')}")
            print(f"    usage_rate: {p.get('usage_rate', 'NULL')}")
    else:
        print("✗ No products found")
        return
    
    # Check statistics
    print("\n2. Statistics:")
    all_products = supabase.table('products').select('usage_period').execute()
    total = len(all_products.data)
    with_usage_period = sum(1 for p in all_products.data if p.get('usage_period'))
    
    print(f"   Total products: {total}")
    print(f"   With usage_period: {with_usage_period}")
    print(f"   Percentage: {with_usage_period * 100.0 / total if total > 0 else 0:.1f}%")
    
    if with_usage_period == 0:
        print("\n⚠️ WARNING: No products have usage_period data!")
        print("   You need to re-import the CSV data.")
        print("   Run: python scripts/update_import_script_usage_period.py")
    else:
        print("\n✅ usage_period column has data!")

if __name__ == "__main__":
    try:
        check_usage_period()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
