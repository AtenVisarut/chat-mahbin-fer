"""
Update import script to include usage_period field
This script shows how to import CSV with the new usage_period column
"""
import os
import csv
import json
import sys
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def import_csv_with_usage_period(csv_path: str):
    """Import CSV data to Supabase WITH usage_period field"""
    
    print("=" * 60)
    print("Import CSV to Supabase (with usage_period)")
    print("=" * 60)
    
    # Initialize Supabase client
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    print(f"\n1. Reading CSV file: {csv_path}")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    print(f"✓ Found {len(rows)} products")
    
    success_count = 0
    error_count = 0
    
    print("\n2. Processing products...")
    
    for idx, row in enumerate(rows, 1):
        try:
            # Extract key fields
            product_name = row.get('ชื่อสินค้า (ชื่อการค้า)', '').strip()
            if not product_name:
                print(f"[{idx}/{len(rows)}] Skipping - no product name")
                continue
            
            active_ingredient = row.get('สารสําคัญ', '').strip()
            target_pest = row.get('ศัตรูพืชที่กำจัดได้', '').strip()
            applicable_crops = row.get('ใช้ได้กับพืช', '').strip()
            how_to_use = row.get('วิธีใช้', '').strip()
            usage_period = row.get('ช่วงการใช้', '').strip()  # NEW FIELD
            product_group = row.get('กลุ่มสาร', '').strip()
            formulation = row.get('Formulation', '').strip()
            usage_rate = row.get('อัตราการใช้', '').strip()
            
            print(f"[{idx}/{len(rows)}] {product_name}")
            
            # Prepare data for Supabase
            data = {
                'product_name': product_name,
                'active_ingredient': active_ingredient,
                'target_pest': target_pest,
                'applicable_crops': applicable_crops,
                'how_to_use': how_to_use,
                'usage_period': usage_period,  # NEW FIELD
                'product_group': product_group,
                'formulation': formulation,
                'usage_rate': usage_rate,
                'metadata': json.dumps(row, ensure_ascii=False)
            }
            
            # Insert to Supabase
            result = supabase.table('products').insert(data).execute()
            
            print(f"  ✓ Success!")
            success_count += 1
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            error_count += 1
            continue
    
    print("\n" + "=" * 60)
    print(f"Import completed!")
    print(f"✓ Success: {success_count}")
    print(f"✗ Errors: {error_count}")
    print("=" * 60)
    
    if success_count > 0:
        print("\n✅ Products imported successfully with usage_period!")
        print("   You can now use the new field in your queries")
    else:
        print("\n❌ No products were imported")

if __name__ == "__main__":
    # Check if CSV path provided as argument
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    else:
        csv_file = "Data ICPL product for iDA.csv"
    
    if not os.path.exists(csv_file):
        print(f"Error: CSV file not found: {csv_file}")
        print(f"Usage: python {sys.argv[0]} <path_to_csv>")
        exit(1)
    
    print("Starting CSV import with usage_period to Supabase...")
    print("=" * 60)
    
    import_csv_with_usage_period(csv_file)
