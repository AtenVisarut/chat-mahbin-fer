"""
Import dealer CSV data to Supabase 'dealers' table.
Usage: python scripts/import_dealers.py
"""
import os
import csv
import re
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Province name normalization (fix data quality issues in CSV)
PROVINCE_NORMALIZE = {
    "กาฬสินธ์": "กาฬสินธุ์",
    "ตรััง": "ตรัง",
}

# District name normalization
DISTRICT_NORMALIZE = {
    "ท่่ามะกา": "ท่ามะกา",
}

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "ICP Fer Dealer_rows.csv")


def normalize_province(name: str) -> str:
    name = name.strip()
    return PROVINCE_NORMALIZE.get(name, name)


def normalize_district(name: str) -> str:
    name = name.strip()
    return DISTRICT_NORMALIZE.get(name, name)


def normalize_phone(phone: str) -> str:
    """Normalize phone: keep digits and dashes only."""
    phone = phone.strip()
    return re.sub(r'[^\d\-]', '', phone)


def import_dealers(csv_path: str):
    print(f"Reading CSV: {csv_path}")

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Found {len(rows)} rows")

    # Build batch
    batch = []
    skipped = 0
    for row in rows:
        dealer_name = row.get("ชื่อร้าน", "").strip()
        province = normalize_province(row.get("จังหวัด", "").strip())
        dealer_type = row.get("ประเภท", "").strip()

        if not dealer_name or not province or not dealer_type:
            skipped += 1
            continue

        # CSV คอลัมน์ "อำเภอ"/"ตำบล" สลับกันเฉพาะ Dealer rows
        # Dealer: CSV "อำเภอ" = ตำบลจริง, CSV "ตำบล" = อำเภอจริง
        # Sub Dealer: CSV "อำเภอ" = อำเภอจริง, CSV "ตำบล" = ตำบลจริง
        csv_amphoe = row.get("อำเภอ", "").strip()
        csv_tambon = row.get("ตำบล", "").strip()

        if dealer_type == "Dealer":
            district = normalize_district(csv_tambon) or None
            subdistrict = csv_amphoe or None
        else:
            district = normalize_district(csv_amphoe) or None
            subdistrict = csv_tambon or None

        batch.append({
            "dealer_name": dealer_name,
            "zone": row.get("เขต", "").strip() or None,
            "province": province,
            "district": district,
            "subdistrict": subdistrict,
            "phone": normalize_phone(row.get("เบอร์โทร", "")) or None,
            "dealer_type": dealer_type,
        })

    print(f"Prepared {len(batch)} records (skipped {skipped})")

    # Insert in batches of 50
    BATCH_SIZE = 50
    inserted = 0
    for i in range(0, len(batch), BATCH_SIZE):
        chunk = batch[i : i + BATCH_SIZE]
        try:
            supabase.table("dealers").insert(chunk).execute()
            inserted += len(chunk)
            print(f"  Inserted {inserted}/{len(batch)}")
        except Exception as e:
            print(f"  Error inserting batch {i}-{i+len(chunk)}: {e}")

    print(f"\nDone! Inserted {inserted} rows into 'dealers' table.")


if __name__ == "__main__":
    import_dealers(CSV_PATH)
