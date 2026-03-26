"""
Script: Regenerate embeddings for ALL products in Supabase
Uses same logic as /admin/regenerate-embeddings endpoint

Usage:
    python scripts/regenerate_all_embeddings.py
"""
import sys
import os
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.chdir("C:\\clone_chatbot_ick\\Chatbot-ladda")
sys.path.insert(0, "C:\\clone_chatbot_ick\\Chatbot-ladda")

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from app.config import OPENAI_API_KEY, EMBEDDING_MODEL
from app.dependencies import supabase_client

openai_client = OpenAI(api_key=OPENAI_API_KEY)


def generate_embedding(text: str) -> list:
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return response.data[0].embedding


def build_embedding_text(product: dict) -> str:
    """Build embedding text from product fields (same as /admin/regenerate-embeddings)"""
    text_parts = [
        f"ชื่อสินค้า: {product['product_name']}",
        f"สารสำคัญ: {product.get('active_ingredient', '')}",
        f"ศัตรูพืชที่กำจัดได้: {product.get('target_pest', '')}",
        f"ใช้ได้กับพืช: {product.get('applicable_crops', '')}",
        f"กลุ่มสาร: {product.get('product_group', '')}",
        f"ความเป็นพิษต่อพืช: {product.get('phytotoxicity', '')}",
    ]
    return " | ".join([p for p in text_parts if p])


def main():
    print("=" * 70)
    print("REGENERATE ALL PRODUCT EMBEDDINGS")
    print(f"Model: {EMBEDDING_MODEL}")
    print("=" * 70)

    # 1. Count and fetch all products
    result = supabase_client.table('products').select('*').execute()

    if not result.data:
        print("ERROR: No products found!")
        return

    products = result.data
    print(f"\nTotal products: {len(products)}")

    # Show product list
    print(f"\n{'ID':<6} {'Product Name':<30} {'Has Embedding'}")
    print("-" * 60)
    for p in products:
        has_emb = "Yes" if p.get('embedding') else "No"
        print(f"{p['id']:<6} {p['product_name']:<30} {has_emb}")

    print(f"\n{'=' * 70}")
    print(f"Starting regeneration for {len(products)} products...")
    print(f"{'=' * 70}\n")

    success_count = 0
    errors = []
    t0 = time.time()

    for i, product in enumerate(products, 1):
        try:
            text = build_embedding_text(product)
            print(f"[{i}/{len(products)}] {product['product_name']}")
            print(f"  Text: {text[:100]}...")

            embedding = generate_embedding(text)
            print(f"  Embedding: {len(embedding)} dimensions")

            supabase_client.table('products').update({
                'embedding': embedding
            }).eq('id', product['id']).execute()

            print(f"  Updated!")
            success_count += 1

        except Exception as e:
            error_msg = f"{product['product_name']}: {str(e)}"
            errors.append(error_msg)
            print(f"  ERROR: {e}")

    elapsed = time.time() - t0

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"Total products: {len(products)}")
    print(f"Success: {success_count}")
    print(f"Errors: {len(errors)}")
    print(f"Time: {elapsed:.1f}s")

    if errors:
        print(f"\nErrors:")
        for e in errors:
            print(f"  - {e}")

    print(f"\n{'=' * 70}")
    print("DONE")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
