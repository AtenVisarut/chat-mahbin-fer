from __future__ import annotations

import logging
import json
from typing import List, Dict, Tuple
from app.models import ProductRecommendation
from app.dependencies import supabase_client, openai_client
from app.services.cache import get_from_cache, set_to_cache
from app.utils.text_processing import extract_keywords_from_question
from app.services.reranker import rerank_products_with_llm, simple_relevance_boost

logger = logging.getLogger(__name__)

# Configuration for re-ranking
ENABLE_RERANKING = True  # เปิดใช้ re-ranking เพื่อเพิ่มความแม่นยำในการแนะนำสินค้า

# =============================================================================
# Mapping โรค/ปัญหา → ประเภทสินค้าที่เหมาะสม (ใช้ระบุ required_category)
# =============================================================================
# =============================================================================
# Keywords สำหรับโรคแบคทีเรีย (Bacterial diseases)
# โรคเหล่านี้ต้องใช้ยาฆ่าแบคทีเรีย (Bactericide) ไม่ใช่ยาฆ่าเชื้อรา (Fungicide)
# =============================================================================
BACTERIAL_KEYWORDS = [
    # โรคข้าว (Rice bacterial diseases)
    "bacterial leaf blight", "โรคขอบใบแห้ง", "ขอบใบแห้ง", "blb", "xanthomonas",
    "bacterial leaf streak", "โรคใบขีดโปร่งแสง", "ใบขีดโปร่งแสง",
    "bacterial panicle blight", "โรครวงเน่า",
    # โรคผักและไม้ผล
    "bacterial wilt", "โรคเหี่ยวเขียว", "เหี่ยวเขียว", "ralstonia",
    "bacterial spot", "จุดแบคทีเรีย",
    "soft rot", "โรคเน่าเละ", "erwinia",
    "citrus canker", "โรคแคงเกอร์", "แคงเกอร์",
    "fire blight", "โรคไฟไหม้",
    # คำทั่วไป
    "แบคทีเรีย", "bacteria", "bacterium",
]


def is_bacterial_disease(disease_name: str) -> bool:
    """ตรวจสอบว่าเป็นโรคที่เกิดจากแบคทีเรียหรือไม่"""
    disease_lower = disease_name.lower()
    for keyword in BACTERIAL_KEYWORDS:
        if keyword.lower() in disease_lower:
            return True
    return False


# =============================================================================
# โรคที่บริษัทไม่มียารักษา - ไม่แนะนำสินค้า แค่ให้คำแนะนำการรักษาเบื้องต้น
# อ้างอิงจาก crop_target ของสินค้าในฐานข้อมูล (เทอราโน่, รีโนเวท)
# =============================================================================
NO_PRODUCT_DISEASES = [
    # โรคไหม้ข้าว (Rice Blast) - ต้องใช้ Tricyclazole ซึ่งบริษัทไม่มี
    "rice blast", "โรคไหม้ข้าว", "ไหม้ข้าว",
    "pyricularia oryzae", "magnaporthe oryzae",
    # โรคไหม้คอรวง / โรคเน่าคอรวง (Neck Blast / Neck Rot) - บริษัทไม่มียารักษา
    "neck blast", "neck rot", "panicle blast",
    "โรคไหม้คอรวง", "โรคเน่าคอรวง", "ไหม้คอรวง", "เน่าคอรวง", "คอรวง",
    # หมายเหตุ: โรคแบคทีเรียและไวรัสถูกกรองแยกอยู่แล้วใน is_bacterial_disease()
]

# โรคที่มียารักษา แม้จะมีชื่อคล้ายกับโรคที่ไม่มียา (ปัจจุบันว่างเปล่า)
HAS_PRODUCT_EXCEPTIONS = []


def is_no_product_disease(disease_name: str) -> bool:
    """
    ตรวจสอบว่าเป็นโรคที่บริษัทไม่มียารักษาหรือไม่
    โรคเหล่านี้จะไม่แนะนำสินค้า แค่ให้คำแนะนำการรักษาเบื้องต้น
    """
    disease_lower = disease_name.lower()

    # ตรวจสอบว่าเป็นโรคที่มียารักษา (exceptions) ก่อน
    for exception in HAS_PRODUCT_EXCEPTIONS:
        if exception.lower() in disease_lower:
            return False  # มียารักษา - ไม่ใช่ no_product_disease

    # ตรวจสอบว่าเป็นโรคที่ไม่มียารักษา
    for keyword in NO_PRODUCT_DISEASES:
        if keyword.lower() in disease_lower:
            return True
    return False


# Keywords สำหรับโรคจากเชื้อรา
FUNGAL_KEYWORDS = [
    # โรคข้าว (Rice diseases)
    "โรคไหม้", "rice blast", "blast", "pyricularia",
    "โรคใบจุด", "leaf spot", "brown spot", "จุดสีน้ำตาล",
    "โรคกาบใบแห้ง", "sheath blight", "rhizoctonia",
    "โรคถอดฝัก", "bakanae", "fusarium",
    "โรคดอกกระถิน", "false smut", "smut", "ustilaginoidea",
    "โรคเมล็ดด่าง", "dirty panicle", "grain discoloration",
    "โรคเน่าคอรวง", "neck rot", "neck blast",
    "โรคใบขีด", "narrow brown leaf spot", "cercospora",
    "โรคกาบใบเน่า", "sheath rot", "sarocladium",
    "โรคกาบใบไหม้", "sheath burn", "rhizoctonia oryzae-sativae",
    # โรคอ้อย (Sugarcane diseases)
    "แส้ดำ", "โรคแส้ดำ", "sugarcane smut", "sporisorium",
    "ลำต้นเน่าแดง", "โรคเน่าแดง", "red rot", "colletotrichum falcatum",
    "ยอดบิด", "โรคยอดบิด", "pokkah boeng",
    # โรคข้าวโพด (Corn diseases)
    "ใบไหม้แผลใหญ่", "southern corn leaf blight", "bipolaris maydis",
    "ใบไหม้แผลเล็ก", "northern corn leaf blight", "exserohilum",
    "ลำต้นเน่า", "stalk rot",
    # โรคมันสำปะหลัง (Cassava diseases)
    "โรคแอนแทรคโนสมัน", "cassava anthracnose",
    # โรคทั่วไป (General diseases)
    "โรคเน่า", "rot", "anthracnose", "แอนแทรคโนส",
    "โรคราน้ำค้าง", "downy mildew", "ราน้ำค้าง",
    "โรคราสนิม", "rust", "ราสนิม",
    "โรคราแป้ง", "powdery mildew", "ราแป้ง",
    "โรคใบไหม้", "leaf blight", "ใบไหม้",
    "โรคโคนเน่า", "stem rot", "โคนเน่า",
    "โรครากเน่า", "root rot", "รากเน่า",
    "เชื้อรา", "fungus", "fungi", "ป้องกันโรค",
    # โรคไม้ผล (Fruit tree diseases)
    "โรคราสีชมพู", "pink disease",
    "โรคใบจุดสาหร่าย", "algal leaf spot",
]

# Keywords สำหรับแมลง/ศัตรูพืช
INSECT_KEYWORDS = [
    "เพลี้ย", "aphid", "planthopper", "leafhopper",
    "หนอน", "worm", "caterpillar", "borer",
    "แมลง", "insect", "pest",
    "เพลี้ยกระโดด", "brown planthopper", "bph",
    "เพลี้ยจักจั่น", "green leafhopper", "glh",
    "เพลี้ยอ่อน", "aphids",
    "เพลี้ยไฟ", "thrips",
    "เพลี้ยแป้ง", "mealybug",
    "หนอนกอ", "stem borer",
    "หนอนห่อใบ", "leaf roller",
    "หนอนเจาะ", "fruit borer",
    "แมลงหวี่ขาว", "whitefly",
    "ไร", "mite", "spider mite",
    "ด้วง", "beetle", "กำจัดแมลง",
]

# Keywords สำหรับวัชพืช
WEED_KEYWORDS = [
    "วัชพืช", "weed", "หญ้า", "grass",
    "หญ้าข้าวนก", "barnyard grass",
    "หญ้าแดง", "red sprangletop",
    "กก", "sedge", "กำจัดวัชพืช",
]

