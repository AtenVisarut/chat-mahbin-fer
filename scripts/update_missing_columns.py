"""
Script อัพเดต 10 columns ใหม่ใน Supabase products จากข้อมูล CSV
แล้ว regenerate embeddings ด้วย fields เพิ่มเติม

วิธีใช้:
1. รัน SQL script add_missing_columns.sql ใน Supabase SQL Editor ก่อน
2. รัน script นี้: python scripts/update_missing_columns.py
"""
import os
import sys
import csv
import time

# Fix Windows console encoding for Thai text
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Missing SUPABASE_URL or SUPABASE_KEY in .env file")
    exit(1)

if not OPENAI_API_KEY:
    print("Error: Missing OPENAI_API_KEY in .env file")
    exit(1)

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# CSV column name → Supabase column name
CSV_TO_SUPABASE = {
    "ขนาดบรรจุ": "package_size",
    "ชื่อสาร": "common_name_th",
    "ลักษณะกายภาพ": "physical_form",
    "คุณสมบัติเด่น (Selling point)": "selling_point",
    "การดูดซึมเข้าสู่พืช": "absorption_method",
    "กลไกการออกฤทธิ์": "mechanism_of_action",
    "ลักษณะการออกฤทธิ์": "action_characteristics",
    "ความเป็นพิษต่อพืชประธ": "phytotoxicity",
    "แถบสีข้างฉลาก": "label_color_band",
    "วันทะเบียนหมดอายุ": "registration_expiry",
}

CSV_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "ICP Ladda Product Detail_rows.csv")


def load_csv_data():
    """โหลดข้อมูลจาก CSV เป็น dict keyed by ProductName"""
    csv_data = {}
    try:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                product_name = row.get('ProductName', '').strip()
                if product_name:
                    csv_data[product_name] = row
        print(f"โหลดข้อมูลจาก CSV: {len(csv_data)} รายการ")
        return csv_data
    except FileNotFoundError:
        print(f"ไม่พบไฟล์ {CSV_FILE}")
        return {}
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return {}


def match_product(product_name, csv_data):
    """Match product_name กับ CSV data: exact → strip → partial"""
    # Exact match
    if product_name in csv_data:
        return product_name, csv_data[product_name]

    # Strip match
    for csv_name, row in csv_data.items():
        if csv_name.strip() == product_name.strip():
            return csv_name, row

    # Partial match
    for csv_name, row in csv_data.items():
        if csv_name in product_name or product_name in csv_name:
            return csv_name, row

    return None, None


def step1_preview_match(products, csv_data):
    """Step 1: Preview match (read-only)"""
    print("\n" + "=" * 60)
    print("Step 1: Preview Match")
    print("=" * 60)

    matched = []
    not_found = []

    for product in products:
        product_name = product['product_name']
        csv_name, csv_row = match_product(product_name, csv_data)

        if csv_row:
            matched.append((product, csv_name, csv_row))
            print(f"  [MATCH] {product_name} <-> {csv_name}")
        else:
            not_found.append(product)
            print(f"  [NOT FOUND] {product_name}")

    print(f"\nสรุป: matched {len(matched)}/{len(products)}, not found {len(not_found)}")

    if not_found:
        print(f"\nรายการที่ match ไม่ได้ ({len(not_found)}):")
        for p in not_found:
            print(f"  - {p['product_name']}")
        print("(จะข้ามรายการเหล่านี้)")

    return matched, not_found


def step2_update_columns(matched):
    """Step 2: UPDATE 10 columns"""
    print("\n" + "=" * 60)
    print("Step 2: Update 10 Columns")
    print("=" * 60)

    updated = 0
    skipped = 0
    errors = 0

    for idx, (product, csv_name, csv_row) in enumerate(matched, 1):
        product_id = product['id']
        product_name = product['product_name']

        # Build update data from CSV
        update_data = {}
        for csv_col, db_col in CSV_TO_SUPABASE.items():
            value = csv_row.get(csv_col, '').strip()
            if value:
                update_data[db_col] = value

        if not update_data:
            print(f"[{idx}/{len(matched)}] {product_name} -> Skipped (no data)")
            skipped += 1
            continue

        try:
            supabase.table('products').update(update_data).eq('id', product_id).execute()
            print(f"[{idx}/{len(matched)}] {product_name} -> Updated {len(update_data)} columns")
            updated += 1
        except Exception as e:
            print(f"[{idx}/{len(matched)}] {product_name} -> Error: {e}")
            errors += 1

    print(f"\nสรุป Step 2: updated {updated}, skipped {skipped}, errors {errors}")
    return updated


