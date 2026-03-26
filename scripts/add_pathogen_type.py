"""
Script to add pathogen_type column to products table in Supabase
"""
import os
import sys
import io

# Fix encoding for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Mapping: active_ingredient -> pathogen_type
PATHOGEN_TYPE_MAPPING = {
    # ==================== OOMYCETES (Phytophthora, Pythium) ====================
    # ต้องใช้สารเฉพาะ: Propamocarb, Fosetyl-Al, Metalaxyl, Cymoxanil
    "propamocarb": "oomycetes",
    "fosetyl": "oomycetes",
    "metalaxyl": "oomycetes",
    "mefenoxam": "oomycetes",
    "cymoxanil": "oomycetes",
    "dimethomorph": "oomycetes",
    "mandipropamid": "oomycetes",
    "fluopicolide": "oomycetes",

    # ==================== FUNGI (เชื้อราแท้ทั่วไป) ====================
    # Triazoles
    "propiconazole": "fungi",
    "difenoconazole": "fungi",
    "tebuconazole": "fungi",
    "hexaconazole": "fungi",
    "myclobutanil": "fungi",
    "cyproconazole": "fungi",
    "epoxiconazole": "fungi",
    "flutriafol": "fungi",

    # Imidazoles
    "prochloraz": "fungi",
    "imazalil": "fungi",

    # Benzimidazoles
    "carbendazim": "fungi",
    "benomyl": "fungi",
    "thiabendazole": "fungi",
    "thiophanate": "fungi",

    # Strobilurins
    "azoxystrobin": "fungi",
    "trifloxystrobin": "fungi",
    "pyraclostrobin": "fungi",
    "kresoxim": "fungi",

    # Dithiocarbamates (contact - ใช้ได้กว้าง)
    "mancozeb": "fungi",
    "maneb": "fungi",
    "zineb": "fungi",
    "propineb": "fungi",
    "thiram": "fungi",

    # Other fungicides
    "chlorothalonil": "fungi",
    "captan": "fungi",
    "copper": "fungi",  # Copper compounds
    "sulfur": "fungi",
    "iprodione": "fungi",
    "fludioxonil": "fungi",

    # ==================== INSECTICIDES (แมลง) ====================
    "imidacloprid": "insect",
    "thiamethoxam": "insect",
    "clothianidin": "insect",
    "acetamiprid": "insect",
    "fipronil": "insect",
    "chlorpyrifos": "insect",
    "cypermethrin": "insect",
    "deltamethrin": "insect",
    "lambda-cyhalothrin": "insect",
    "abamectin": "insect",
    "emamectin": "insect",
    "spinosad": "insect",
    "chlorantraniliprole": "insect",
    "flubendiamide": "insect",
    "indoxacarb": "insect",
    "carbaryl": "insect",
    "carbofuran": "insect",
    "methomyl": "insect",
    "omethoate": "insect",
    "dimethoate": "insect",
    "profenofos": "insect",
    "triazophos": "insect",
    "buprofezin": "insect",
    "pyriproxyfen": "insect",
    "lufenuron": "insect",
    "novaluron": "insect",
    "etofenprox": "insect",
    "bifenthrin": "insect",
    "permethrin": "insect",
    "malathion": "insect",
    "diazinon": "insect",
    "acephate": "insect",
    "cartap": "insect",
    "pirimiphos": "insect",  # Storage insect control
    "fenobucarb": "insect",  # Carbamate insecticide

    # ==================== HERBICIDES (วัชพืช) ====================
    "glyphosate": "herbicide",
    "paraquat": "herbicide",
    "glufosinate": "herbicide",
    "2,4-d": "herbicide",
    "atrazine": "herbicide",
    "alachlor": "herbicide",
    "acetochlor": "herbicide",
    "butachlor": "herbicide",
    "pretilachlor": "herbicide",
    "propanil": "herbicide",
    "quinclorac": "herbicide",
    "bensulfuron": "herbicide",
    "metsulfuron": "herbicide",
    "fenoxaprop": "herbicide",
    "cyhalofop": "herbicide",
    "bispyribac": "herbicide",
    "penoxsulam": "herbicide",

    # ==================== PGR (Plant Growth Regulator) ====================
    "paclobutrazol": "pgr",
    "gibberellic": "pgr",
    "ethephon": "pgr",
    "chlormequat": "pgr",
    "mepiquat": "pgr",
}