# =============================================================================
# Dynamic Product Matching - Query จาก column "target_pest" ใน DB โดยตรง
# ไม่ต้อง maintain hard-code mapping - sync กับ DB อัตโนมัติ
# =============================================================================

# Keywords สำหรับแยก disease name เป็นคำค้นหา
DISEASE_SEARCH_PATTERNS = {
    # โรคข้าว - Thai to searchable keywords
    "โรคดอกกระถิน": ["ดอกกระถิน", "false smut"],
    "โรคเมล็ดด่าง": ["เมล็ดด่าง", "dirty panicle"],
    "โรคไหม้": ["ไหม้", "blast"],
    "โรคไหม้คอรวง": ["คอรวง", "ไหม้คอรวง", "neck blast", "panicle blast", "pyricularia grisea"],
    "โรคเน่าคอรวง": ["คอรวง", "เน่าคอรวง", "neck rot", "panicle rot", "pyricularia grisea"],
    "โรคกาบใบแห้ง": ["กาบใบแห้ง", "sheath blight", "rhizoctonia solani"],
    "โรคกาบใบเน่า": ["กาบใบเน่า", "sheath rot", "sarocladium"],
    "โรคกาบใบไหม้": ["กาบใบไหม้", "sheath burn", "rhizoctonia oryzae"],
    "โรคใบจุด": ["ใบจุด", "leaf spot", "brown spot"],
    # โรค Oomycetes
    "โรครากเน่าโคนเน่า": ["รากเน่า", "โคนเน่า", "phytophthora"],
    "โรคราน้ำค้าง": ["ราน้ำค้าง", "downy mildew"],
    # โรคทั่วไป
    "โรคแอนแทรคโนส": ["แอนแทรคโนส", "anthracnose"],
    "โรคราแป้ง": ["ราแป้ง", "powdery mildew"],
    "โรคราสนิม": ["ราสนิม", "rust"],
    "โรคราสีชมพู": ["ราสีชมพู", "ราชมพู", "pink disease"],
}


def extract_search_keywords(disease_name: str) -> List[str]:
    """
    แยก keywords จากชื่อโรคเพื่อใช้ค้นหาใน target_pest column

    Args:
        disease_name: ชื่อโรค เช่น "โรคดอกกระถิน (False Smut)"
                      หรือ pest_name เช่น "เพลี้ยจักจั่น ไรสี่ขา"

    Returns:
        รายการ keywords สำหรับค้นหา
    """
    keywords = []
    disease_lower = disease_name.lower()

    # 0. ถ้ามี space และเป็นชื่อแมลง/ศัตรูพืชหลายตัว → แยกออก
    # เช่น "เพลี้ยจักจั่น ไรสี่ขา" → ["เพลี้ยจักจั่น", "ไรสี่ขา"]
    if " " in disease_name and not disease_name.startswith("โรค"):
        parts = disease_name.split()
        for part in parts:
            part = part.strip()
            if part and len(part) > 2:
                keywords.append(part)

    # 1. ตรวจสอบจาก pattern ที่กำหนดไว้
    for pattern, search_terms in DISEASE_SEARCH_PATTERNS.items():
        if pattern.lower() in disease_lower or any(term.lower() in disease_lower for term in search_terms):
            keywords.extend(search_terms)

    # 2. แยกคำภาษาไทยจากชื่อโรค
    import re
    # ดึงส่วนภาษาไทย (ก่อนวงเล็บ)
    thai_part = re.split(r'[\(\[]', disease_name)[0].strip()
    # ลบคำนำหน้า "โรค"
    if thai_part.startswith("โรค"):
        thai_part = thai_part[3:].strip()
    if thai_part and thai_part not in keywords:
        keywords.append(thai_part)

    # 3. ดึงส่วนภาษาอังกฤษ (ในวงเล็บ)
    eng_match = re.search(r'[\(\[](.*?)[\)\]]', disease_name)
    if eng_match:
        eng_part = eng_match.group(1).strip()
        # แยกเป็นคำ
        for word in eng_part.split():
            word_clean = word.strip().lower()
            if len(word_clean) > 2 and word_clean not in ['the', 'and', 'for', 'rice']:
                if word_clean not in [k.lower() for k in keywords]:
                    keywords.append(word_clean)

    # 4. เพิ่มชื่อเต็มเป็น keyword
    if disease_name not in keywords:
        keywords.insert(0, disease_name)

    return keywords


# =============================================================================
# Oomycetes Diseases - โรคที่เกิดจาก Oomycetes (ไม่ใช่เชื้อราแท้)
# ต้องใช้สารเฉพาะที่ออกฤทธิ์ต่อ Oomycetes
# =============================================================================
OOMYCETES_DISEASES = [
    # โรครากเน่าโคนเน่า (Phytophthora)
    "phytophthora", "ไฟทอฟธอรา", "ไฟท็อปธอรา", "รากเน่าโคนเน่า", "รากเน่า", "โคนเน่า",
    "root rot", "stem rot", "crown rot",
    # โรคผลเน่า (Fruit Rot) - พบบ่อยในทุเรียน เกิดจาก Phytophthora palmivora
    "fruit rot", "ผลเน่า", "โรคผลเน่า",
    # โรคใบไหม้ (Late Blight) - Phytophthora infestans (มันฝรั่ง/มะเขือเทศ)
    "late blight", "ใบไหม้มันฝรั่ง",
    # โรคราน้ำค้าง (Downy Mildew)
    "pythium", "พิเทียม", "ราน้ำค้าง", "downy mildew",
    # โรคเน่าเละ (จาก Oomycetes)
    "เน่าเละ", "damping off", "damping-off",
    # โรคยางไหล/เปลือกเน่าทุเรียน
    "ยางไหล", "เปลือกเน่า", "gummosis",
]

# Active ingredients ที่เหมาะกับ Oomycetes
OOMYCETES_ACTIVE_INGREDIENTS = [
    # Carbamate - Propamocarb
    "propamocarb", "โพรพาโมคาร์บ",
    # Phenylamides - Metalaxyl
    "metalaxyl", "เมทาแลกซิล", "metalaxyl-m", "เมฟีโนแซม", "mefenoxam",
    # Phosphonates - Fosetyl
    "fosetyl", "ฟอสเอทิล", "ฟอสอีทิล", "phosphonic", "phosphonate",
    # Cyanoacetamide oxime - Cymoxanil
    "cymoxanil", "ไซม็อกซานิล", "ไซม๊อกซานิล", "ไซม๊อคซานิล",
    # Carboxylic acid amide - Dimethomorph
    "dimethomorph", "ไดเมโทมอร์ฟ",
    # Quinone outside inhibitors with Oomycete activity
    "mandipropamid", "แมนดิโพรพามิด",
    # Cinnamic acid - Dimethomorph related
    "fluopicolide", "ฟลูโอพิโคไลด์",
]

# Active ingredients ที่ไม่เหมาะกับ Oomycetes (เชื้อราแท้เท่านั้น)
NON_OOMYCETES_ACTIVE_INGREDIENTS = [
    # Imidazoles - ไม่ออกฤทธิ์ต่อ Oomycetes
    "prochloraz", "โพรคลอราซ", "imazalil", "อิมาซาลิล",
    # Triazoles - ไม่ค่อยออกฤทธิ์ต่อ Oomycetes
    "propiconazole", "difenoconazole", "tebuconazole", "hexaconazole",
    "โพรพิโคนาโซล", "ไดฟีโนโคนาโซล", "เทบูโคนาโซล", "เฮกซาโคนาโซล",
    # Benzimidazoles - ไม่ออกฤทธิ์ต่อ Oomycetes
    "carbendazim", "คาร์เบนดาซิม", "benomyl", "เบโนมิล", "thiabendazole",
    # Dithiocarbamates - ประสิทธิภาพต่ำกับ Oomycetes (contact fungicide ทั่วไป)
    "mancozeb", "แมนโคเซบ", "maneb", "แมเนบ", "zineb", "ไซเนบ",
    "propineb", "โพรพิเนบ", "thiram", "ไทแรม",
    # Strobilurins - บางตัวไม่ค่อยออกฤทธิ์ต่อ Oomycetes
    "azoxystrobin", "อะซ็อกซีสโตรบิน",
]


