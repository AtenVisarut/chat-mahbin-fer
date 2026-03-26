"""
Script อัพเดต product_category ใน Supabase จากข้อมูล CSV

วิธีใช้:
1. รัน SQL script add_product_category.sql ใน Supabase SQL Editor ก่อน
2. รัน script นี้: python scripts/update_product_category.py
"""
import os
import csv
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Missing SUPABASE_URL or SUPABASE_KEY in .env file")
    exit(1)

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Mapping ประเภทจาก CSV → category code
CATEGORY_MAPPING = {
    "ป้องกันโรค": "fungicide",
    "กำจัดแมลง": "insecticide",
    "กำจัดวัชพืช": "herbicide",
    "ปุ๋ยและสารบำรุง": "fertilizer"
}

def load_category_from_csv():
    """โหลดข้อมูลประเภทจาก CSV"""
    product_categories = {}

    csv_file = "ข้อมูลปุ๋ยicp.csv"

    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                product_name = row.get('ชื่อสินค้า', '').strip()
                category_th = row.get('ประเภท', '').strip()

                if product_name and category_th:
                    category = CATEGORY_MAPPING.get(category_th, category_th)
                    product_categories[product_name] = {
                        'category': category,
                        'category_th': category_th
                    }

        print(f"✅ โหลดข้อมูลประเภทจาก CSV: {len(product_categories)} รายการ")
        return product_categories

    except FileNotFoundError:
        print(f"❌ ไม่พบไฟล์ {csv_file}")
        return {}
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return {}

def update_products_category():
    """อัพเดต product_category ใน Supabase"""

    # 1. โหลดข้อมูลประเภทจาก CSV
    product_categories = load_category_from_csv()

    if not product_categories:
        print("❌ ไม่มีข้อมูลประเภทสินค้า")
        return

    # 2. ดึงข้อมูล products จาก Supabase
    try:
        result = supabase.table('products').select('id, product_name, product_category').execute()
        products = result.data
        print(f"📦 พบสินค้าใน Supabase: {len(products)} รายการ")
    except Exception as e:
        print(f"❌ Error fetching products: {e}")
        return

    # 3. อัพเดตทีละรายการ
    updated = 0
    not_found = 0
    already_set = 0

    for product in products:
        product_id = product['id']
        product_name = product['product_name']
        current_category = product.get('product_category')

        # หา category จาก CSV
        category_info = product_categories.get(product_name)

        if not category_info:
            # ลอง match แบบ partial
            for csv_name, info in product_categories.items():
                if csv_name in product_name or product_name in csv_name:
                    category_info = info
                    break

        if category_info:
            new_category = category_info['category']

            if current_category == new_category:
                already_set += 1
                continue

            try:
                supabase.table('products').update({
                    'product_category': new_category
                }).eq('id', product_id).execute()

                print(f"✅ Updated: {product_name} → {new_category}")
                updated += 1

            except Exception as e:
                print(f"❌ Error updating {product_name}: {e}")
        else:
            not_found += 1
            print(f"⚠️ ไม่พบประเภทใน CSV: {product_name}")

    print("\n" + "="*50)
    print(f"📊 สรุปผล:")
    print(f"   ✅ อัพเดตแล้ว: {updated} รายการ")
    print(f"   ✓ มีอยู่แล้ว: {already_set} รายการ")
    print(f"   ⚠️ ไม่พบใน CSV: {not_found} รายการ")
    print("="*50)

def update_missing_by_ingredient():
    """อัพเดตสินค้าที่ไม่พบใน CSV โดยดูจาก active_ingredient"""

    print("\n🔍 กำลังอัพเดตสินค้าที่ยังไม่มี category โดยดูจากสารสำคัญ...")

    # ดึงสินค้าที่ยังไม่มี category
    try:
        result = supabase.table('products').select('id, product_name, active_ingredient, target_pest').is_('product_category', 'null').execute()
        products = result.data
        print(f"📦 สินค้าที่ยังไม่มี category: {len(products)} รายการ")
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    # Mapping สารสำคัญ → ประเภท
    INGREDIENT_CATEGORY = {
        "fungicide": [
            "propiconazole", "prochloraz", "difenoconazole", "azoxystrobin",
            "tebuconazole", "carbendazim", "mancozeb", "chlorothalonil",
            "metalaxyl", "trifloxystrobin", "hexaconazole", "tricyclazole",
            "isoprothiolane", "kasugamycin", "validamycin", "copper", "sulfur"
        ],
        "insecticide": [
            "cartap", "cypermethrin", "deltamethrin", "lambda-cyhalothrin",
            "chlorpyrifos", "profenofos", "abamectin", "emamectin",
            "fipronil", "imidacloprid", "thiamethoxam", "clothianidin",
            "acetamiprid", "dinotefuran", "chlorantraniliprole", "flubendiamide"
        ],
        "herbicide": [
            "bispyribac", "pretilachlor", "butachlor", "propanil",
            "glyphosate", "paraquat", "2,4-d", "atrazine",
            "pendimethalin", "oxadiazon", "quinclorac", "cyhalofop"
        ]
    }

    updated = 0

    for product in products:
        product_id = product['id']
        product_name = product['product_name']
        active_ingredient = (product.get('active_ingredient') or '').lower()
        target_pest = (product.get('target_pest') or '').lower()

        detected_category = None

        # ตรวจจาก active_ingredient
        for category, ingredients in INGREDIENT_CATEGORY.items():
            for ing in ingredients:
                if ing.lower() in active_ingredient:
                    detected_category = category
                    break
            if detected_category:
                break

        # ถ้าไม่เจอ ตรวจจาก target_pest
        if not detected_category:
            if any(kw in target_pest for kw in ["โรค", "เชื้อรา", "ใบไหม้", "เน่า"]):
                detected_category = "fungicide"
            elif any(kw in target_pest for kw in ["เพลี้ย", "หนอน", "แมลง"]):
                detected_category = "insecticide"
            elif any(kw in target_pest for kw in ["วัชพืช", "หญ้า"]):
                detected_category = "herbicide"

        if detected_category:
            try:
                supabase.table('products').update({
                    'product_category': detected_category
                }).eq('id', product_id).execute()

                print(f"✅ Auto-detected: {product_name} → {detected_category}")
                updated += 1

            except Exception as e:
                print(f"❌ Error: {e}")

    print(f"\n✅ Auto-detected และอัพเดต: {updated} รายการ")

if __name__ == "__main__":
    print("="*50)
    print("🔄 อัพเดต Product Category")
    print("="*50)

    # Step 1: อัพเดตจาก CSV
    update_products_category()

    # Step 2: อัพเดตที่เหลือจาก active_ingredient
    update_missing_by_ingredient()

    print("\n✅ เสร็จสิ้น!")
