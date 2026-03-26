"""
Generate embeddings for all products in Supabase
Only needed if you want to use Vector Search
"""
import os
import sys
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI
import time

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def generate_embedding(text: str, openai_client: OpenAI) -> list:
    """Generate embedding using OpenAI"""
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None

def generate_embeddings_for_products():
    """Generate embeddings for all products"""
    
    print("=" * 60)
    print("Generating Embeddings for Products")
    print("=" * 60)
    
    # Initialize clients
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Fetch all products
    print("\n1. Fetching products from Supabase...")
    response = supabase.table('products').select('*').execute()
    products = response.data
    print(f"✓ Found {len(products)} products")
    
    # Generate embeddings
    print("\n2. Generating embeddings...")
    success_count = 0
    error_count = 0
    
    for idx, product in enumerate(products, 1):
        try:
            # Build text for embedding
            text_parts = [
                f"ชื่อสินค้า: {product['product_name']}",
                f"สารสำคัญ: {product.get('active_ingredient', '')}",
                f"ศัตรูพืชที่กำจัดได้: {product.get('target_pest', '')}",
                f"ใช้ได้กับพืช: {product.get('applicable_crops', '')}",
                f"กลุ่มสาร: {product.get('product_group', '')}",
            ]
            text = " | ".join([p for p in text_parts if p])
            
            print(f"[{idx}/{len(products)}] {product['product_name']}")
            
            # Generate embedding
            embedding = generate_embedding(text, openai_client)
            
            if not embedding:
                print(f"  ✗ Failed to generate embedding")
                error_count += 1
                continue
            
            # Update product with embedding
            supabase.table('products').update({
                'embedding': embedding
            }).eq('id', product['id']).execute()
            
            print(f"  ✓ Embedding generated and saved")
            success_count += 1
            
            # Rate limiting (OpenAI has rate limits)
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            error_count += 1
            continue
    
    print("\n" + "=" * 60)
    print(f"Embeddings generation completed!")
    print(f"Success: {success_count}")
    print(f"Errors: {error_count}")
    print("=" * 60)
    
    if success_count > 0:
        print("\n✓ You can now use Vector Search!")
        print("  Update main.py to use vector similarity search")
    else:
        print("\n✗ No embeddings were generated")
        print("  Continue using Keyword Search instead")

if __name__ == "__main__":
    try:
        generate_embeddings_for_products()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
