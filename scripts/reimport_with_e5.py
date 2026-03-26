"""
Re-import CSV with E5 embeddings (768 dimensions)
This is FREE and works offline!
"""
import os
import csv
import json
import sys
from dotenv import load_dotenv
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
import time

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def reimport_with_e5(csv_path: str):
    """Re-import CSV data with E5 embeddings"""
    
    print("=" * 60)
    print("Re-import CSV with E5 Embeddings (768 dim)")
    print("=" * 60)
    
    # Initialize E5 model
    print("\n1. Loading E5 model...")
    e5_model = SentenceTransformer('intfloat/multilingual-e5-base')
    print("✓ E5 model loaded (768 dimensions)")
    
    # Initialize Supabase
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    print(f"\n2. Reading CSV file: {csv_path}")
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    print(f"✓ Found {len(rows)} products")
    
    # Clear existing products
    print("\n3. Clearing existing products...")
    try:
        supabase.table('products').delete().neq('id', 0).execute()
        print("✓ Existing products cleared")
    except Exception as e:
        print(f"⚠️ Warning: {e}")
    
    success_count = 0
    error_count = 0
    
    print("\n4. Processing products with E5 embeddings...")
    
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
            usage_period = row.get('ช่วงการใช้', '').strip()
            product_group = row.get('กลุ่มสาร', '').strip()
            formulation = row.get('Formulation', '').strip()
            usage_rate = row.get('อัตราการใช้', '').strip()
            
            print(f"[{idx}/{len(rows)}] {product_name}")
            
            # Build text for embedding (E5 requires "passage: " prefix)
            embedding_parts = [
                f"ชื่อสินค้า: {product_name}",
                f"สารสำคัญ: {active_ingredient}" if active_ingredient else "",
                f"ศัตรูพืชที่กำจัดได้: {target_pest}" if target_pest else "",
                f"ใช้ได้กับพืช: {applicable_crops}" if applicable_crops else "",
                f"กลุ่มสาร: {product_group}" if product_group else "",
            ]
            
            embedding_text = "passage: " + " | ".join([p for p in embedding_parts if p]).strip()
            
            # Generate E5 embedding
            embedding = e5_model.encode(embedding_text, normalize_embeddings=True).tolist()
            print(f"  → Embedding: {len(embedding)} dimensions")
            
            # Prepare data for Supabase
            data = {
                'product_name': product_name,
                'active_ingredient': active_ingredient,
                'target_pest': target_pest,
                'applicable_crops': applicable_crops,
                'how_to_use': how_to_use,
                'usage_period': usage_period,
                'product_group': product_group,
                'formulation': formulation,
                'usage_rate': usage_rate,
                'metadata': json.dumps(row, ensure_ascii=False),
                'embedding': embedding
            }
            
            # Insert to Supabase
            result = supabase.table('products').insert(data).execute()
            
            print(f"  ✓ Success!")
            success_count += 1
            
            # Small delay to avoid overwhelming the system
            time.sleep(0.1)
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            error_count += 1
            continue
    
    print("\n" + "=" * 60)
    print(f"Re-import completed!")
    print(f"✓ Success: {success_count}")
    print(f"✗ Errors: {error_count}")
    print("=" * 60)
    
    if success_count > 0:
        print("\n✅ Products re-imported with E5 embeddings!")
        print("   Next steps:")
        print("   1. Update RPC function: scripts/create_match_products_function.sql")
        print("   2. Test: python scripts/test_match_products_function.py")
        print("   3. Start server: python app/main.py")
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
    
    print("⚠️ WARNING: This will DELETE all existing products!")
    print("Press Ctrl+C to cancel, or Enter to continue...")
    try:
        input()
    except KeyboardInterrupt:
        print("\nCancelled.")
        exit(0)
    
    reimport_with_e5(csv_file)