def is_oomycetes_disease(disease_name: str) -> bool:
    """ตรวจสอบว่าเป็นโรคที่เกิดจาก Oomycetes หรือไม่"""
    disease_lower = disease_name.lower()
    for keyword in OOMYCETES_DISEASES:
        if keyword.lower() in disease_lower:
            return True
    return False


def filter_products_for_oomycetes(products: List[Dict], disease_name: str) -> List[Dict]:
    """
    กรองสินค้าสำหรับโรค Oomycetes ให้เหลือเฉพาะที่มี pathogen_type = 'oomycetes'

    ใช้ pathogen_type column จาก DB เป็นหลัก (ถูกต้องกว่าการ filter ด้วย keyword)

    Args:
        products: รายการสินค้าทั้งหมด
        disease_name: ชื่อโรค

    Returns:
        รายการสินค้าที่เหมาะกับ Oomycetes (ถ้าไม่พบให้ return สินค้าทั้งหมด)
    """
    if not is_oomycetes_disease(disease_name):
        return products

    logger.info(f"🦠 โรค Oomycetes detected: {disease_name}")
    logger.info(f"   กรองสินค้าตาม pathogen_type = 'oomycetes'...")

    # Filter by pathogen_type column (primary method)
    oomycetes_products = [p for p in products if p.get("pathogen_type") == "oomycetes"]

    if oomycetes_products:
        logger.info(f"   ✓ พบสินค้า pathogen_type='oomycetes': {len(oomycetes_products)} รายการ")
        return oomycetes_products

    # Fallback: ถ้าไม่มี pathogen_type → ใช้ active ingredient keyword (backward compatibility)
    logger.warning(f"⚠️ ไม่พบสินค้า pathogen_type='oomycetes' → ใช้ active ingredient fallback")

    suitable_products = []
    for product in products:
        active_ingredient = (product.get("active_ingredient") or "").lower()
        for ai in OOMYCETES_ACTIVE_INGREDIENTS:
            if ai.lower() in active_ingredient:
                suitable_products.append(product)
                break

    if suitable_products:
        logger.info(f"   ✓ พบสินค้าจาก active ingredient: {len(suitable_products)} รายการ")
        return suitable_products

    # ถ้าไม่มีเลย → return สินค้าทั้งหมด (fallback)
    logger.warning(f"⚠️ ไม่พบสินค้าที่เหมาะกับ Oomycetes → ใช้สินค้าทั้งหมด")
    return products


def has_oomycetes_active_ingredient(product: Dict) -> bool:
    """
    ตรวจสอบว่าสินค้ามี active ingredient ที่เหมาะกับ Oomycetes หรือไม่
    ใช้กรองสินค้าที่ไม่เหมาะกับโรคเชื้อราแท้ (True Fungi)
    """
    active_ingredient = (product.get("active_ingredient") or "").lower()

    # สาร Oomycetes-specific ที่ไม่เหมาะกับเชื้อราแท้
    oomycetes_only_ingredients = [
        "fosetyl", "ฟอสเอทิล", "ฟอสอีทิล",
        "cymoxanil", "ไซม็อกซานิล", "ไซม๊อกซานิล",
        "propamocarb", "โพรพาโมคาร์บ",
        "metalaxyl", "เมทาแลกซิล", "mefenoxam",
        "dimethomorph", "ไดเมโทมอร์ฟ",
        "mandipropamid", "แมนดิโพรพามิด",
    ]

    for ingredient in oomycetes_only_ingredients:
        if ingredient in active_ingredient:
            return True
    return False


def filter_products_for_fungi(products: List[Dict], disease_name: str) -> List[Dict]:
    """
    กรองสินค้าสำหรับโรคเชื้อรา (True Fungi) ให้เหลือเฉพาะที่เหมาะสม

    หลีกเลี่ยงการแนะนำยา Oomycetes (Propamocarb, Fosetyl-Al, Cymoxanil) สำหรับโรคเชื้อราทั่วไป
    เช่น Cercospora, Colletotrichum, Fusarium, Rhizoctonia

    Args:
        products: รายการสินค้าทั้งหมด
        disease_name: ชื่อโรค

    Returns:
        รายการสินค้าที่เหมาะกับเชื้อราแท้
    """
    # ถ้าเป็นโรค Oomycetes → ไม่ต้อง filter (ใช้ filter_products_for_oomycetes แทน)
    if is_oomycetes_disease(disease_name):
        return products

    logger.info(f"🍄 โรคเชื้อรา detected: {disease_name}")
    logger.info(f"   กรองสินค้าตาม pathogen_type = 'fungi' และ active ingredient...")

    # Step 1: Filter by pathogen_type column
    fungi_products = [p for p in products if p.get("pathogen_type") == "fungi"]

    if fungi_products:
        logger.info(f"   ✓ พบสินค้า pathogen_type='fungi': {len(fungi_products)} รายการ")
        return fungi_products

    # Step 2: Fallback - กรองออกยา Oomycetes (ทั้ง pathogen_type และ active ingredient)
    logger.warning(f"⚠️ ไม่พบสินค้า pathogen_type='fungi' → กรองออก Oomycetes products")

    filtered = []
    excluded = []
    for p in products:
        # กรองออกถ้า pathogen_type = 'oomycetes'
        if p.get("pathogen_type") == "oomycetes":
            excluded.append(p.get("product_name"))
            continue
        # กรองออกถ้ามี active ingredient ที่เป็น Oomycetes-specific
        if has_oomycetes_active_ingredient(p):
            excluded.append(p.get("product_name"))
            continue
        filtered.append(p)

    if excluded:
        logger.info(f"   ❌ กรองออก Oomycetes products: {excluded}")

    if filtered:
        logger.info(f"   ✓ เหลือสินค้าที่เหมาะกับเชื้อรา: {len(filtered)} รายการ")
        return filtered

    # ถ้าไม่เหลือเลย → return list ว่าง (ดีกว่าแนะนำสินค้าผิดประเภท)
    logger.warning(f"⚠️ ไม่เหลือสินค้าหลังกรอง Oomycetes → ไม่แนะนำสินค้า (ป้องกันแนะนำผิด)")
    return []


def get_required_category(disease_name: str) -> tuple:
    """
    ระบุประเภทสินค้าที่เหมาะสมจากชื่อโรค/ปัญหา

    Returns: (category, category_th) หรือ (None, None) ถ้าไม่แน่ใจ

    หมายเหตุ: category ต้องตรงกับค่าใน DB (English)
    - Fungicide (โรคจากเชื้อรา)
    - Insecticide (แมลง/ศัตรูพืช)
    - Herbicide (วัชพืช)
    """
    disease_lower = disease_name.lower()

    # ตรวจสอบว่าเป็นโรคจากเชื้อรา → Fungicide
    for keyword in FUNGAL_KEYWORDS:
        if keyword.lower() in disease_lower:
            logger.info(f"🏷️ โรค '{disease_name}' → ต้องใช้ Fungicide")
            return ("Fungicide", "ยาป้องกันโรค")

    # ตรวจสอบว่าเป็นแมลง/ศัตรูพืช → Insecticide
    for keyword in INSECT_KEYWORDS:
        if keyword.lower() in disease_lower:
            logger.info(f"🏷️ ปัญหา '{disease_name}' → ต้องใช้ Insecticide")
            return ("Insecticide", "ยากำจัดแมลง")

    # ตรวจสอบว่าเป็นวัชพืช → Herbicide
    for keyword in WEED_KEYWORDS:
        if keyword.lower() in disease_lower:
            logger.info(f"🏷️ ปัญหา '{disease_name}' → ต้องใช้ Herbicide")
            return ("Herbicide", "ยากำจัดวัชพืช")

    return (None, None)


