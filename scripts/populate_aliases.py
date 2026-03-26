"""
Populate `aliases` column in products table + regenerate embeddings.

Usage:
    python scripts/populate_aliases.py              # aliases only
    python scripts/populate_aliases.py --regen      # aliases + regen embeddings

Reads .env automatically for SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY.
"""
import argparse
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from app.services.product.registry import _FALLBACK_PRODUCTS, _generate_thai_variants


def populate_aliases(client):
    """Update aliases column for all products in DB using ILIKE matching."""
    print("=" * 60)
    print("STEP 1: Populate aliases")
    print("=" * 60)

    updated = 0
    not_found = 0
    skipped = 0

    for product_name, hand_aliases in sorted(_FALLBACK_PRODUCTS.items()):
        auto_variants = set(_generate_thai_variants(product_name))

        # Extra aliases = hand-crafted ones that auto-generation doesn't produce
        extra = [a for a in hand_aliases if a.lower() not in auto_variants]
        if not extra:
            skipped += 1
            continue

        aliases_str = ", ".join(extra)

        try:
            # Try exact match first
            result = client.table('products').update(
                {"aliases": aliases_str}
            ).eq('product_name', product_name).execute()

            if result.data:
                print(f"  [OK] {product_name}: {aliases_str}")
                updated += 1
                continue

            # Fallback: ILIKE match (e.g. "กะรัต" → "กะรัต 35")
            result = client.table('products').update(
                {"aliases": aliases_str}
            ).ilike('product_name', f'%{product_name}%').execute()

            if result.data:
                matched = [r['product_name'] for r in result.data]
                print(f"  [OK-ILIKE] {product_name} → {matched}: {aliases_str}")
                updated += 1
            else:
                print(f"  [NOT IN DB] {product_name}: {aliases_str}")
                not_found += 1
        except Exception as e:
            print(f"  [ERR] {product_name}: {e}")

    print(f"\nAliases done. Updated: {updated}, Not in DB: {not_found}, Skipped (auto-only): {skipped}")
    return updated


def regen_embeddings(client):
    """Regenerate embeddings for ALL products."""
    print("\n" + "=" * 60)
    print("STEP 2: Regenerate embeddings")
    print("=" * 60)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set, skipping embedding regen")
        return 0

    from openai import OpenAI
    openai_client = OpenAI(api_key=api_key)

    embedding_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

    # Fetch all products
    result = client.table('products').select('*').execute()
    if not result.data:
        print("  No products found in DB!")
        return 0

    products = result.data
    print(f"  Found {len(products)} products to process\n")

    success = 0
    errors = []

    for product in products:
        name = product['product_name']
        try:
            text_parts = [
                f"ชื่อสินค้า: {name}",
                f"สารสำคัญ: {product.get('active_ingredient', '')}",
                f"ศัตรูพืชที่กำจัดได้: {product.get('target_pest', '')}",
                f"ใช้ได้กับพืช: {product.get('applicable_crops', '')}",
                f"กลุ่มสาร: {product.get('product_group', '')}",
            ]
            text = " | ".join([p for p in text_parts if p])

            resp = openai_client.embeddings.create(
                model=embedding_model,
                input=text
            )
            embedding = resp.data[0].embedding

            client.table('products').update({
                'embedding': embedding
            }).eq('id', product['id']).execute()

            success += 1
            print(f"  [OK] {name}")
        except Exception as e:
            errors.append(name)
            print(f"  [ERR] {name}: {e}")

    print(f"\nEmbeddings done. Success: {success}/{len(products)}")
    if errors:
        print(f"  Errors: {', '.join(errors)}")
    return success


def main():
    parser = argparse.ArgumentParser(description="Populate aliases + optionally regen embeddings")
    parser.add_argument("--regen", action="store_true", help="Also regenerate embeddings")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY (in .env or env vars)")
        sys.exit(1)

    client = create_client(url, key)

    # Step 1: Populate aliases
    populate_aliases(client)

    # Step 2: Regen embeddings (optional)
    if args.regen:
        regen_embeddings(client)
    else:
        print("\nSkipping embedding regen (use --regen to include)")

    print("\nAll done!")


if __name__ == "__main__":
    main()