def generate_embedding(text):
    """Generate embedding using OpenAI text-embedding-3-small"""
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"  Error generating embedding: {e}")
        return None


def step3_regenerate_embeddings():
    """Step 3: Regenerate embeddings with 8 fields (เดิม 5 + ใหม่ 3)"""
    print("\n" + "=" * 60)
    print("Step 3: Regenerate Embeddings (8 fields)")
    print("=" * 60)

    # Fetch all products with new columns
    try:
        result = supabase.table('products').select('*').execute()
        products = result.data
        print(f"พบสินค้า: {len(products)} รายการ")
    except Exception as e:
        print(f"Error fetching products: {e}")
        return

    regenerated = 0
    failed = 0

    for idx, product in enumerate(products, 1):
        product_name = product['product_name']

        # Build embedding text: 5 fields เดิม + 3 fields ใหม่
        text_parts = [
            f"ชื่อสินค้า: {product.get('product_name', '')}",
            f"สารสำคัญ: {product.get('active_ingredient', '')}",
            f"ศัตรูพืชที่กำจัดได้: {product.get('target_pest', '')}",
            f"ใช้ได้กับพืช: {product.get('applicable_crops', '')}",
            f"กลุ่มสาร: {product.get('product_group', '')}",
            f"ชื่อสารไทย: {product.get('common_name_th', '')}",
            f"คุณสมบัติเด่น: {product.get('selling_point', '')}",
            f"ลักษณะการออกฤทธิ์: {product.get('action_characteristics', '')}",
        ]
        text = " | ".join([p for p in text_parts if p.split(": ", 1)[-1].strip()])

        print(f"[{idx}/{len(products)}] {product_name}")

        embedding = generate_embedding(text)

        if not embedding:
            print(f"  Failed to generate embedding")
            failed += 1
            continue

        try:
            supabase.table('products').update({
                'embedding': embedding
            }).eq('id', product['id']).execute()
            print(f"  Embedding regenerated")
            regenerated += 1
        except Exception as e:
            print(f"  Error saving embedding: {e}")
            failed += 1

        # Rate limiting
        time.sleep(0.5)

    print(f"\nสรุป Step 3: regenerated {regenerated}, failed {failed}")
    return regenerated, failed


if __name__ == "__main__":
    print("=" * 60)
    print("Update Missing Columns + Regenerate Embeddings")
    print("=" * 60)

    # Load data
    csv_data = load_csv_data()
    if not csv_data:
        print("ไม่มีข้อมูล CSV, หยุดทำงาน")
        exit(1)

    # Fetch products from Supabase
    try:
        result = supabase.table('products').select('id, product_name').execute()
        products = result.data
        print(f"พบสินค้าใน Supabase: {len(products)} รายการ")
    except Exception as e:
        print(f"Error fetching products: {e}")
        exit(1)

    # Step 1: Preview match
    matched, not_found = step1_preview_match(products, csv_data)

    if not matched:
        print("\nไม่มีสินค้าที่ match ได้, หยุดทำงาน")
        exit(1)

    # Step 2: Update 10 columns
    step2_update_columns(matched)

    # Step 3: Regenerate embeddings
    regenerated, failed = step3_regenerate_embeddings()

    # Final summary
    print("\n" + "=" * 60)
    print("สรุปทั้งหมด")
    print("=" * 60)
    print(f"  Match: {len(matched)}/{len(products)} products")
    print(f"  Not found: {len(not_found)} products (skipped)")
    print(f"  Embeddings: regenerated {regenerated}, failed {failed}")
    print("=" * 60)
    print("เสร็จสิ้น!")