# Category synonyms - ชื่อต่างกันแต่หมายถึงประเภทเดียวกัน
CATEGORY_SYNONYMS = {
    "Insecticide": ["Insecticide", "insecticide", "กำจัดแมลง", "ยาฆ่าแมลง", "ยากำจัดแมลง"],
    "Fungicide": ["Fungicide", "fungicide", "ป้องกันโรค", "ยาป้องกันโรค", "ยาฆ่าเชื้อรา"],
    "Herbicide": ["Herbicide", "herbicide", "กำจัดวัชพืช", "ยาฆ่าหญ้า", "ยากำจัดวัชพืช"],
    "PGR": ["PGR", "pgr", "สารเร่งการเจริญเติบโต", "สารควบคุมการเจริญเติบโต"],
    "Fertilizer": ["Fertilizer", "fertilizer", "ปุ๋ยและสารบำรุง", "ปุ๋ย", "สารบำรุง"],
}


def normalize_category(category: str) -> str:
    """
    แปลง category ให้เป็นชื่อมาตรฐาน
    เช่น "ยาฆ่าแมลง" → "Insecticide", "กำจัดแมลง" → "Insecticide"
    """
    if not category:
        return "unknown"

    category_lower = category.lower().strip()
    for standard, synonyms in CATEGORY_SYNONYMS.items():
        if category_lower in [s.lower() for s in synonyms]:
            return standard

    return category  # คืนค่าเดิมถ้าไม่พบใน synonyms


def get_product_category(product: dict) -> str:
    """
    ระบุประเภทสินค้าจาก field product_category ใน DB

    Returns: "Fungicide", "Insecticide", "Herbicide", "PGR", "Fertilizer" หรือ "unknown"
    """
    # อ่านจาก field product_category ใน DB (แม่นยำ 100%)
    db_category = product.get("product_category")
    if db_category:
        # Normalize ให้เป็นชื่อมาตรฐาน
        return normalize_category(db_category)

    # Fallback: ถ้าไม่มีข้อมูลใน DB ให้ return unknown
    return "unknown"


def filter_products_by_category(products: List[Dict], required_category: str) -> List[Dict]:
    """
    กรองสินค้าให้เหลือเฉพาะประเภทที่ต้องการ

    Args:
        products: รายการสินค้าทั้งหมด
        required_category: ประเภทที่ต้องการ (ป้องกันโรค, กำจัดแมลง, กำจัดวัชพืช)

    Returns:
        รายการสินค้าที่ตรงประเภท เท่านั้น (ไม่มี fallback ที่ผิดประเภท)
    """
    if not required_category:
        return products

    # กรองสินค้าตรงประเภท
    matched_products = []
    wrong_category_products = []

    for product in products:
        product_category = get_product_category(product)
        product["detected_category"] = product_category  # เก็บไว้ใช้ debug

        logger.debug(f"   Product: {product.get('product_name')} → category: {product_category}")

        if product_category == required_category:
            matched_products.append(product)
        else:
            # ตรวจสอบว่าเป็นประเภทที่ผิดชัดเจนหรือไม่
            wrong_categories = {"Fungicide", "Insecticide", "Herbicide", "PGR", "Fertilizer"} - {required_category}
            if product_category in wrong_categories:
                wrong_category_products.append(product.get('product_name'))
            # ถ้าเป็น unknown → ตรวจสอบเพิ่มเติมจาก active ingredient
            elif product_category == "unknown" or product_category is None:
                # กรองออกถ้าเป็นยาฆ่าหญ้า/แมลงชัดเจน (จาก active ingredient)
                active = (product.get("active_ingredient") or "").lower()
                herbicide_ingredients = ["ametryn", "acetochlor", "paraquat", "glyphosate", "atrazine", "2,4-d"]
                insecticide_ingredients = ["fipronil", "cypermethrin", "imidacloprid", "abamectin", "chlorpyrifos"]

                is_herbicide = any(h in active for h in herbicide_ingredients)
                is_insecticide = any(i in active for i in insecticide_ingredients)

                # ถ้าต้องการยาป้องกันโรค แต่ active ingredient เป็นยาฆ่าหญ้า/แมลง → กรองออก
                if required_category == "Fungicide" and (is_herbicide or is_insecticide):
                    wrong_category_products.append(product.get('product_name'))
                    continue
                # ถ้าไม่แน่ใจและไม่ใช่ประเภทที่ผิดชัดเจน → ไม่เอา (เข้มงวดขึ้น)
                wrong_category_products.append(product.get('product_name'))

    if wrong_category_products:
        logger.info(f"❌ กรองออกสินค้าผิดประเภท: {wrong_category_products[:5]}...")

    logger.info(f"🔍 Filter by '{required_category}': {len(matched_products)} matched, {len(wrong_category_products)} excluded")

    # ถ้ามีสินค้าตรงประเภท → ใช้เฉพาะสินค้าตรงประเภท
    if matched_products:
        return matched_products

    # ถ้าไม่มีเลย → return list ว่าง (ไม่ fallback ไปประเภทอื่น)
    logger.warning(f"⚠️ ไม่พบสินค้าประเภท {required_category} - ไม่แนะนำสินค้าผิดประเภท")
    return []


# =============================================================================
# Plant Synonyms (ใช้ในการจับคู่ชื่อพืช)
# =============================================================================
PLANT_SYNONYMS = {
    # พืชไร่
    "ข้าว": ["ข้าว", "rice", "นาข้าว", "นา", "ข้าวเจ้า", "ข้าวเหนียว"],
    "ข้าวโพด": ["ข้าวโพด", "corn", "maize", "โพด"],
    "มันสำปะหลัง": ["มัน", "cassava", "มันสำปะหลัง"],
    "อ้อย": ["อ้อย", "sugarcane"],
    # ไม้ผล
    "มะม่วง": ["มะม่วง", "mango"],
    "ทุเรียน": ["ทุเรียน", "durian"],
    "ลำไย": ["ลำไย", "longan"],
    "ส้ม": ["ส้ม", "มะนาว", "citrus", "ส้มโอ", "ส้มเขียวหวาน"],
    "ลิ้นจี่": ["ลิ้นจี่", "lychee", "litchi"],
    "มังคุด": ["มังคุด", "mangosteen"],
    "เงาะ": ["เงาะ", "rambutan"],
    "กล้วย": ["กล้วย", "banana"],
    # พืชยืนต้น
    "ยางพารา": ["ยาง", "rubber", "ยางพารา"],
    "ปาล์ม": ["ปาล์ม", "palm", "ปาล์มน้ำมัน"],
    # พืชผัก
    "พริก": ["พริก", "chili", "pepper"],
    "มะเขือเทศ": ["มะเขือเทศ", "tomato"],
    "แตง": ["แตง", "melon", "แตงกวา", "แตงโม"],
    "ถั่ว": ["ถั่ว", "bean", "ถั่วเหลือง", "ถั่วลิสง"],
    "ผักกาด": ["ผักกาด", "cabbage", "กะหล่ำ"],
}

# =============================================================================
# PLANT_EXCLUSIONS - คำที่ต้อง exclude เมื่อค้นหาพืช
# เช่น ค้นหา "ข้าว" → ต้อง exclude product ที่มีเฉพาะ "ข้าวโพด"
# =============================================================================
PLANT_EXCLUSIONS = {
    "ข้าว": ["ข้าวโพด"],  # ข้าว ≠ ข้าวโพด
    "rice": ["corn", "maize"],
    "ข้าวโพด": [],  # ข้าวโพด ไม่ต้อง exclude อะไร
    "corn": [],
}


