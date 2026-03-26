"""
Diagnose and fix embedding issues
"""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def diagnose():
    print("=" * 60)
    print("Diagnosing Embedding Issues")
    print("=" * 60)
    
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Check embedding dimensions
    print("\n1. Checking embedding dimensions...")
    result = supabase.table('products').select('product_name, embedding').limit(5).execute()
    
    if result.data:
        for p in result.data:
            emb = p.get('embedding')
            if emb:
                print(f"   {p.get('product_name')}: {len(emb)} dimensions")
            else:
                print(f"   {p.get('product_name')}: No embedding")
    
    # Check if embeddings are corrupted
    print("\n2. Checking for corrupted embeddings...")
    all_products = supabase.table('products').select('id, product_name, embedding').execute()
    
    corrupted = []
    no_embedding = []
    valid_768 = []
    valid_1536 = []
    other_dims = []
    
    for p in all_products.data:
        emb = p.get('embedding')
        if not emb:
            no_embedding.append(p)
        elif len(emb) == 768:
            valid_768.append(p)
        elif len(emb) == 1536:
            valid_1536.append(p)
        else:
            other_dims.append((p, len(emb)))
    
    print(f"\n   Products without embeddings: {len(no_embedding)}")
    print(f"   Products with 768-dim embeddings: {len(valid_768)}")
    print(f"   Products with 1536-dim embeddings: {len(valid_1536)}")
    print(f"   Products with other dimensions: {len(other_dims)}")
    
    if other_dims:
        print("\n   ⚠️ Found products with unusual dimensions:")
        for p, dim in other_dims[:5]:
            print(f"      {p.get('product_name')}: {dim} dimensions")
    
    # Recommendations
    print("\n" + "=" * 60)
    print("RECOMMENDATIONS:")
    print("=" * 60)
    
    if len(other_dims) > 0:
        print("\n❌ PROBLEM: Embeddings have wrong dimensions!")
        print("   This happens when embeddings are stored as text instead of vector.")
        print("\n   SOLUTION:")
        print("   1. Clear all products: python scripts/clear_products.py")
        print("   2. Re-import with correct embeddings:")
        print("      - For E5 (768-dim): Use E5 model to generate embeddings")
        print("      - For OpenAI (1536-dim): python scripts/import_with_embeddings.py")
    elif len(valid_768) > 0:
        print("\n✅ Embeddings are 768-dimensional (E5 model)")
        print("   Make sure to use E5 model in your code (already configured)")
        print("   Update RPC function: scripts/create_match_products_function.sql")
    elif len(valid_1536) > 0:
        print("\n✅ Embeddings are 1536-dimensional (OpenAI)")
        print("   Update RPC function: scripts/fix_match_products_1536.sql")
    else:
        print("\n⚠️ No embeddings found!")
        print("   Run: python scripts/import_with_embeddings.py")

if __name__ == "__main__":
    try:
        diagnose()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