def get_pathogen_type(active_ingredient: str, product_category: str) -> str:
    """Determine pathogen_type from active_ingredient and product_category"""
    if not active_ingredient:
        # Fallback to product_category
        if product_category in ("Insecticide", "กำจัดแมลง"):
            return "insect"
        elif product_category in ("Herbicide", "กำจัดวัชพืช"):
            return "herbicide"
        elif product_category in ("Fungicide", "ป้องกันโรค"):
            return "fungi"  # Default for disease prevention
        elif product_category in ("Fertilizer", "ปุ๋ยและสารบำรุง"):
            return "fertilizer"
        elif product_category in ("PGR",):
            return "pgr"
        return "unknown"

    ai_lower = active_ingredient.lower()

    # Check each keyword in mapping
    for keyword, ptype in PATHOGEN_TYPE_MAPPING.items():
        if keyword in ai_lower:
            return ptype

    # Fallback to product_category
    if product_category == "กำจัดแมลง":
        return "insect"
    elif product_category == "กำจัดวัชพืช":
        return "herbicide"
    elif product_category == "ป้องกันโรค":
        return "fungi"  # Default
    elif product_category == "ปุ๋ยและสารบำรุง":
        return "fertilizer"

    return "unknown"


def main():
    # 1. Fetch all products
    print("Fetching products from Supabase...")
    result = supabase.table("products").select("id, product_name, active_ingredient, product_category").execute()
    products = result.data
    print(f"Found {len(products)} products\n")

    # 2. Determine pathogen_type for each product
    updates = []
    for p in products:
        ptype = get_pathogen_type(p.get("active_ingredient", ""), p.get("product_category", ""))
        updates.append({
            "id": p["id"],
            "product_name": p["product_name"],
            "active_ingredient": p.get("active_ingredient", "")[:50],
            "pathogen_type": ptype
        })

    # 3. Print summary
    print("=" * 80)
    print("PATHOGEN TYPE ASSIGNMENT")
    print("=" * 80)

    # Group by pathogen_type
    by_type = {}
    for u in updates:
        ptype = u["pathogen_type"]
        if ptype not in by_type:
            by_type[ptype] = []
        by_type[ptype].append(u)

    for ptype in sorted(by_type.keys()):
        print(f"\n{'='*40}")
        print(f"  {ptype.upper()} ({len(by_type[ptype])} products)")
        print(f"{'='*40}")
        for u in by_type[ptype]:
            print(f"  - {u['product_name'][:30]:<30} | {u['active_ingredient'][:40]}")

    # 4. Ask for confirmation (or auto-update if --auto flag)
    print("\n" + "=" * 80)

    auto_mode = "--auto" in sys.argv
    if auto_mode:
        confirm = "yes"
        print("Auto-update mode enabled.")
    else:
        confirm = input("Update database with these pathogen_type values? (yes/no): ")

    if confirm.lower() == "yes":
        print("\nUpdating database...")
        success = 0
        failed = 0

        for u in updates:
            try:
                supabase.table("products").update({
                    "pathogen_type": u["pathogen_type"]
                }).eq("id", u["id"]).execute()
                success += 1
                print(f"  ✓ {u['product_name'][:30]} -> {u['pathogen_type']}")
            except Exception as e:
                failed += 1
                print(f"  ✗ {u['product_name'][:30]} - Error: {e}")

        print(f"\nDone! Success: {success}, Failed: {failed}")
    else:
        print("Cancelled.")


if __name__ == "__main__":
    main()