def filter_products_by_plant(products: List[Dict], plant_type: str) -> List[Dict]:
    """
    กรองสินค้าให้เหลือเฉพาะที่ใช้ได้กับพืชที่ระบุ

    Args:
        products: รายการสินค้าทั้งหมด
        plant_type: ชนิดพืช (เช่น "ข้าว", "ทุเรียน")

    Returns:
        รายการสินค้าที่ใช้ได้กับพืชนั้น + สินค้าที่ใช้ได้กับพืชทุกชนิด
    """
    if not plant_type:
        return products

    plant_lower = plant_type.lower()

    # หา synonyms ของพืช
    plant_keywords = [plant_lower]
    for main_plant, synonyms in PLANT_SYNONYMS.items():
        if plant_lower in [s.lower() for s in synonyms] or plant_lower == main_plant.lower():
            plant_keywords = [s.lower() for s in synonyms]
            break

    matched_products = []
    general_products = []  # สินค้าที่ใช้ได้กับพืชหลายชนิด
    excluded_products = []  # สินค้าที่ห้ามใช้กับพืชนี้

    # คำที่บ่งบอกว่า "ห้ามใช้"
    exclusion_keywords = ["ยกเว้น", "ห้ามใช้", "ไม่ควรใช้", "ห้าม"]

    for product in products:
        applicable_crops = (product.get("applicable_crops") or "").lower()
        product_name = product.get("product_name", "")

        # ตรวจสอบว่าสินค้า "ห้ามใช้" กับพืชนี้หรือไม่
        is_excluded = False
        for excl_kw in exclusion_keywords:
            if excl_kw in applicable_crops:
                # ถ้ามีคำว่า "ยกเว้น/ห้ามใช้" + ชื่อพืช → ห้ามใช้
                for plant_kw in plant_keywords:
                    if plant_kw in applicable_crops:
                        is_excluded = True
                        logger.debug(f"   ❌ {product_name}: ห้ามใช้กับ {plant_type}")
                        break
                if is_excluded:
                    break

        if is_excluded:
            excluded_products.append(product)
            continue

        # ตรวจสอบว่าสินค้าใช้ได้กับพืชที่ระบุหรือไม่
        is_matched = False
        for kw in plant_keywords:
            if kw in applicable_crops:
                is_matched = True
                break

        if is_matched:
            matched_products.append(product)
        elif "พืชทุกชนิด" in applicable_crops or "ทุกชนิด" in applicable_crops or "ทุกพืช" in applicable_crops:
            # สินค้าใช้ได้กับพืชทั่วไป (แต่ต้องไม่มีข้อยกเว้น)
            general_products.append(product)

    logger.info(f"🌱 Filter by plant '{plant_type}': {len(matched_products)} matched, {len(general_products)} general, {len(excluded_products)} excluded")

    # ถ้ามีสินค้าตรงพืช → ใช้เฉพาะสินค้าตรงพืช
    if matched_products:
        return matched_products

    # ถ้าไม่มีสินค้าตรงพืช → ใช้สินค้าที่ใช้ได้ทั่วไป
    if general_products:
        logger.warning(f"⚠️ ไม่พบสินค้าเฉพาะ {plant_type} → ใช้สินค้าที่ใช้ได้กับพืชหลายชนิด")
        return general_products

    # ถ้าไม่มีเลย → return ทั้งหมด (ไม่กรอง)
    logger.warning(f"⚠️ ไม่พบสินค้าสำหรับ {plant_type} → ไม่กรอง")
    return products


def filter_products_strict(
    products: List[Dict],
    plant_type: str,
    disease_name: str
) -> List[Dict]:
    """
    กรองสินค้าแบบ strict - ต้องตรงทั้ง applicable_crops และ target_pest

    Args:
        products: รายการสินค้าทั้งหมด
        plant_type: ชนิดพืช (เช่น "ข้าว", "ทุเรียน")
        disease_name: ชื่อโรคที่วิเคราะห์ได้

    Returns:
        รายการสินค้าที่ตรงทั้ง 2 เงื่อนไข
    """
    if not products:
        return []

    # ==========================================================================
    # PLANT MATCHING - ใช้ keywords ที่ชัดเจนสำหรับแต่ละพืช
    # STRICT: ต้อง match เฉพาะ keyword ที่ไม่ใช่ substring ของพืชอื่น
    # ==========================================================================
    STRICT_PLANT_PATTERNS = {
        # ข้าว - ต้องไม่ใช่ข้าวโพด
        # หมายเหตุ: ห้ามใช้ ' ข้าว' หรือ 'ข้าว ' เพราะจะ match กับ ', ข้าวโพด'
        "ข้าว": {
            "must_match": ["นาข้าว", "(ข้าว)", "ข้าว)", "(ข้าว", "rice", "paddy"],
            "must_not_match": ["ข้าวโพด", "corn", "maize"],
        },
        "rice": {
            "must_match": ["นาข้าว", "(ข้าว)", "rice", "paddy"],
            "must_not_match": ["ข้าวโพด", "corn", "maize"],
        },
    }

    # ==========================================================================
    # DISEASE-SPECIFIC KEYWORDS - keywords เฉพาะโรค
    # โรคไหม้ข้าว (Blast) - รวม keywords จากข้อมูลจริงในฐานข้อมูล
    # ==========================================================================
    DISEASE_SPECIFIC_KEYWORDS = {
        "โรคไหม้คอรวง": ["blast", "pyricularia", "โรคไหม้ข้าว", "โรคเน่าคอรวง", "คอรวง", "neck blast", "panicle blast", "กาบใบไหม้"],
        "โรคไหม้ข้าว": ["blast", "pyricularia", "rice blast", "leaf blast", "โรคไหม้", "กาบใบไหม้"],
        "rice blast": ["blast", "pyricularia", "โรคไหม้", "คอรวง"],
        "neck blast": ["blast", "pyricularia", "โรคไหม้คอรวง", "โรคเน่าคอรวง", "คอรวง"],
        "leaf blast": ["blast", "pyricularia", "โรคไหม้ใบ"],
        "โรครากเน่าโคนเน่า": ["phytophthora", "รากเน่า", "โคนเน่า", "root rot", "ยางไหล"],
        "phytophthora": ["phytophthora", "รากเน่า", "โคนเน่า", "ยางไหล"],
    }

    disease_lower = disease_name.lower()

    # Get disease-specific keywords if available
    disease_keywords = []
    for disease_key, keywords in DISEASE_SPECIFIC_KEYWORDS.items():
        if disease_key.lower() in disease_lower or disease_lower in disease_key.lower():
            disease_keywords = [kw.lower() for kw in keywords]
            logger.info(f"   🎯 Using specific keywords for '{disease_key}': {disease_keywords}")
            break

    # Fallback to generic keywords if no specific match
    if not disease_keywords:
        disease_patterns = [
            "เน่า", "จุด", "ราน้ำค้าง", "ราแป้ง", "ราสนิม",
            "แอนแทรคโนส", "anthracnose", "rot", "blight",
            "phytophthora", "pythium", "fusarium", "cercospora",
            "เพลี้ย", "หนอน", "ด้วง", "ไร"
        ]
        for pattern in disease_patterns:
            if pattern.lower() in disease_lower:
                disease_keywords.append(pattern.lower())

        # Add main disease name words
        for word in disease_name.split():
            if len(word) > 2:
                disease_keywords.append(word.lower())

    disease_keywords = list(set(disease_keywords))
    logger.info(f"🔍 Strict filter - Plant: {plant_type}, Disease keywords: {disease_keywords[:5]}")

    # Get plant keywords
    plant_lower = plant_type.lower() if plant_type else ""

    # Check if we have strict patterns for this plant
    use_strict_matching = plant_lower in STRICT_PLANT_PATTERNS
    strict_patterns = STRICT_PLANT_PATTERNS.get(plant_lower, {})

    # Fallback: use PLANT_SYNONYMS + PLANT_EXCLUSIONS
    plant_keywords = [plant_lower]
    for main_plant, synonyms in PLANT_SYNONYMS.items():
        if plant_lower in [s.lower() for s in synonyms] or plant_lower == main_plant.lower():
            plant_keywords = [s.lower() for s in synonyms]
            break
    plant_exclusions = PLANT_EXCLUSIONS.get(plant_lower, [])

    strict_matched = []
    plant_only_matched = []

    for product in products:
        applicable_crops = (product.get("applicable_crops") or "").lower()
        target_pest = (product.get("target_pest") or "").lower()
        product_name = product.get("product_name", "")

        # Check plant match - use STRICT matching if available
        plant_match = False
        if plant_type:
            if use_strict_matching:
                # === STRICT MATCHING ===
                # ต้องมี must_match pattern อย่างน้อย 1 ตัว
                # ถ้ามี must_match → match (แม้จะมี must_not_match ด้วย เพราะ product อาจใช้ได้กับหลายพืช)
                # ถ้าไม่มี must_match แต่มี must_not_match → exclude
                must_match = strict_patterns.get("must_match", [])
                must_not_match = strict_patterns.get("must_not_match", [])

                has_required = any(p.lower() in applicable_crops for p in must_match)
                has_excluded = any(p.lower() in applicable_crops for p in must_not_match)

                # Special case: applicable_crops = "ข้าว" พอดี (exact match)
                # ถ้า plant_lower ตรงกับ applicable_crops พอดี และไม่มี excluded → match
                if applicable_crops.strip() == plant_lower:
                    plant_match = True
                    logger.debug(f"   ✓ EXACT MATCH: {product_name}")
                elif has_required:
                    # มี must_match → match (เช่น "นาข้าว" อยู่ใน applicable_crops)
                    plant_match = True
                    logger.debug(f"   ✓ STRICT MATCH: {product_name}")
                elif has_excluded and not has_required:
                    # ไม่มี must_match แต่มี excluded (เช่น มีแค่ "ข้าวโพด")
                    logger.debug(f"   ✗ STRICT EXCLUDED: {product_name} - มี excluded pattern แต่ไม่มี required")
            else:
                # === FALLBACK: Original matching ===
                for kw in plant_keywords:
                    if kw in applicable_crops:
                        is_excluded = False
                        for excl in plant_exclusions:
                            if excl.lower() in applicable_crops:
                                is_excluded = True
                                logger.debug(f"   ❌ EXCLUDED: {product_name} - มี '{excl}' ใน applicable_crops")
                                break
                        if not is_excluded:
                            plant_match = True
                            break

            # Also check for general products
            if not plant_match and ("พืชทุกชนิด" in applicable_crops or "ทุกชนิด" in applicable_crops):
                plant_match = True

        # Check disease match in target_pest
        disease_match = False
        for kw in disease_keywords:
            if kw in target_pest:
                disease_match = True
                break

        # Strict match: both plant AND disease must match
        if plant_match and disease_match:
            strict_matched.append(product)
            logger.debug(f"   ✅ STRICT: {product_name} (plant={plant_match}, disease={disease_match})")
        elif plant_match:
            plant_only_matched.append(product)
            logger.debug(f"   🌱 PLANT ONLY: {product_name}")

    logger.info(f"   → Strict matched: {len(strict_matched)}, Plant-only: {len(plant_only_matched)}")

    # Return strict matched first, then plant-only as fallback
    if strict_matched:
        return strict_matched

    # Fallback: return plant-only matches if no strict matches
    if plant_only_matched:
        logger.warning(f"⚠️ No strict match for {disease_name} → using plant-only matches")
        return plant_only_matched

    # Last fallback: return all
    logger.warning(f"⚠️ No matches at all → returning all products")
    return products


