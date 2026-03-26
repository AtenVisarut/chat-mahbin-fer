"""
Script อัพเดต product_category (กลุ่มสาร) ใน Supabase จากข้อมูล CSV
CSV: Data ICPL product for iDA - สำหรับ view.csv
"""
import os
import csv
import sys
import io
from dotenv import load_dotenv
from supabase import create_client, Client

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Missing SUPABASE_URL or SUPABASE_KEY")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CSV_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'Data ICPL product for iDA - สำหรับ view.csv')


def load_csv_group_mapping():
    mapping = {}
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)

        name_col = None
        group_col = None
        for i, col in enumerate(header):
            if 'ชื่อสินค้า' in col:
                name_col = i
            if col.strip() == 'กลุ่มสาร':
                group_col = i

        if name_col is None or group_col is None:
            print(f"Cannot find columns. Header: {header}")
            return {}

        for row in reader:
            if len(row) > max(name_col, group_col):
                product_name = row[name_col].strip()
                group_sar = row[group_col].strip()
                if product_name and group_sar:
                    mapping[product_name] = group_sar

    print(f"Loaded {len(mapping)} mappings from CSV:")
    for name, group in mapping.items():
        print(f"  '{name}' -> '{group}'")
    return mapping


def find_match(supabase_name, csv_mapping):
    if supabase_name in csv_mapping:
        return csv_mapping[supabase_name]

    for csv_name, group in csv_mapping.items():
        if csv_name in supabase_name or supabase_name in csv_name:
            return group

    for csv_name, group in csv_mapping.items():
        csv_clean = csv_name.replace(' ', '').lower()
        sb_clean = supabase_name.replace(' ', '').lower()
        if csv_clean == sb_clean:
            return group
        if len(csv_clean) > 3 and len(sb_clean) > 3:
            if csv_clean in sb_clean or sb_clean in csv_clean:
                return group

    return None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"

    # Step 1: Load CSV mapping + manual overrides
    csv_mapping = load_csv_group_mapping()
    # Manual mapping for products not matched by CSV
    csv_mapping['ก็อปกัน'] = 'Fungicide'    # CSV has ก๊อปกัน (different tone mark)
    csv_mapping['โทมาฮอค'] = 'Fungicide'   # Not in CSV, but is a fungicide

    # Step 2: Fetch products from Supabase
    result = supabase.table('products').select('id, product_name, product_category').execute()
    products = result.data
    print(f"\nProducts in Supabase: {len(products)}")
    print("=" * 70)
    for p in products:
        cat = p.get('product_category') or 'NULL'
        print(f"  ID={p['id']:3d} | category={cat:15s} | {p['product_name']}")

    if mode == "check":
        print("\n--- CHECK mode: no changes ---")
        return

    # Step 3: Match and update
    print(f"\n{'=' * 70}")
    print(f"{'DRY RUN' if mode == 'dry' else 'UPDATING'}...")
    print(f"{'=' * 70}")

    updated = 0
    skipped = 0
    not_found = 0

    for product in products:
        pid = product['id']
        pname = product['product_name']
        current_cat = product.get('product_category')
        matched = find_match(pname, csv_mapping)

        if matched:
            if current_cat and current_cat.lower() == matched.lower():
                skipped += 1
                continue
            print(f"  {'[DRY]' if mode == 'dry' else '[UPD]'} {pname}: {current_cat or 'NULL'} -> {matched}")
            if mode == "update":
                supabase.table('products').update({
                    'product_category': matched
                }).eq('id', pid).execute()
            updated += 1
        else:
            not_found += 1
            print(f"  [???] Not in CSV: {pname} (current: {current_cat or 'NULL'})")

    print(f"\nSummary: updated={updated}, skipped={skipped}, not_found={not_found}")


if __name__ == "__main__":
    main()
