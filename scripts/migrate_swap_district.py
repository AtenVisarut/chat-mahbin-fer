"""
Migration: Fix district/subdistrict swap in dealers table.

CSV ต้นทาง "ICP Fer Dealer_rows.csv" มี pattern:
- Dealer rows: คอลัมน์ "อำเภอ" = ตำบลจริง, "ตำบล" = อำเภอจริง (สลับ)
- Sub Dealer rows: คอลัมน์ถูกต้องตามปกติ

Migration นี้ swap เฉพาะ Dealer rows เท่านั้น

Usage: python scripts/migrate_swap_district.py
"""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def migrate():
    # Only Dealer rows have swapped columns in the CSV
    result = supabase.table("dealers") \
        .select("id, district, subdistrict") \
        .eq("dealer_type", "Dealer") \
        .execute()
    rows = result.data or []
    print(f"Found {len(rows)} Dealer rows to fix")

    updated = 0
    errors = 0
    for row in rows:
        try:
            supabase.table("dealers").update({
                "district": row.get("subdistrict"),
                "subdistrict": row.get("district"),
            }).eq("id", row["id"]).execute()
            updated += 1
        except Exception as e:
            print(f"  Error updating id={row['id']}: {e}")
            errors += 1

    print(f"Fixed {updated} Dealer rows, {errors} errors")


if __name__ == "__main__":
    migrate()