# =============================================================================
# โรคที่มีแมลงพาหะ → ควรแนะนำยาฆ่าแมลงแทนยากำจัดเชื้อ
# =============================================================================
VECTOR_DISEASES = {
    # =========================================================================
    # 🌾 ข้าว (RICE) - โรคไวรัสที่มีเพลี้ยเป็นพาหะ
    # =========================================================================
    "โรคจู๋": {"pest": "เพลี้ยกระโดดสีน้ำตาล", "search_query": "เพลี้ยกระโดดสีน้ำตาล ยาฆ่าแมลง BPH", "disease_query": "โรคจู๋ ข้าว บำรุงต้น ฟื้นฟู"},
    "rice ragged stunt": {"pest": "เพลี้ยกระโดดสีน้ำตาล", "search_query": "เพลี้ยกระโดดสีน้ำตาล ยาฆ่าแมลง BPH", "disease_query": "โรคจู๋ ข้าว บำรุงต้น"},
    "ragged stunt": {"pest": "เพลี้ยกระโดดสีน้ำตาล", "search_query": "เพลี้ยกระโดดสีน้ำตาล ยาฆ่าแมลง BPH", "disease_query": "โรคจู๋ ข้าว บำรุงต้น"},
    "โรคใบหงิก": {"pest": "เพลี้ยกระโดดสีน้ำตาล", "search_query": "เพลี้ยกระโดดสีน้ำตาล ยาฆ่าแมลง BPH", "disease_query": "โรคใบหงิก ข้าว บำรุงต้น ฮอร์โมน"},
    "rice grassy stunt": {"pest": "เพลี้ยกระโดดสีน้ำตาล", "search_query": "เพลี้ยกระโดดสีน้ำตาล ยาฆ่าแมลง BPH", "disease_query": "โรคใบหงิก ข้าว บำรุงต้น"},
    "grassy stunt": {"pest": "เพลี้ยกระโดดสีน้ำตาล", "search_query": "เพลี้ยกระโดดสีน้ำตาล ยาฆ่าแมลง BPH", "disease_query": "โรคใบหงิก ข้าว บำรุงต้น"},
    "โรคใบสีส้ม": {"pest": "เพลี้ยจักจั่นเขียว", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง GLH", "disease_query": "โรคใบสีส้ม ข้าว บำรุงต้น"},
    "rice orange leaf": {"pest": "เพลี้ยจักจั่นเขียว", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง GLH", "disease_query": "โรคใบสีส้ม ข้าว บำรุงต้น"},
    "orange leaf": {"pest": "เพลี้ยจักจั่นเขียว", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง GLH", "disease_query": "โรคใบสีส้ม ข้าว บำรุงต้น"},
    "โรคใบขาวข้าว": {"pest": "เพลี้ยจักจั่นเขียว", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง GLH", "disease_query": "โรคใบขาว ข้าว บำรุงต้น"},
    "rice tungro": {"pest": "เพลี้ยจักจั่นเขียว", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง GLH", "disease_query": "โรคทังโร ข้าว บำรุงต้น"},
    "tungro": {"pest": "เพลี้ยจักจั่นเขียว", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง GLH", "disease_query": "โรคทังโร ข้าว บำรุงต้น"},
    "โรคทังโร": {"pest": "เพลี้ยจักจั่นเขียว", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง GLH", "disease_query": "โรคทังโร ข้าว บำรุงต้น"},

    # =========================================================================
    # 🍬 อ้อย (SUGARCANE) - โรคไวรัสและไฟโตพลาสมา
    # =========================================================================
    "โรคใบขาวอ้อย": {"pest": "เพลี้ยจักจั่น", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง อ้อย"},
    "sugarcane white leaf": {"pest": "เพลี้ยจักจั่น", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง อ้อย"},
    "white leaf": {"pest": "เพลี้ยจักจั่น", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง"},
    "โรคใบด่างอ้อย": {"pest": "เพลี้ยอ่อน", "search_query": "เพลี้ยอ่อน ยาฆ่าแมลง อ้อย"},
    "sugarcane mosaic": {"pest": "เพลี้ยอ่อน", "search_query": "เพลี้ยอ่อน ยาฆ่าแมลง"},
    "โรคกอตะไคร้": {"pest": "เพลี้ยจักจั่น", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง อ้อย"},
    "sugarcane grassy shoot": {"pest": "เพลี้ยจักจั่น", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง"},

    # =========================================================================
    # 🥭 มะม่วง (MANGO) - โรคที่มีแมลงเกี่ยวข้อง
    # =========================================================================
    "โรคช่อดำมะม่วง": {"pest": "เพลี้ยจักจั่นมะม่วง เพลี้ยไฟ", "search_query": "เพลี้ยจักจั่นมะม่วง เพลี้ยไฟ ยาฆ่าแมลง"},
    "mango malformation": {"pest": "ไรสี่ขา", "search_query": "ไรสี่ขา ยาฆ่าไร มะม่วง"},
    "โรคยอดไหม้มะม่วง": {"pest": "เพลี้ยจักจั่นมะม่วง", "search_query": "เพลี้ยจักจั่นมะม่วง ยาฆ่าแมลง"},
    "mango hopper burn": {"pest": "เพลี้ยจักจั่นมะม่วง", "search_query": "เพลี้ยจักจั่นมะม่วง ยาฆ่าแมลง"},

    # =========================================================================
    # 🌳 ลำไย (LONGAN) - โรคที่มีแมลงเป็นพาหะ
    # =========================================================================
    "โรคพุ่มไม้กวาด": {"pest": "เพลี้ยจักจั่น ไรสี่ขา", "search_query": "เพลี้ยจักจั่น ไรสี่ขา ยาฆ่าแมลง ลำไย"},
    "witches' broom": {"pest": "เพลี้ยจักจั่น ไรสี่ขา", "search_query": "เพลี้ยจักจั่น ไรสี่ขา ยาฆ่าแมลง ลำไย"},
    "longan witches broom": {"pest": "เพลี้ยจักจั่น ไรสี่ขา", "search_query": "เพลี้ยจักจั่น ไรสี่ขา ยาฆ่าแมลง"},
    "โรคใบไหม้ลำไย": {"pest": "เพลี้ยไฟ ไรแดง", "search_query": "เพลี้ยไฟ ไรแดง ยาฆ่าแมลง ลำไย"},

    # =========================================================================
    # 🍈 ทุเรียน (DURIAN) - แมลงศัตรูพืชสำคัญ
    # =========================================================================
    "เพลี้ยไก่แจ้ทุเรียน": {"pest": "เพลี้ยไก่แจ้", "search_query": "เพลี้ยไก่แจ้ ยาฆ่าแมลง ทุเรียน"},
    "หนอนเจาะผลทุเรียน": {"pest": "หนอนเจาะผล", "search_query": "หนอนเจาะผล ยาฆ่าแมลง ทุเรียน"},
    "เพลี้ยแป้งทุเรียน": {"pest": "เพลี้ยแป้ง", "search_query": "เพลี้ยแป้ง ยาฆ่าแมลง ทุเรียน"},
    "ไรแดงทุเรียน": {"pest": "ไรแดง", "search_query": "ไรแดง ยาฆ่าไร ทุเรียน"},
    "เพลี้ยไฟทุเรียน": {"pest": "เพลี้ยไฟ", "search_query": "เพลี้ยไฟ ยาฆ่าแมลง ทุเรียน"},
    # เพลี้ยจักจั่นฝอย (Durian Jassid) - สาเหตุอาการใบหงิกและก้านธูป
    "เพลี้ยจักจั่นฝอย": {"pest": "เพลี้ยจักจั่นฝอย", "search_query": "เพลี้ยจักจั่นฝอย ยาฆ่าแมลง ทุเรียน"},
    "เพลี้ยจักจั่นฝอยทุเรียน": {"pest": "เพลี้ยจักจั่นฝอย", "search_query": "เพลี้ยจักจั่นฝอย ยาฆ่าแมลง ทุเรียน"},
    "durian jassid": {"pest": "เพลี้ยจักจั่นฝอย", "search_query": "เพลี้ยจักจั่นฝอย ยาฆ่าแมลง ทุเรียน"},
    "อาการใบหงิก": {"pest": "เพลี้ยจักจั่นฝอย", "search_query": "เพลี้ยจักจั่นฝอย ยาฆ่าแมลง ทุเรียน"},
    "อาการก้านธูป": {"pest": "เพลี้ยจักจั่นฝอย", "search_query": "เพลี้ยจักจั่นฝอย ยาฆ่าแมลง ทุเรียน"},
    "ก้านธูป": {"pest": "เพลี้ยจักจั่นฝอย", "search_query": "เพลี้ยจักจั่นฝอย ยาฆ่าแมลง ทุเรียน"},
    # เพลี้ยไฟ (Thrips) - สาเหตุอาการใบไหม้และร่วง
    "เพลี้ยไฟ": {"pest": "เพลี้ยไฟ", "search_query": "เพลี้ยไฟ ยาฆ่าแมลง ทุเรียน"},
    "thrips": {"pest": "เพลี้ยไฟ", "search_query": "เพลี้ยไฟ ยาฆ่าแมลง ทุเรียน"},

    # =========================================================================
    # 🍊 ส้ม/มะนาว (CITRUS) - โรคไวรัสที่มีพาหะ
    # =========================================================================
    "โรคกรีนนิ่ง": {"pest": "เพลี้ยไก่แจ้", "search_query": "เพลี้ยไก่แจ้ ยาฆ่าแมลง ส้ม"},
    "greening": {"pest": "เพลี้ยไก่แจ้", "search_query": "เพลี้ยไก่แจ้ ยาฆ่าแมลง ส้ม"},
    "hlb": {"pest": "เพลี้ยไก่แจ้", "search_query": "เพลี้ยไก่แจ้ ยาฆ่าแมลง ส้ม"},
    "huanglongbing": {"pest": "เพลี้ยไก่แจ้", "search_query": "เพลี้ยไก่แจ้ ยาฆ่าแมลง ส้ม"},
    "โรคทริสเตซ่า": {"pest": "เพลี้ยอ่อน", "search_query": "เพลี้ยอ่อน ยาฆ่าแมลง ส้ม"},
    "tristeza": {"pest": "เพลี้ยอ่อน", "search_query": "เพลี้ยอ่อน ยาฆ่าแมลง ส้ม"},
    "citrus tristeza": {"pest": "เพลี้ยอ่อน", "search_query": "เพลี้ยอ่อน ยาฆ่าแมลง ส้ม"},

    # =========================================================================
    # 🥔 มันสำปะหลัง (CASSAVA) - โรคไวรัสที่มีพาหะ
    # =========================================================================
    "โรคใบด่างมันสำปะหลัง": {"pest": "แมลงหวี่ขาว", "search_query": "แมลงหวี่ขาว ยาฆ่าแมลง มันสำปะหลัง"},
    "cassava mosaic": {"pest": "แมลงหวี่ขาว", "search_query": "แมลงหวี่ขาว ยาฆ่าแมลง มันสำปะหลัง"},
    "cmd": {"pest": "แมลงหวี่ขาว", "search_query": "แมลงหวี่ขาว ยาฆ่าแมลง มันสำปะหลัง"},
    "slcmv": {"pest": "แมลงหวี่ขาว", "search_query": "แมลงหวี่ขาว ยาฆ่าแมลง"},
    "โรคพุ่มแจ้มันสำปะหลัง": {"pest": "เพลี้ยจักจั่น", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง มันสำปะหลัง"},
    "cassava witches' broom": {"pest": "เพลี้ยจักจั่น", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง"},

    # =========================================================================
    # 🌽 ข้าวโพด (CORN/MAIZE) - โรคไวรัสที่มีพาหะ
    # =========================================================================
    "โรคข้าวโพดแคระ": {"pest": "เพลี้ยจักจั่นข้าวโพด", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง ข้าวโพด"},
    "corn stunt": {"pest": "เพลี้ยจักจั่นข้าวโพด", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง ข้าวโพด"},
    "โรคข้าวโพดงอย": {"pest": "เพลี้ยจักจั่นข้าวโพด", "search_query": "เพลี้ยจักจั่น ยาฆ่าแมลง ข้าวโพด"},
    "โรคใบลายข้าวโพด": {"pest": "เพลี้ยกระโดดข้าวโพด", "search_query": "เพลี้ยกระโดด ยาฆ่าแมลง ข้าวโพด"},
    "maize stripe": {"pest": "เพลี้ยกระโดดข้าวโพด", "search_query": "เพลี้ยกระโดด ยาฆ่าแมลง ข้าวโพด"},
    "โรคใบด่างข้าวโพด": {"pest": "เพลี้ยอ่อน", "search_query": "เพลี้ยอ่อน ยาฆ่าแมลง ข้าวโพด"},
    "maize mosaic": {"pest": "เพลี้ยอ่อน เพลี้ยกระโดด", "search_query": "เพลี้ยอ่อน เพลี้ยกระโดด ยาฆ่าแมลง"},

    # =========================================================================
    # 🌿 โรคไวรัสทั่วไป
    # =========================================================================
    "โรคใบด่าง": {"pest": "เพลี้ยอ่อน แมลงหวี่ขาว", "search_query": "เพลี้ยอ่อน แมลงหวี่ขาว ยาฆ่าแมลง"},
    "mosaic": {"pest": "เพลี้ยอ่อน", "search_query": "เพลี้ยอ่อน ยาฆ่าแมลง"},
    "โรคใบหด": {"pest": "เพลี้ยอ่อน ไรขาว", "search_query": "เพลี้ยอ่อน ไรขาว ยาฆ่าแมลง"},
    "leaf curl": {"pest": "แมลงหวี่ขาว", "search_query": "แมลงหวี่ขาว ยาฆ่าแมลง"},
    "โรคใบหงิกเหลือง": {"pest": "แมลงหวี่ขาว", "search_query": "แมลงหวี่ขาว ยาฆ่าแมลง"},
}

def get_search_query_for_disease(disease_name: str, pest_type: str = "") -> tuple:
    """
    ตรวจสอบว่าโรคนี้มีแมลงพาหะหรือไม่
    ถ้ามี → return (search_query สำหรับยาฆ่าแมลง, pest_name, disease_search_query)
    ถ้าไม่มี → return (disease_name, None, None)

    Returns: (vector_search_query, pest_name, disease_search_query)
    """
    disease_lower = disease_name.lower()

    # ตรวจสอบว่าเป็นโรคที่มีพาหะหรือไม่
    # เรียง key ยาวที่สุดก่อน เพื่อให้ "cassava witches' broom" match ก่อน "witches' broom"
    sorted_keys = sorted(VECTOR_DISEASES.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in disease_lower:
            info = VECTOR_DISEASES[key]
            logger.info(f"🐛 โรคนี้มีแมลงพาหะ: {info['pest']} → ค้นหาทั้งยาฆ่าแมลงและยารักษาโรค")
            # Return both: vector search + disease treatment search
            disease_treatment_query = info.get("disease_query", f"{disease_name} ยารักษา โรคพืช")
            return (info["search_query"], info["pest"], disease_treatment_query)

    # ถ้าเป็นไวรัส → แนะนำให้หาพาหะ
    if pest_type and "ไวรัส" in pest_type.lower():
        logger.info("🦠 โรคไวรัส → ค้นหายาฆ่าแมลงสำหรับพาหะ")
        return (f"{disease_name} ยาฆ่าแมลง พาหะ", None, None)

    return (disease_name, None, None)


# =============================================================================
# Hybrid Search Functions (Vector + BM25/Keyword)
# =============================================================================

async def hybrid_search_products(query: str, match_count: int = 15,
                                  vector_weight: float = 0.6,
                                  keyword_weight: float = 0.4) -> List[Dict]:
    """
    Perform Hybrid Search combining Vector Search + Keyword/BM25 Search
    Uses Reciprocal Rank Fusion (RRF) for combining results
    """
    try:
        if not supabase_client or not openai_client:
            logger.warning("Supabase or OpenAI client not available for hybrid search")
            return []

        logger.info(f"🔍 Hybrid Search: '{query}' (vector={vector_weight}, keyword={keyword_weight})")

        # Generate embedding for vector search
        response = await openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query,
            encoding_format="float"
        )
        query_embedding = response.data[0].embedding

        # Try hybrid_search_mahbin_npk RPC first (if SQL function exists)
        try:
            result = supabase_client.rpc(
                'hybrid_search_mahbin_npk',
                {
                    'query_embedding': query_embedding,
                    'search_query': query,
                    'vector_weight': vector_weight,
                    'keyword_weight': keyword_weight,
                    'match_count': match_count
                }
            ).execute()

            if result.data:
                logger.info(f"✓ Hybrid search returned {len(result.data)} products")
                return result.data

        except Exception as e:
            logger.warning(f"hybrid_search_mahbin_npk RPC failed: {e}, falling back to manual hybrid search")

        # Fallback: Manual hybrid search (Vector + Keyword separately)
        return await manual_hybrid_search(query, query_embedding, match_count, vector_weight, keyword_weight)

    except Exception as e:
        logger.error(f"Hybrid search failed: {e}", exc_info=True)
        return []


async def manual_hybrid_search(query: str, query_embedding: List[float],
                                match_count: int = 15,
                                vector_weight: float = 0.6,
                                keyword_weight: float = 0.4) -> List[Dict]:
    """
    Manual Hybrid Search fallback - runs vector and keyword search separately
    then combines with Reciprocal Rank Fusion (RRF)
    """
    try:
        # 1. Vector Search via mahbin_npk
        vector_results = []
        try:
            result = supabase_client.rpc(
                'hybrid_search_mahbin_npk',
                {
                    'query_embedding': query_embedding,
                    'search_query': query,
                    'vector_weight': 1.0,
                    'keyword_weight': 0.0,
                    'match_count': match_count * 2
                }
            ).execute()
            if result.data:
                vector_results = result.data
                logger.info(f"   Vector search: {len(vector_results)} results")
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")

        # 2. Keyword Search (ILIKE fallback on mahbin_npk)
        keyword_results = []
        try:
            result = supabase_client.table('mahbin_npk')\
                .select('*')\
                .or_(f"crop.ilike.%{query}%,"
                     f"growth_stage.ilike.%{query}%,"
                     f"fertilizer_formula.ilike.%{query}%,"
                     f"benefits.ilike.%{query}%")\
                .limit(match_count * 2)\
                .execute()
            if result.data:
                for i, p in enumerate(result.data):
                    p['rank'] = 1.0 / (i + 1)
                keyword_results = result.data
                logger.info(f"   Keyword search (ILIKE): {len(keyword_results)} results")
        except Exception as e:
            logger.warning(f"ILIKE search on mahbin_npk failed: {e}")

        # 3. Combine with RRF (Reciprocal Rank Fusion)
        combined = reciprocal_rank_fusion(
            vector_results, keyword_results,
            vector_weight, keyword_weight
        )

        logger.info(f"✓ Manual hybrid search combined: {len(combined)} products")
        return combined[:match_count]

    except Exception as e:
        logger.error(f"Manual hybrid search failed: {e}", exc_info=True)
        return []


def reciprocal_rank_fusion(vector_results: List[Dict], keyword_results: List[Dict],
                           vector_weight: float = 0.6, keyword_weight: float = 0.4,
                           k: int = 60) -> List[Dict]:
    """
    Combine vector and keyword search results using Reciprocal Rank Fusion (RRF)
    RRF score = sum(1 / (k + rank)) across all result sets

    Parameters:
    - k: constant to prevent high scores for top results (default 60)
    """
    try:
        # Build product lookup and RRF scores
        products_by_id = {}
        rrf_scores = {}

        # Process vector results
        for rank, product in enumerate(vector_results, 1):
            pid = product.get('id') or product.get('product_name')
            if pid:
                products_by_id[pid] = product
                rrf_scores[pid] = rrf_scores.get(pid, 0) + vector_weight * (1 / (k + rank))
                product['vector_rank'] = rank
                product['vector_score'] = product.get('similarity', 0)

        # Process keyword results
        for rank, product in enumerate(keyword_results, 1):
            pid = product.get('id') or product.get('product_name')
            if pid:
                if pid not in products_by_id:
                    products_by_id[pid] = product
                rrf_scores[pid] = rrf_scores.get(pid, 0) + keyword_weight * (1 / (k + rank))
                products_by_id[pid]['keyword_rank'] = rank
                products_by_id[pid]['keyword_score'] = product.get('rank', 0)

        # Add bonus for products appearing in both
        for pid in rrf_scores:
            product = products_by_id[pid]
            if product.get('vector_rank') and product.get('keyword_rank'):
                rrf_scores[pid] += 0.02  # Small bonus for appearing in both

        # Sort by RRF score
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

        # Build final results
        combined_results = []
        for pid in sorted_ids:
            product = products_by_id[pid].copy()
            product['hybrid_score'] = rrf_scores[pid]
            product['similarity'] = rrf_scores[pid]  # Use hybrid score as similarity
            combined_results.append(product)

        return combined_results

    except Exception as e:
        logger.error(f"RRF fusion failed: {e}", exc_info=True)
        # Fallback: return vector results
        return vector_results


### DEAD CODE REMOVED: fetch_products_by_names, retrieve_product_recommendation,
### build_recommendations_from_data, recommend_products_by_intent, format_product_list_simple,
### calculate_matching_score, retrieve_products_with_matching_score, answer_product_question
### All referenced the old 'products' table which no longer exists.
