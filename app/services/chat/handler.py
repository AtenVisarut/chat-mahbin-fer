import logging
import re
import asyncio
from typing import List, Dict, Optional, Tuple
from app.dependencies import openai_client, supabase_client
from app.services.memory import add_to_memory, get_conversation_context, get_recommended_products, get_enhanced_context
from app.utils.text_processing import extract_keywords_from_question, post_process_answer
from app.services.product.recommendation import hybrid_search_products, filter_products_by_category
from app.config import USE_AGENTIC_RAG
from app.prompts import GENERAL_CHAT_PROMPT, ERROR_GENERIC, ERROR_AI_UNAVAILABLE, GREETINGS, GREETING_KEYWORDS
from app.services.dealer_lookup import (
    is_dealer_question, extract_location, extract_location_llm, search_dealers,
    format_dealer_response, DEALER_SUGGESTION_SUFFIX, extract_province_from_context,
    search_dealers_with_fallback, message_has_explicit_province,
)
from app.services.cache import save_pending_context
from app.services.rag import IntentType

logger = logging.getLogger(__name__)

# Import AgenticRAG (lazy import to avoid circular dependencies)
_agentic_rag = None
_agentic_rag_lock = asyncio.Lock()

async def _get_agentic_rag():
    """Lazy import and get AgenticRAG instance (async-safe with lock)"""
    global _agentic_rag
    if _agentic_rag is not None:
        return _agentic_rag
    if not USE_AGENTIC_RAG:
        return None
    async with _agentic_rag_lock:
        # Double-check after acquiring lock
        if _agentic_rag is None:
            from app.services.rag.orchestrator import get_agentic_rag
            _agentic_rag = get_agentic_rag()
    return _agentic_rag

# =============================================================================
# คำสำคัญสำหรับตรวจจับคำถามเรื่องพืช/โรคพืช/การเกษตร
# =============================================================================
AGRICULTURE_KEYWORDS = [
    # พืช (6 crops ในฐานข้อมูล mahbin_npk)
    "ข้าว", "นาข้าว", "ข้าวโพด", "อ้อย", "มันสำปะหลัง", "มันสัมปะหลัง",
    "ยางพารา", "ปาล์ม", "ปาล์มน้ำมัน",
    # ปุ๋ย/ธาตุอาหาร
    "ปุ๋ย", "สูตรปุ๋ย", "ธาตุอาหาร", "ไนโตรเจน", "ฟอสฟอรัส", "โพแทสเซียม",
    "NPK", "N-P-K", "ยูเรีย", "บำรุง", "เสริมผลผลิต",
    # ระยะการเจริญเติบโต
    "เร่งต้น", "แตกกอ", "รับรวง", "รองพื้น", "แต่งหน้า", "ตั้งท้อง",
    # การเกษตรทั่วไป
    "ระยะ", "ช่วง", "ปลูก", "เก็บเกี่ยว", "ดูแล", "บำรุง",
    "ไร่", "กิโล", "อัตราใส่", "ใส่ปุ๋ย",
]


def is_agriculture_question(message: str) -> bool:
    """ตรวจสอบว่าเป็นคำถามเกี่ยวกับการเกษตร/พืช/โรคพืชหรือไม่"""
    message_lower = message.lower()
    for keyword in AGRICULTURE_KEYWORDS:
        if keyword in message_lower:
            return True
    return False


# =============================================================================
# Non-agriculture detection (สำหรับ RAG-first routing)
# ใช้จับข้อความสั้นที่ชัดเจนว่าไม่เกี่ยวกับเกษตร เช่น ทักทาย/ขอบคุณ/ลา
# ถ้าไม่ชัดว่า non-agri → ส่ง RAG เป็น default (ปลอดภัยกว่า general chat)
# =============================================================================
_NON_AGRI_KEYWORDS = [
    # ขอบคุณ / รับทราบ
    "ขอบคุณ", "ขอบใจ", "thank",
    # ลาก่อน
    "บาย", "ลาก่อน", "ไว้คุยกัน", "bye",
    # หัวเราะ / อารมณ์
    "555", "ฮ่าๆ", "ฮ่าฮ่า",
    # ถามเกี่ยวกับ bot
    "ชื่ออะไร", "เป็นใคร", "อายุเท่าไหร่", "เป็นคน", "เป็น ai",
    # รับทราบสั้นๆ
    "โอเค", "เข้าใจแล้ว", "ได้เลย", "ตกลง", "ok",
    # ชม
    "เก่งมาก", "เจ๋ง",
]


def _is_clearly_non_agriculture(message: str) -> bool:
    """ตรวจสอบว่าข้อความเป็น non-agriculture ชัดเจน (สั้น + ไม่เกี่ยวกับเกษตร)

    ใช้สำหรับ RAG-first routing:
    - ถ้า True → ส่ง general chat (neutered, ไม่มี expertise เกษตร)
    - ถ้า False → ส่ง RAG เป็น default (ปลอดภัยกว่า)
    - เงื่อนไข: ข้อความสั้น (≤ 20 chars) + มี keyword non-agri
    """
    msg = message.strip().lower()
    if len(msg) > 20:
        return False
    return any(kw in msg for kw in _NON_AGRI_KEYWORDS)


# =============================================================================
# Keywords สำหรับตรวจจับคำถามเกี่ยวกับสินค้า/ผลิตภัณฑ์
# =============================================================================
PRODUCT_KEYWORDS = [
    "ปุ๋ย", "สูตรปุ๋ย", "สูตร", "ธาตุอาหาร", "ใส่ปุ๋ย", "แนะนำปุ๋ย",
    "ปุ๋ยอะไรดี", "ใช้ปุ๋ยอะไร", "อัตราใส่", "เร่งต้น", "แตกกอ",
    "รับรวง", "รองพื้น", "แต่งหน้า", "บำรุง", "เสริมผลผลิต",
    "ม้าบิน", "mahbin",
]

# =============================================================================
# รายชื่อสินค้า ม้าบิน — Proxy ไปยัง ProductRegistry (DB-driven)
# ไฟล์อื่นที่ import ICP_PRODUCT_NAMES ยังใช้ได้เหมือนเดิม
# =============================================================================
from app.services.product.registry import ProductRegistry


class _ProductNamesProxy(dict):
    """Dict-like proxy that delegates to ProductRegistry singleton.
    Existing code doing `ICP_PRODUCT_NAMES.get(...)`, `ICP_PRODUCT_NAMES.keys()`,
    `name in ICP_PRODUCT_NAMES`, etc. works without changes."""

    def _reg(self):
        return ProductRegistry.get_instance()

    def __contains__(self, key):
        return self._reg().is_known_product(key)

    def __getitem__(self, key):
        aliases = self._reg().get_aliases(key)
        if not self._reg().is_known_product(key):
            raise KeyError(key)
        return aliases

    def get(self, key, default=None):
        if self._reg().is_known_product(key):
            return self._reg().get_aliases(key)
        return default

    def keys(self):
        return self._reg().get_canonical_list()

    def values(self):
        d = self._reg().get_product_names_dict()
        return d.values()

    def items(self):
        return self._reg().get_product_names_dict().items()

    def __iter__(self):
        return iter(self._reg().get_canonical_list())

    def __len__(self):
        return len(self._reg().get_canonical_list())

    def __bool__(self):
        return True

    def __repr__(self):
        return f"<_ProductNamesProxy({len(self)} products)>"


ICP_PRODUCT_NAMES = _ProductNamesProxy()


def extract_product_name_from_question(question: str) -> Optional[str]:
    """ดึงชื่อสินค้าจากคำถาม — delegate ไปยัง ProductRegistry"""
    return ProductRegistry.get_instance().extract_product_name(question)


def fuzzy_match_product_name(text: str, threshold: float = 0.65) -> Optional[str]:
    """Fuzzy matching สำหรับชื่อสินค้าที่พิมพ์ผิด — delegate ไปยัง ProductRegistry"""
    return ProductRegistry.get_instance().fuzzy_match(text, threshold)


def detect_unknown_product_in_question(question: str) -> Optional[str]:
    """
    ตรวจสอบว่า user ถามเกี่ยวกับสินค้าที่ไม่มีใน ICP_PRODUCT_NAMES หรือไม่
    Returns: ชื่อสินค้าที่ไม่รู้จัก หรือ None

    หมายเหตุ: ใช้เฉพาะกรณีที่ user ถามชื่อสินค้าโดยตรง เช่น "โตโร่ ใช้ยังไง"
    ไม่ใช้กับคำถามทั่วไป เช่น "แนะนำยาตัวไหน"
    """
    # ถ้าพบสินค้าที่รู้จักแล้ว → return None
    if extract_product_name_from_question(question):
        return None

    # คำที่ต้องข้าม (คำทั่วไป, คำถาม, คำกริยา)
    skip_words = [
        'อะไร', 'ยังไง', 'อย่างไร', 'เท่าไหร่', 'ตัวไหน', 'กี่', 'ทำไม', 'ไหม',
        'ใช้', 'พ่น', 'ฉีด', 'ผสม', 'กำจัด', 'รักษา', 'แนะนำ', 'ดี', 'ได้',
        'ยา', 'สาร', 'โรค', 'แมลง', 'หญ้า', 'วัชพืช', 'ธาตุ', 'อาหาร',
        'ข้าว', 'ทุเรียน', 'มะม่วง', 'ส้ม', 'พริก', 'ข้าวโพด', 'อ้อย',
        'นา', 'ไร่', 'สวน', 'ต้น', 'ใบ', 'ผล', 'ดอก',
        'ฆ่า', 'ป้องกัน', 'ควบคุม', 'ขาด', 'ร่วง', 'เหลือง', 'จุด',
        'สำคัญ', 'ที่สุด', 'บำรุง', 'ติด', 'การ'
    ]

    # pattern สำหรับตรวจจับชื่อสินค้าที่ไม่รู้จัก
    # เฉพาะกรณี "XXX ใช้ยังไง" ที่ XXX เป็นชื่อสินค้าโดยตรง
    import re

    # Pattern 1: "XXX ใช้ยังไง" - XXX ต้องขึ้นต้นประโยค
    match = re.match(r'^([ก-๙a-zA-Z]+)\s+(?:ใช้|พ่น|ฉีด|ผสม)', question.strip())
    if match:
        potential_product = match.group(1)
        # ตรวจสอบว่าไม่ใช่คำทั่วไป และมีความยาวเหมาะสม
        if potential_product.lower() not in [w.lower() for w in skip_words]:
            if 2 < len(potential_product) < 20:
                return potential_product

    return None


def extract_plant_type_from_question(question: str) -> Optional[str]:
    """
    ดึงชื่อพืชจากคำถาม
    Returns: ชื่อพืช หรือ None ถ้าไม่พบ
    """
    # รายชื่อพืชที่รองรับ
    plants = [
        "ทุเรียน", "ข้าว", "ข้าวโพด", "มันสำปะหลัง", "อ้อย", "ยางพารา", "ปาล์ม",
        "มะม่วง", "ลำไย", "ลิ้นจี่", "เงาะ", "มังคุด", "พริก", "มะเขือเทศ",
        "ถั่ว", "กล้วย", "มะพร้าว", "ส้ม", "มะนาว", "ฝรั่ง", "ชมพู่",
        "สับปะรด", "หอมแดง", "กระเทียม", "ผัก", "ไม้ผล"
    ]

    question_lower = question.lower()
    for plant in plants:
        if plant in question_lower:
            return plant
    return None


def is_product_question(message: str) -> bool:
    """ตรวจสอบว่าเป็นคำถามเกี่ยวกับสินค้า/ผลิตภัณฑ์หรือไม่"""
    message_lower = message.lower()
    for keyword in PRODUCT_KEYWORDS:
        if keyword in message_lower:
            return True
    return False


# =============================================================================
# ตรวจจับประเภทปัญหา: โรค vs แมลง vs ธาตุอาหาร vs วัชพืช
# =============================================================================
DISEASE_KEYWORDS = [
    # โรคทั่วไป
    "โรค", "ใบจุด", "ใบไหม้", "ราน้ำค้าง", "ราแป้ง", "ราสนิม", "เชื้อรา",
    "แอนแทรคโนส", "ผลเน่า", "รากเน่า", "โคนเน่า", "ลำต้นเน่า", "กิ่งแห้ง",
    "ราดำ", "จุดสีน้ำตาล", "ใบแห้ง", "ไฟท็อป", "ไฟทิป", "ไฟทอป", "ใบติด", "ดอกกระถิน", "เมล็ดด่าง",
    # English
    "disease", "fungus", "fungal", "rot", "blight", "mildew", "rust", "anthracnose"
]

INSECT_KEYWORDS = [
    # แมลง (หมายเหตุ: หลีกเลี่ยง "ไร" เพราะจะ match กับ "อะไร")
    "แมลง", "เพลี้ย", "หนอน", "ด้วง", "มด", "ปลวก", "เพลี้ยไฟ",
    "เพลี้ยอ่อน", "เพลี้ยแป้ง", "เพลี้ยกระโดด", "หนอนกอ", "หนอนเจาะ",
    "หนอนใย", "แมลงวัน", "จักจั่น", "ทริปส์", "ศัตรูพืช",
    "ไรแดง", "ไรขาว", "ไรแมง", "ตัวไร",
    # English
    "insect", "pest", "aphid", "thrips", "mite", "worm", "caterpillar", "beetle"
]

# เพิ่ม: Keywords สำหรับธาตุอาหาร/การบำรุง
NUTRIENT_KEYWORDS = [
    # ขาดธาตุ/บำรุง
    "ขาดธาตุ", "ธาตุอาหาร", "บำรุง", "เสริมธาตุ", "ปุ๋ย",
    # อาการ
    "ดอกร่วง", "ผลร่วง", "ใบเหลือง", "ใบร่วง", "ไม่ติดดอก", "ไม่ติดผล",
    "ดอกไม่ติด", "ผลไม่ติด", "ต้นโทรม", "ต้นไม่สมบูรณ์",
    # การบำรุง
    "ติดดอก", "ติดผล", "ขยายผล", "บำรุงดอก", "บำรุงผล", "บำรุงต้น",
    "เร่งดอก", "เร่งผล", "สะสมอาหาร", "เพิ่มผลผลิต",
    # ธาตุเฉพาะ
    "โพแทสเซียม", "ฟอสฟอรัส", "ไนโตรเจน", "แคลเซียม", "โบรอน", "สังกะสี", "ซิงค์"
]

# เพิ่ม: Keywords สำหรับวัชพืช
WEED_KEYWORDS = [
    "หญ้า", "วัชพืช", "กำจัดหญ้า", "ยาฆ่าหญ้า", "หญ้าขึ้น", "หญ้างอก",
    "ใบแคบ", "ใบกว้าง", "กก"
]


# =============================================================================
# Farmer Slang → Technical Terms Mapping
# =============================================================================
FARMER_SLANG_MAP = {
    "ยาดูด": {"hint": "สารดูดซึม (systemic insecticide/fungicide) ไม่ใช่สารควบคุมการเจริญเติบโต", "search_terms": ["ดูดซึม", "สารกำจัดแมลง", "สารป้องกันโรค"]},
    "ยาสัมผัส": {"hint": "สารสัมผัส (contact)", "search_terms": ["สัมผัส", "contact"]},
    "ยาเผาไหม้": {"hint": "ยาฆ่าหญ้าสัมผัส", "category": "Herbicide", "search_terms": ["เผาไหม้"]},
    "ยาคลุม": {"hint": "สารก่อนงอก (pre-emergent)", "search_terms": ["ก่อนงอก"]},
    "ต้นโทรม": {"hint": "ต้นไม่สมบูรณ์/ขาดธาตุอาหาร", "problem_type": "nutrient"},
    "ใบม้วน": {"hint": "ใบม้วนงอ อาจจากเพลี้ยหรือไวรัส", "problem_type": "insect"},
    "ต้นเหลือง": {"hint": "ใบเหลือง/ขาดธาตุอาหาร", "problem_type": "nutrient"},
    "ราขึ้น": {"hint": "เชื้อราเข้าทำลาย", "problem_type": "disease"},
    "แมลงกัด": {"hint": "แมลงกัดกิน/เจาะ", "problem_type": "insect"},
    "หนอนเจาะ": {"hint": "หนอนเจาะลำต้น/ผล", "problem_type": "insect"},
    "ข้าวดื้อยา": {"hint": "วัชพืชดื้อสารเคมี ต้องเปลี่ยนกลุ่มสาร", "problem_type": "weed"},
    "หญ้าดื้อ": {"hint": "วัชพืชดื้อสารเคมี", "problem_type": "weed"},
    "ดอกกระถิน": {"hint": "โรคเมล็ดด่าง/ดอกกระถิน (false smut) ในข้าว", "problem_type": "disease", "search_terms": ["เมล็ดด่าง", "ดอกกระถิน", "false smut"]},
    "ไฟทิป": {"hint": "โรคไฟท็อปทอร่า (Phytophthora) - โรครากเน่า/โคนเน่า", "problem_type": "disease", "search_terms": ["ไฟท็อปธอร่า", "Phytophthora", "รากเน่า", "โคนเน่า"]},
    "ไฟทอป": {"hint": "โรคไฟท็อปทอร่า (Phytophthora) - โรครากเน่า/โคนเน่า", "problem_type": "disease", "search_terms": ["ไฟท็อปธอร่า", "Phytophthora", "รากเน่า", "โคนเน่า"]},
}


def resolve_farmer_slang(query: str) -> dict:
    """
    ตรวจจับคำภาษาชาวบ้านในคำถามและแปลเป็นคำทางเทคนิค

    Returns:
        {
            "matched_slangs": [str],
            "hints": str,           # ข้อความ hint สำหรับ inject เข้า LLM prompt
            "search_terms": [str],  # คำค้นเพิ่มเติมสำหรับ retrieval
            "problem_type": str|None
        }
    """
    result = {
        "matched_slangs": [],
        "hints": "",
        "search_terms": [],
        "problem_type": None,
    }

    query_lower = query.lower()
    hint_parts = []

    for slang, info in FARMER_SLANG_MAP.items():
        if slang in query_lower:
            result["matched_slangs"].append(slang)
            hint_parts.append(f'"{slang}" หมายถึง {info["hint"]}')
            if info.get("search_terms"):
                result["search_terms"].extend(info["search_terms"])
            if info.get("problem_type") and not result["problem_type"]:
                result["problem_type"] = info["problem_type"]

    if hint_parts:
        result["hints"] = "; ".join(hint_parts)

    return result


def detect_problem_type(message: str) -> str:
    """
    ตรวจจับประเภทปัญหา
    Returns: 'disease', 'insect', 'nutrient', 'weed', หรือ 'unknown'

    Priority: nutrient > disease > insect > weed > unknown
    (เพราะคำถามเรื่องบำรุงมักมีคำว่า "ใบเหลือง" ซึ่งอาจซ้ำกับ disease)
    """
    from app.utils.text_processing import diacritics_match
    message_lower = message.lower()

    # นับ keywords แต่ละประเภท (diacritics-tolerant)
    nutrient_count = sum(1 for kw in NUTRIENT_KEYWORDS if diacritics_match(message_lower, kw))
    disease_count = sum(1 for kw in DISEASE_KEYWORDS if diacritics_match(message_lower, kw))
    insect_count = sum(1 for kw in INSECT_KEYWORDS if diacritics_match(message_lower, kw))
    weed_count = sum(1 for kw in WEED_KEYWORDS if diacritics_match(message_lower, kw))

    # หา max count
    counts = {
        'nutrient': nutrient_count,
        'disease': disease_count,
        'insect': insect_count,
        'weed': weed_count
    }

    max_count = max(counts.values())
    if max_count == 0:
        return 'unknown'

    # Return ตาม priority: nutrient > disease > insect > weed
    if counts['nutrient'] == max_count:
        return 'nutrient'
    elif counts['disease'] == max_count:
        return 'disease'
    elif counts['insect'] == max_count:
        return 'insect'
    elif counts['weed'] == max_count:
        return 'weed'
    else:
        return 'unknown'


# =============================================================================
# Vector Search Functions สำหรับ Q&A
# =============================================================================
async def generate_embedding(text: str) -> List[float]:
    """Generate embedding for search query using OpenAI"""
    if not openai_client:
        logger.error("OpenAI client not available")
        return []

    try:
        response = await openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
            encoding_format="float"
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        return []


async def vector_search_products(query: str, top_k: int = 5) -> List[Dict]:
    """Vector search จากตาราง products"""
    try:
        # ใช้ hybrid_search_products ที่มีอยู่แล้ว
        products = await hybrid_search_products(
            query=query,
            match_count=top_k,
            vector_weight=0.6,
            keyword_weight=0.4
        )
        if products:
            logger.info(f"✓ Found {len(products)} products via vector search")
        return products or []
    except Exception as e:
        logger.error(f"Product vector search failed: {e}")
        return []


# =============================================================================
# Mapping: problem_type → product_category ใน products table
# =============================================================================
PROBLEM_TYPE_TO_PRODUCT_CATEGORY = {
    'disease': 'Fungicide',
    'insect': 'Insecticide',
    'nutrient': 'Fertilizer',
    'weed': 'Herbicide'
}


async def vector_search_products_for_qa(
    query: str,
    top_k: int = 5,
    validate_product: bool = True,
    problem_type: str = None
) -> Tuple[List[Dict], Optional[str]]:
    """
    Vector search จากตาราง products พร้อมกรองตาม category/product/plant

    Args:
        query: คำถาม
        top_k: จำนวนผลลัพธ์สูงสุด
        validate_product: ตรวจสอบว่าชื่อสินค้าตรงกับผลลัพธ์หรือไม่
        problem_type: 'disease', 'insect', 'nutrient', 'weed' หรือ None

    Returns:
        Tuple[results, product_not_found_message]
    """
    if not supabase_client or not openai_client:
        return [], None

    try:
        product_in_question = extract_product_name_from_question(query)
        plant_in_question = extract_plant_type_from_question(query)

        if problem_type is None:
            problem_type = detect_problem_type(query)

        # ค้นหาจาก products table (hybrid search)
        all_products = await vector_search_products(query, top_k=top_k * 10)

        if not all_products:
            if product_in_question:
                return [], f"ไม่พบข้อมูลเกี่ยวกับ \"{product_in_question}\" ในฐานข้อมูล"
            return [], None

        logger.info(f"✓ Found {len(all_products)} products via hybrid search (problem_type={problem_type})")

        filtered_results = all_products

        # กรองตาม product_category ตามประเภทปัญหา
        if problem_type in PROBLEM_TYPE_TO_PRODUCT_CATEGORY:
            required_category = PROBLEM_TYPE_TO_PRODUCT_CATEGORY[problem_type]
            category_filtered = filter_products_by_category(filtered_results, required_category)

            if category_filtered:
                filtered_results = category_filtered
                logger.info(f"✓ Filtered to {len(filtered_results)} {problem_type}-related products")
            else:
                logger.info(f"⚠️ No {problem_type} category found, using all results")

        # ถ้าถามเกี่ยวกับสินค้าเฉพาะ → กรองเฉพาะสินค้าที่ตรงกับชื่อ
        if product_in_question:
            product_lower = product_in_question.lower()
            aliases = ICP_PRODUCT_NAMES.get(product_in_question, [product_in_question])

            matched = []
            for p in filtered_results:
                pname = (p.get('product_name') or '').lower()
                target = (p.get('target_pest') or '').lower()
                for alias in aliases:
                    if alias.lower() in pname or alias.lower() in target:
                        matched.append(p)
                        break

            if matched:
                logger.info(f"✓ Validated: {len(matched)} results match product '{product_in_question}'")
                return matched[:top_k], None
            else:
                if validate_product:
                    logger.warning(f"⚠️ ถามเกี่ยวกับ '{product_in_question}' แต่ไม่พบข้อมูลตรง")
                    return [], f"ไม่พบข้อมูลเกี่ยวกับ \"{product_in_question}\" ในฐานข้อมูล กรุณาตรวจสอบชื่อสินค้าอีกครั้ง"
                else:
                    logger.info(f"ℹ️ ไม่พบ '{product_in_question}' ตรงๆ ใช้ผลลัพธ์จาก vector search")
                    return filtered_results[:top_k], None

        # กรองตาม plant_type ถ้ามี (ใช้ applicable_crops)
        if plant_in_question:
            plant_lower = plant_in_question.lower()
            plant_filtered = []
            for p in filtered_results:
                applicable = (p.get('applicable_crops') or '').lower()
                pname = (p.get('product_name') or '').lower()
                target = (p.get('target_pest') or '').lower()
                if plant_lower in applicable or plant_lower in pname or plant_lower in target:
                    plant_filtered.append(p)

            if plant_filtered:
                filtered_results = plant_filtered
                logger.info(f"✓ Filtered to {len(filtered_results)} products for plant '{plant_in_question}'")

        return filtered_results[:top_k], None

    except Exception as e:
        logger.error(f"Products vector search for QA failed: {e}")
        return [], None


async def answer_qa_with_vector_search(question: str, context: str = "") -> str:
    """
    ตอบคำถาม Q&A โดยใช้ Vector Search จาก products table เป็นหลัก
    พร้อมกรองตาม category (โรค vs แมลง)

    Flow ที่ถูกต้อง:
    1. รับคำถามจาก user
    2. ตรวจจับ: ชื่อสินค้า, ชื่อพืช, ประเภทปัญหา
    3. ถ้าถามเรื่องโรค/แมลง แต่ไม่ระบุพืช → ถามพืชก่อน
    4. ถ้าถามเรื่องสินค้าเฉพาะแต่ไม่ระบุพืช → ถามพืชก่อน (เพื่อให้อัตราการใช้ถูกต้อง)
    5. ค้นหาจาก products table
    6. ตอบเฉพาะข้อมูลที่มีใน DB - ห้าม hallucinate
    """
    try:
        logger.info(f"Q&A Vector Search: {question[:50]}...")

        # ตรวจสอบว่าเป็นคำถามประเภทไหน
        is_product_q = is_product_question(question)
        is_agri_q = is_agriculture_question(question)

        # ตรวจจับประเภทปัญหา (โรค vs แมลง)
        problem_type = detect_problem_type(question)
        plant_in_question = extract_plant_type_from_question(question)
        product_in_question = extract_product_name_from_question(question)

        logger.info(f"Detected: problem_type={problem_type}, plant={plant_in_question}, product={product_in_question}")

        # =================================================================
        # STEP 2: ถ้าคำถามสั้นเกินไป (เช่น "อัตราการใช้") → ถามรายละเอียด
        # =================================================================
        short_questions = ['อัตราการใช้', 'วิธีใช้', 'อัตราผสม', 'ผสมยังไง', 'ใช้ยังไง', 'อัตรา']
        is_very_short = question.strip() in short_questions or (len(question.strip()) < 12 and not product_in_question and not plant_in_question)

        # เช็คคำถามถามขนาดถัง
        tank_keywords = ['ถังเล็ก', 'ถังใหญ่', 'ถัง 20', 'ถัง 100', 'ถัง 200', 'ถังพ่น', 'กี่ลิตร']
        is_tank_question = any(kw in question.lower() for kw in tank_keywords)

        if is_tank_question:
            # Extract tank size from question
            tank_size_match = re.search(r'(\d+)\s*ลิตร', question)
            if tank_size_match:
         
                tank_size = int(tank_size_match.group(1))
                logger.info(f"ถามถังขนาด {tank_size} ลิตร")
                # ถ้าระบุขนาดถังแล้ว → ไปค้นหาข้อมูลต่อ (จะคำนวณในส่วน response)
            elif 'ถังเล็ก' in question.lower():
                logger.info(f"ถามถังเล็ก → ถามขนาดที่แน่นอน")
                return "ขอทราบขนาดถังเล็กกี่ลิตรด้วยครับ จะได้คำนวณให้เป๊ะนะครับ\n\nตัวอย่างถัง 20 ลิตร: พี่ม้าบินจะคำนวณอัตราให้ตามขนาดถังที่บอกครับ"
            elif 'ถังใหญ่' in question.lower():
                logger.info(f"ถามถังใหญ่ → ถามขนาดที่แน่นอน")
                return "ถังใหญ่กี่ลิตรคะ บอกพี่ม้าบินนิด จะได้คำนวณให้ตรงครับ\n\nตัวอย่างคำนวณให้ก่อนนะครับ\n- ถัง 200 ลิตร: ใช้อัตราตามฉลาก\n- ถัง 100 ลิตร: ลดครึ่งจากอัตราปกติ"

        if is_very_short and problem_type == 'unknown' and not is_tank_question:
            logger.info(f"⚠️ คำถามสั้นไม่มีรายละเอียด: {question}")
            return "ขอทราบรายละเอียดเพิ่มเติมครับ\n- ต้องการทราบข้อมูลของสินค้าตัวไหนครับ?\n- และใช้กับพืชอะไรครับ?\n\nเพื่อให้พี่ม้าบินตอบได้ถูกต้องครับ"

        # =================================================================
        # STEP 2.5: ถ้าถามเกี่ยวกับสินค้าที่ไม่มีใน ICP → บอกว่าไม่มี
        # =================================================================
        unknown_product = detect_unknown_product_in_question(question)
        if unknown_product and not product_in_question:
            logger.info(f"⚠️ ถามเกี่ยวกับสินค้าที่ไม่รู้จัก: {unknown_product}")
            return f"ขออภัยครับ ไม่พบข้อมูลสินค้า \"{unknown_product}\" ในฐานข้อมูลของ ม้าบิน ครับ\n\nกรุณาตรวจสอบชื่อสินค้าอีกครั้ง หรือสอบถามเกี่ยวกับสินค้าอื่นได้เลยครับ"

        # =================================================================
        # STEP 3: ถ้าถามเรื่องโรค/แมลง แต่ไม่ระบุพืช → ถามพืชก่อน
        # =================================================================
        # ตรวจสอบว่าเป็นคำถาม "รักษา/กำจัด" ที่ต้องการสินค้า
        is_treatment_question = any(kw in question.lower() for kw in [
            'รักษา', 'กำจัด', 'แนะนำ', 'ใช้ยา', 'ยาอะไร', 'สารอะไร',
            'ป้องกัน', 'ฆ่า', 'ควบคุม', 'จัดการ'
        ])

        # ถ้าถามเรื่องโรค/แมลง และต้องการรักษา แต่ไม่ระบุพืช → ถามพืชก่อน
        if problem_type in ['insect', 'disease'] and is_treatment_question and not plant_in_question and not product_in_question:
            logger.info(f"⚠️ ถามเรื่อง {problem_type} แต่ไม่ระบุพืช → ถามพืชก่อน")
            # Extract ชื่อปัญหา/แมลง/โรค จากคำถาม
            from app.utils.text_processing import diacritics_match as _dm_kw
            problem_name = ""
            for kw in INSECT_KEYWORDS + DISEASE_KEYWORDS:
                if _dm_kw(question.lower(), kw) and len(kw) > 2:
                    problem_name = kw
                    break

            if problem_type == 'insect':
                return f"พี่ม้าบินขอเช็คให้ก่อนนะครับ จากข้อมูลสินค้า ยังไม่พบตัวยาที่ระบุใช้กับ \"{problem_name}\" โดยตรงครับ\n\nรบกวนบอกเพิ่มหน่อยว่าเป็นพืชอะไร และอยู่ช่วงไหน (แตกใบอ่อน/ออกดอก/ติดผล) จะได้ค้นหาตัวที่เหมาะให้ตรงที่สุดนะครับ"
            else:  # disease
                return f"พี่ม้าบินขอเช็คให้ก่อนนะครับ จากข้อมูลสินค้า ยังไม่พบตัวยาที่ระบุใช้กับ \"{problem_name}\" โดยตรงครับ\n\nรบกวนบอกเพิ่มหน่อยว่าเป็นพืชอะไร และอยู่ช่วงไหน (แตกใบอ่อน/ออกดอก/ติดผล) จะได้ค้นหาตัวที่เหมาะให้ตรงที่สุดนะครับ"

        # เก็บ context จากแต่ละ source
        all_context_parts = []

        # 1. ค้นหาจาก products table เป็นหลัก (แทน knowledge table)
        product_docs, product_not_found_msg = await vector_search_products_for_qa(
            question,
            top_k=5,
            validate_product=False,
            problem_type=problem_type
        )

        if product_docs:
            products_context = "ข้อมูลสินค้าและวิธีใช้:\n"
            for idx, doc in enumerate(product_docs[:5], 1):
                product_name = doc.get('product_name', '')
                active_ingredient = doc.get('active_ingredient', '')
                usage_rate = doc.get('usage_rate', '')
                target_pest = doc.get('target_pest', '')
                product_category = doc.get('product_category', '')
                applicable_crops = doc.get('applicable_crops', '')
                how_to_use = doc.get('how_to_use', '')
                usage_period = doc.get('usage_period', '')

                # แสดงในรูปแบบ "ชื่อสินค้า (สารสำคัญ)"
                if active_ingredient:
                    products_context += f"\n[{idx}] {product_name} (สารสำคัญ: {active_ingredient})"
                else:
                    products_context += f"\n[{idx}] {product_name}"
                if product_category:
                    products_context += f"\n   ประเภท: {product_category}"
                if target_pest:
                    products_context += f"\n   ใช้กำจัด: {target_pest[:150]}"
                if applicable_crops:
                    products_context += f"\n   พืชที่ใช้ได้: {applicable_crops[:150]}"
                if usage_rate:
                    products_context += f"\n   อัตราใช้: {usage_rate}"
                if how_to_use:
                    products_context += f"\n   วิธีใช้: {how_to_use[:200]}"
                if usage_period:
                    products_context += f"\n   ช่วงการใช้: {usage_period[:100]}"

            all_context_parts.append(products_context)
            logger.info(f"Added {len(product_docs)} products to context")

        elif product_not_found_msg:
            logger.warning(f"Product not found: {product_not_found_msg}")
            all_context_parts.append(f"หมายเหตุ: {product_not_found_msg}")

        # รวม context ทั้งหมด
        combined_context = "\n\n".join(all_context_parts) if all_context_parts else "(ไม่พบข้อมูลในฐานข้อมูล)"

        # ตรวจจับประเภทคำถาม
        is_what_question = any(kw in question.lower() for kw in ['ใช้ทำอะไร', 'คืออะไร', 'ใช้อะไร', 'ทำอะไร', 'เป็นอะไร'])
        is_how_question = any(kw in question.lower() for kw in ['ใช้ยังไง', 'ใช้อย่างไร', 'วิธีใช้', 'ผสมยังไง'])
        is_rate_question = any(kw in question.lower() for kw in ['อัตรา', 'ผสมเท่าไหร่', 'กี่ซีซี', 'กี่ลิตร'])
        # เพิ่ม: คำถามแนะนำสินค้า/สาร
        is_recommend_question = any(kw in question.lower() for kw in ['แนะนำ', 'ใช้ยาอะไร', 'ใช้สารอะไร', 'ยาตัวไหน', 'สารตัวไหน', 'ฉีดพ่น'])

        # สร้าง prompt ตามประเภทคำถาม
        if is_recommend_question and product_docs:
            # คำถามแนะนำสินค้า (มี product_docs แล้ว) → ตอบจากข้อมูลที่มี
            prompt = f"""คุณคือ "พี่ม้าบิน" ผู้เชี่ยวชาญด้านการเกษตรของ ม้าบิน

คำถาม: {question}

ข้อมูลจากฐานข้อมูล:
{combined_context}

หลักการตอบ (สำคัญมาก!):

2. ชื่อสินค้าต้องแสดงในรูปแบบ "ชื่อสินค้า (สารสำคัญ)" เช่น "โมเดิน 50 (โปรฟีโนฟอส)"
3. ถ้าเป็นวัชพืช → จัดกลุ่มตามช่วง:
   - ก่อนวัชพืชงอก: ใช้ "ชื่อยา (สาร)" อัตรา XX มล./ไร่ พ่น...
   - หลังวัชพืชงอก:
     - ทางเลือก 1: "ชื่อยา (สาร)" XX มล./ไร่ ...
     - ทางเลือก 2: "ชื่อยา (สาร)" XX มล./ไร่ ...

4. ถ้าเป็นแมลง/โรค → ตอบแบบนี้:
   จากข้อมูลสินค้า แนะนำ "ชื่อยา (สารสำคัญ)" ใช้กำจัด XX ได้ครับ
   - อัตราใช้: XX กรัม ต่อน้ำ XX ลิตร
   - วิธีใช้: ผสมน้ำตามอัตรา แล้วฉีดพ่นให้ทั่วทรงพุ่ม
   - ช่วงใช้: ใช้ได้ทุกระยะ

5. ปิดท้าย:
   - ถ้าผู้ใช้บอกขนาดถังหรือพื้นที่มาแล้ว → คำนวณอัตราให้เลย ไม่ต้องถามซ้ำ
   - ถ้ายังไม่บอก → ถามว่า "ถ้าบอกขนาดถังพ่น พี่ม้าบินช่วยคำนวณอัตราให้ได้ครับ"

6. ห้ามแต่งข้อมูลเอง ใช้เฉพาะที่มีในฐานข้อมูล
7. ห้ามใช้ ** หรือ ##
8. ใช้ emoji นำหน้าหัวข้อ เช่น 🦠 🌿 💊 📋 ⚖️ 📅 ⚠️ 💡
9. ใช้ ━━━━━━━━━━━━━━━ คั่นระหว่างส่วนหลักๆ

ตอบ:"""
        elif product_in_question and is_what_question:
            # คำถามแบบ "X ใช้ทำอะไร" → ตอบสั้นๆ + ถาม follow-up
            prompt = f"""คุณคือ "พี่ม้าบิน" ผู้เชี่ยวชาญด้านการเกษตรของ ม้าบิน

คำถาม: {question}

ข้อมูลจากฐานข้อมูล:
{combined_context}

หลักการตอบ (สำคัญมาก!):
2. ชื่อสินค้าต้องแสดงในรูปแบบ "ชื่อสินค้า (สารสำคัญ)" เช่น "โมเดิน 50 (โปรฟีโนฟอส)"
3. บอกว่าสินค้านี้คืออะไร ใช้ทำอะไร (2-3 ประโยค)
4. ปิดท้ายด้วยการถามข้อมูลเพิ่มเติม
5. ห้ามใช้ ** หรือ ##
6. ใช้ emoji นำหน้าหัวข้อ เช่น 💊 🌿 💡
7. ห้ามแต่งข้อมูลเอง

ตัวอย่างการตอบ:
จากข้อมูลสินค้า "โมเดิน 50 (โปรฟีโนฟอส)" เป็นสารกำจัดแมลงศัตรูพืช ใช้สำหรับกำจัดเพลี้ยแป้ง หนอน ในทุเรียนครับ

ต้องการทราบข้อมูลเพิ่มเติมไหมคะ เช่น วิธีใช้, อัตราผสม, หรือใช้กับพืชอะไรได้บ้าง?

ตอบ:"""
        elif product_in_question and (is_how_question or is_rate_question):
            # คำถามเฉพาะเจาะจง → ตอบเฉพาะสิ่งที่ถาม
            prompt = f"""คุณคือ "พี่ม้าบิน" ผู้เชี่ยวชาญด้านการเกษตรของ ม้าบิน

คำถาม: {question}

ข้อมูลจากฐานข้อมูล:
{combined_context}

หลักการตอบ:
1. เริ่มด้วย "จากข้อมูลสินค้า แนะนำ" หรือ "จากข้อมูลสินค้า"
2. ชื่อสินค้าต้องแสดงในรูปแบบ "ชื่อสินค้า (สารสำคัญ)" เช่น "แกนเตอร์ (ไซฮาโลฟอป-บิวทิล)"
3. ตอบแบบนี้:
   จากข้อมูลสินค้า แนะนำ "ชื่อยา (สารสำคัญ)" ... ครับ
   - อัตราใช้: XX กรัม/มล. ต่อน้ำ XX ลิตร
   - วิธีใช้: ผสมน้ำตามอัตรา แล้วฉีดพ่น...
   - ช่วงใช้: ใช้ได้ทุกระยะ / ช่วง...

   ถ้าผู้ใช้บอกขนาดถังหรือพื้นที่มาแล้ว → คำนวณอัตราให้เลย ไม่ต้องถามซ้ำ
   ถ้ายังไม่บอก → ถามว่า "ถ้าบอกขนาดถังพ่น พี่ม้าบินช่วยคำนวณอัตราให้ได้ครับ"

4. ห้ามแต่งข้อมูลเอง ใช้เฉพาะที่มีในฐานข้อมูล
5. ห้ามใช้ ** หรือ ##
6. ใช้ emoji นำหน้าหัวข้อ เช่น 💊 📋 ⚖️ ⚠️ 💡
7. ใช้ ━━━━━━━━━━━━━━━ คั่นระหว่างส่วนหลักๆ

ตอบ:"""
        else:
            # คำถามทั่วไป → ตอบตามปกติแต่กระชับ
            prompt = f"""คุณคือ "พี่ม้าบิน" ผู้เชี่ยวชาญด้านการเกษตรของ ม้าบิน

คำถาม: {question}

บริบท: {context if context else "(เริ่มสนทนาใหม่)"}

ข้อมูลจากฐานข้อมูล:
{combined_context}

หลักการตอบ (สำคัญมาก!):
2. ชื่อสินค้าต้องแสดงในรูปแบบ "ชื่อสินค้า (สารสำคัญ)" เช่น "โมเดิน 50 (โปรฟีโนฟอส)"

3. ถ้าเป็นวัชพืช → จัดกลุ่มตามช่วง:
   จากข้อมูลสินค้า จัดการ "ชื่อวัชพืช" ใน... เลือกใช้ตามช่วงนี้ได้เลยครับ
   - ก่อนวัชพืชงอก: ใช้ "ชื่อยา (สารสำคัญ)" อัตรา XX มล./ไร่ พ่นหลังหว่าน X วัน...
   - หลังวัชพืชงอก:
     - ทางเลือก 1: "ชื่อยา (สารสำคัญ)" XX มล./ไร่ ร่วมกับ "ชื่อยา (สารสำคัญ)" XX มล./ไร่ พ่นหลังหว่าน X วัน...
     - ทางเลือก 2: "ชื่อยา (สารสำคัญ)" XX มล./ไร่ พ่นหลังหว่าน X วัน...

4. ถ้าเป็นแมลง/โรค → ตอบแบบนี้:
   จากข้อมูลสินค้า แนะนำ "ชื่อยา (สารสำคัญ)" ใช้กำจัด XX ใน YY ได้ครับ
   - อัตราใช้: XX กรัม ต่อน้ำ XX ลิตร
   - วิธีใช้: ผสมน้ำตามอัตรา แล้วฉีดพ่นให้ทั่วทรงพุ่ม
   - ช่วงใช้: ใช้ได้ทุกระยะ ทั้งแตกใบอ่อน ออกดอก และติดผล

5. ปิดท้าย:
   - ถ้าผู้ใช้บอกขนาดถังหรือพื้นที่มาแล้ว → คำนวณอัตราให้เลย ไม่ต้องถามซ้ำ
   - ถ้ายังไม่บอก → ถามว่า "บอกพี่ม้าบินหน่อยครับ ใช้ถังพ่นกี่ลิตร พี่ม้าบินคำนวณอัตราต่อถังให้เป๊ะๆ ได้เลยครับ"

6. ถ้าคำถามไม่ชัดเจน ให้ถามกลับ เช่น "ขอทราบชื่อพืชด้วยครับ?"
7. ห้ามแต่งข้อมูลเอง ใช้เฉพาะที่มีในฐานข้อมูล
8. ห้ามใช้ ** หรือ ##
9. ใช้ emoji นำหน้าหัวข้อ เช่น 🦠 🌿 💊 📋 ⚖️ 📅 ⚠️ 💡
10. ใช้ ━━━━━━━━━━━━━━━ คั่นระหว่างส่วนหลักๆ

ตอบ:"""

        if not openai_client:
            return "ขออภัยครับ ระบบ AI ไม่พร้อมใช้งานในขณะนี้"

        # ถ้าไม่พบข้อมูลในฐานข้อมูล → บอกตรงๆ
        if not product_docs:
            return f"พี่ม้าบินขอเช็คให้ก่อนนะครับ จากข้อมูลสินค้า ยังไม่พบข้อมูลที่ตรงกับคำถามโดยตรงครับ\n\nรบกวนบอกเพิ่มหน่อยว่า:\n- เป็นพืชอะไรคะ (เช่น ข้าว, ทุเรียน, มะม่วง)\n- ปัญหาที่พบ (เช่น โรค, แมลง, วัชพืช)\n\nจะได้ค้นหาตัวที่เหมาะให้ตรงที่สุดนะครับ"

        # =================================================================
        # สร้างรายชื่อสินค้าที่อนุญาตให้แนะนำ (จาก product_docs เท่านั้น)
        # =================================================================
        allowed_products = []
        for doc in product_docs:
            pname = doc.get('product_name', '')
            if pname and pname not in allowed_products:
                allowed_products.append(pname)

        allowed_products_str = ", ".join(allowed_products[:10]) if allowed_products else "(ไม่มี)"

        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"""คุณคือพี่ม้าบิน ผู้เชี่ยวชาญด้านการเกษตรของ ม้าบิน

⛔ กฎเหล็กที่ห้ามละเมิดเด็ดขาด:

1. ห้ามตอบมั่ว ห้ามแต่งข้อมูลเด็ดขาด
   - ถ้าคำถามไหนไม่มีข้อมูลในฐานข้อมูล → ตอบตรงๆ ว่า:
     "ขออภัยครับ ไม่มีข้อมูลเรื่องนี้ในฐานข้อมูลของพี่ม้าบินครับ"
   - ห้ามเดา ห้ามสมมติ ห้ามใช้ความรู้ทั่วไป

2. แนะนำได้เฉพาะสินค้าต่อไปนี้เท่านั้น (ห้ามแต่งชื่ออื่น):
   [{allowed_products_str}]

3. ถ้าถามเรื่องสินค้าที่ไม่อยู่ในรายการด้านบน → ตอบว่า:
   "ขออภัยครับ ไม่พบข้อมูลสินค้านี้ในฐานข้อมูลครับ"

4. ห้ามแต่งข้อมูลต่อไปนี้เด็ดขาด:
   - ห้ามแต่งอัตราการใช้ (ถ้าไม่มีในข้อมูล → บอกว่าไม่มี)
   - ห้ามแต่งวิธีการใช้ (ถ้าไม่มีในข้อมูล → บอกว่าไม่มี)
   - ห้ามแต่งชื่อสารเคมี (ถ้าไม่มีในข้อมูล → บอกว่าไม่มี)
   - ห้ามแต่งชื่อโรค/แมลง (ถ้าไม่มีในข้อมูล → บอกว่าไม่มี)

5. ห้ามใช้ ** หรือ ##
   ใช้ emoji นำหน้าหัวข้อ เช่น 🦠 🌿 💊 📋 ⚖️ 📅 ⚠️ 💡
   ใช้ ━━━━━━━━━━━━━━━ คั่นระหว่างส่วนหลักๆ

6. รูปแบบการตอบ:
   
   - ชื่อสินค้าต้องแสดงในรูปแบบ "ชื่อสินค้า (สารสำคัญ)" เช่น "โมเดิน 50 (โปรฟีโนฟอส)"
   - ถ้าเป็นวัชพืช → จัดกลุ่มตาม: ก่อนวัชพืชงอก, หลังวัชพืชงอก (ทางเลือก 1, 2)
   - ถ้าเป็นแมลง/โรค → ระบุ: อัตราใช้, วิธีใช้, ช่วงใช้
   - ปิดท้ายด้วย: "ถ้าบอกขนาดถังพ่น พี่ม้าบินช่วยคำนวณอัตราให้ได้ครับ"

7. ตอบกระชับ ตรงประเด็น เฉพาะข้อมูลที่มีในฐานข้อมูลเท่านั้น"""},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,
            temperature=0.1  # ลด temperature มากที่สุดเพื่อป้องกันการแต่งข้อมูล
        )

        answer = post_process_answer(response.choices[0].message.content)
        return answer

    except Exception as e:
        logger.error(f"Error in Q&A vector search: {e}", exc_info=True)
        return "ขออภัยครับ เกิดข้อผิดพลาดในการประมวลผล กรุณาลองใหม่อีกครั้งนะครับ"


# =============================================================================
# คำถามเกี่ยวกับวิธีใช้สินค้า / การพ่นยา / การฉีด
# =============================================================================
USAGE_QUESTION_PATTERNS = [
    # วิธีใช้ทั่วไป
    r"วิธี(?:ใช้|พ่น|ฉีด|ผสม)",
    r"ใช้(?:ยัง|ยังไง|อย่างไร|ย่างไร)",
    r"พ่น(?:ยัง|ยังไง|อย่างไร|ย่างไร)",
    r"ฉีด(?:ยัง|ยังไง|อย่างไร|ย่างไร)",
    r"ผสม(?:ยัง|ยังไง|อย่างไร|ย่างไร)",
    # อัตราส่วน
    r"อัตรา(?:การ)?(?:ใช้|ผสม|ส่วน)",
    r"ผสม(?:กี่|เท่าไหร่|เท่าไร)",
    r"ใช้(?:กี่|เท่าไหร่|เท่าไร)",
    # ช่วงเวลา
    r"(?:พ่น|ฉีด|ใช้)(?:ตอน|เมื่อ|ช่วง)",
    r"(?:ตอน|เมื่อ|ช่วง)(?:ไหน|ใด).*(?:พ่น|ฉีด|ใช้)",
    # คำถามเฉพาะ
    r"(?:แนะนำ)?(?:วิธี|ขั้นตอน).*(?:พ่น|ฉีด|ใช้|รักษา)",
    r"(?:พ่น|ฉีด).*(?:กี่|บ่อย|ถี่)",
    r"(?:ละลาย|เจือจาง).*(?:น้ำ|ยัง)",
    # ถามต่อจากสินค้าที่แนะนำ
    r"(?:ตัว)?(?:นี้|นั้น|แรก|ที่\d).*(?:ใช้|พ่น|ฉีด)",
    r"(?:ใช้|พ่น|ฉีด).*(?:ตัว)?(?:นี้|นั้น|แรก|ที่\d)",
    # บรรจุภัณฑ์/ขนาด/ราคา (follow-up questions)
    r"(?:บรรจุ|ขนาด|ราคา).*(?:เท่าไหร่|เท่าไร|กี่|ไหน)",
    r"(?:บรรจุภัณฑ์|บรรภัณ|ขนาดบรรจุ)",
    r"มี(?:กี่)?ขนาด",
    r"(?:กี่|เท่าไหร่|เท่าไร).*(?:บาท|ลิตร|มล\.|ซีซี|กรัม|กก\.)",
    # ถามพื้นที่การใช้งาน
    r"\d+\s*ไร่.*(?:ใช้|เท่าไหร่|เท่าไร)",
    r"(?:ใช้|พ่น).*\d+\s*ไร่",
]


def is_usage_question(message: str) -> bool:
    """ตรวจสอบว่าเป็นคำถามเกี่ยวกับวิธีใช้สินค้าหรือไม่"""
    message_lower = message.lower()
    for pattern in USAGE_QUESTION_PATTERNS:
        if re.search(pattern, message_lower):
            return True
    return False


async def _fetch_product_from_db(product_name: str) -> list:
    """ดึงข้อมูลปุ๋ยจาก mahbin_npk ตรงๆ สำหรับ enrich memory data"""
    try:
        from app.dependencies import supabase_client as _sb
        if not _sb:
            return []
        # Search by crop name or fertilizer formula
        result = _sb.table('mahbin_npk').select(
            'id, crop, growth_stage, fertilizer_formula, usage_rate, '
            'primary_nutrients, benefits'
        ).or_(
            f"crop.ilike.%{product_name}%,fertilizer_formula.ilike.%{product_name}%"
        ).limit(5).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"_fetch_product_from_db error: {e}")
        return []


async def answer_usage_question(user_id: str, message: str, context: str = "") -> str:
    """
    ตอบคำถามเกี่ยวกับวิธีใช้สินค้าจากข้อมูลที่เก็บใน memory

    Flow ที่ถูกต้อง:
    1. ถ้าถามแบบสั้น (เช่น "อัตราการใช้") โดยไม่ระบุสินค้า/พืช → ถามกลับ
    2. ถ้ามีสินค้าใน memory และระบุพืช → ตอบจาก memory
    3. ถ้าไม่มี memory → ไป flow ปกติ
    """
    try:
        # ตรวจสอบว่าคำถามระบุสินค้าหรือพืชหรือไม่
        product_in_question = extract_product_name_from_question(message)
        plant_in_question = extract_plant_type_from_question(message)

        # ถ้าถามแบบสั้นๆ (เช่น "อัตราการใช้", "วิธีใช้") โดยไม่ระบุสินค้า → ต้องถามกลับ
        short_questions = ['อัตราการใช้', 'วิธีใช้', 'อัตราผสม', 'ผสมยังไง', 'ใช้ยังไง']
        is_short_question = message.strip() in short_questions or len(message.strip()) < 15

        if is_short_question and not product_in_question and not plant_in_question:
            logger.info(f"⚠️ คำถามสั้นไม่ระบุรายละเอียด: {message}")
            return "ขอทราบรายละเอียดเพิ่มเติมครับ:\n- ต้องการทราบอัตราการใช้ของสินค้าตัวไหนครับ?\n- และใช้กับพืชอะไรครับ?\n\nเพื่อให้พี่ม้าบินแนะนำอัตราการใช้ที่ถูกต้องครับ"

        # ดึงข้อมูลสินค้าที่แนะนำล่าสุด
        products = await get_recommended_products(user_id, limit=5)

        if not products:
            # ถ้าไม่มี memory แต่ระบุชื่อสินค้า → ดึงจาก DB ตรงๆ
            if product_in_question:
                products = await _fetch_product_from_db(product_in_question)
            if not products:
                return None  # ไม่มีสินค้าใน memory → ให้ไปใช้ flow ปกติ

        # Enrich ข้อมูลจาก DB (กรณี memory เก่าไม่มี fields เช่น package_size)
        _ENRICH_KEYS = ['package_size', 'absorption_method', 'mechanism_of_action',
                        'how_to_use', 'usage_rate', 'usage_period', 'target_pest',
                        'active_ingredient', 'applicable_crops', 'phytotoxicity']
        if product_in_question:
            db_product = await _fetch_product_from_db(product_in_question)
            if db_product:
                # Merge DB data into memory products
                merged = False
                for p in products:
                    if product_in_question.lower() in p.get('product_name', '').lower():
                        db_p = db_product[0]
                        for key in _ENRICH_KEYS:
                            if db_p.get(key) and not p.get(key):
                                p[key] = db_p[key]
                        merged = True
                        break
                # ถ้าสินค้าที่ถามไม่อยู่ใน memory → เพิ่ม DB product เข้าไปเป็นตัวแรก
                if not merged:
                    logger.info(f"📦 Product '{product_in_question}' not in memory, adding from DB")
                    products.insert(0, db_product[0])
        else:
            # ไม่มีชื่อสินค้าในคำถาม (เช่น "กี่กระสอบ", "1ขวดฉีดได้กี่ไร่")
            # → enrich ทุกตัวใน memory ที่ยังขาด field สำคัญ
            for p in products:
                pname = p.get('product_name', '')
                if not pname:
                    continue
                # ถ้ามี field สำคัญครบแล้ว → ข้าม
                if p.get('package_size') and p.get('how_to_use') and p.get('usage_rate'):
                    continue
                try:
                    db_rows = await _fetch_product_from_db(pname)
                    if db_rows:
                        db_p = db_rows[0]
                        for key in _ENRICH_KEYS:
                            if db_p.get(key) and not p.get(key):
                                p[key] = db_p[key]
                        logger.info(f"📦 Enriched '{pname}' from DB (follow-up without product name)")
                except Exception as e:
                    logger.warning(f"Failed to enrich '{pname}': {e}")

        # สร้าง prompt สำหรับ AI
        products_text = ""
        for idx, p in enumerate(products, 1):
            products_text += f"\n[{idx}] {p.get('product_name', 'N/A')}"
            if p.get('how_to_use'):
                products_text += f"\n   • วิธีใช้: {p.get('how_to_use')}"
            if p.get('usage_rate'):
                products_text += f"\n   • อัตราใช้: {p.get('usage_rate')}"
            if p.get('usage_period'):
                products_text += f"\n   • ช่วงการใช้: {p.get('usage_period')}"
            if p.get('target_pest'):
                products_text += f"\n   • ศัตรูพืชที่กำจัด: {p.get('target_pest')[:100]}"
            if p.get('applicable_crops'):
                products_text += f"\n   • ใช้กับพืช: {p.get('applicable_crops')[:100]}"
            if p.get('package_size'):
                products_text += f"\n   • ขนาดบรรจุ: {p.get('package_size')}"
            if p.get('absorption_method'):
                products_text += f"\n   • การดูดซึม: {p.get('absorption_method')}"
            if p.get('mechanism_of_action'):
                products_text += f"\n   • กลไกการออกฤทธิ์: {p.get('mechanism_of_action')}"
            if p.get('phytotoxicity'):
                products_text += f"\n   • ความเป็นพิษต่อพืช: {p.get('phytotoxicity')}"
            products_text += "\n"

        prompt = f"""คุณคือ "พี่ม้าบิน" ผู้เชี่ยวชาญด้านการใช้ยาฆ่าศัตรูพืชจาก ม้าบิน

สินค้าที่เพิ่งแนะนำให้ผู้ใช้:
{products_text}

บทสนทนาก่อนหน้า:
{context if context else "(ไม่มี)"}

คำถามจากผู้ใช้: {message}

กฎการตอบ (สำคัญมาก — ต้องทำตามเคร่งครัด):
- ห้ามใช้ emoji ทุกตัว ยกเว้น 😊 กับ 🌱 เท่านั้น ใช้ไม่เกิน 1-2 ตัวทั้งข้อความ
- ห้ามใช้ emoji เป็นหัวข้อ/bullet point/icon เด็ดขาด
- ห้ามใช้เส้นขีด/divider เช่น ────, ━━━━, ═══, ---
- ห้ามใช้ ** หรือ ## หรือ markdown อื่นๆ
- ใช้ bullet point แบบ "•" หรือเลข "1. 2. 3." เท่านั้น
- ห้ามจัดรูปแบบเป็น section/หมวดหมู่ที่มี header แยก
- หน่วย: ใช้ "มล." แทน "cc/ซีซี" เสมอ; กรัม = "กรัม"
- ตอบกระชับ ตรงประเด็น ไม่เกิน 8-10 บรรทัด

[ห้ามมั่วข้อมูล — กฎเด็ดขาด]
- ข้อมูลสินค้าด้านบนคือข้อมูลทั้งหมดที่มีในระบบ ให้ตอบตามข้อมูลที่ให้มา
- ถ้าถามขนาดบรรจุ/จำนวนขนาด → ตอบตามข้อมูล "ขนาดบรรจุ" ที่แสดงด้านบน (ถ้ามี 1 ขนาด ให้ตอบว่ามี 1 ขนาด)
- ห้ามแต่งข้อมูลขนาดบรรจุ น้ำหนัก ราคา กลไกการออกฤทธิ์ หรือการดูดซึมเอง
- ถ้าข้อมูลที่ถามไม่ปรากฏเลยในรายการด้านบน (ไม่มี field นั้นๆ) ให้ตอบว่า "ขออภัยครับ ไม่มีข้อมูลส่วนนี้ในระบบ"
- ห้ามเดา ห้ามใช้ความรู้ทั่วไป ใช้เฉพาะข้อมูลที่ให้มาเท่านั้น

[คำนวณอัตราผสม] (ถ้าผู้ใช้บอกขนาดถังหรือพื้นที่)
- ดูอัตราใช้จากข้อมูลสินค้าด้านบน
- คำนวณตามสัดส่วน แสดงวิธีคิดสั้นๆ
- ตัวอย่าง: อัตรา 30 มล./น้ำ 20 ลิตร + ถัง 50 ลิตร → 30 x (50/20) = 75 มล.
- ตัวอย่าง: อัตรา 50 มล./ไร่ + 10 ไร่ → 50 x 10 = 500 มล.
- ถ้าข้อมูลเป็น "กรัม" ใช้หน่วย "กรัม"

ปิดท้ายด้วย: "สามารถสอบถามพี่ม้าบินได้เลยนะครับ 🌱"

ตอบ:"""

        if not openai_client:
            # Fallback: แสดงข้อมูลดิบ
            response = "[วิธีใช้ผลิตภัณฑ์ที่แนะนำ]\n"
            for idx, p in enumerate(products[:3], 1):
                response += f"\n{idx}. {p.get('product_name', 'N/A')}"
                if p.get('how_to_use'):
                    response += f"\n   - วิธีใช้: {p.get('how_to_use')}"
                if p.get('usage_rate'):
                    response += f"\n   - อัตราใช้: {p.get('usage_rate')}"
            response += "\n\n[ข้อควรระวัง]\nอ่านฉลากก่อนใช้ทุกครั้งนะครับ"
            return response

        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """คุณคือ "พี่ม้าบิน" ผู้เชี่ยวชาญด้านการใช้ยาฆ่าศัตรูพืชจาก ม้าบิน

กฎการตอบ:
- ห้ามใช้ emoji ทุกตัว ยกเว้น 😊 กับ 🌱 เท่านั้น
- ห้ามใช้ emoji เป็นหัวข้อ/bullet point/icon
- ห้ามใช้เส้นขีด/divider เช่น ────, ━━━━
- ห้ามใช้ ** หรือ ## หรือ markdown
- ใช้ bullet point แบบ • หรือเลข 1. 2. 3.
- หน่วย: ใช้ "มล." แทน "cc/ซีซี"
- ตอบกระชับ ไม่เกิน 8-10 บรรทัด
- ห้ามมั่วข้อมูลเด็ดขาด ตอบเฉพาะข้อมูลที่ให้มา ถ้าไม่มีข้อมูลให้ตอบ "ไม่มีข้อมูลในระบบ"
- ห้ามแต่งตัวเลขขนาดบรรจุ น้ำหนัก ราคา กลไกการออกฤทธิ์เอง"""},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,
            temperature=0.3
        )

        answer = response.choices[0].message.content.strip()
        answer = answer.replace("**", "").replace("##", "").replace("```", "")
        # ลบ emoji ที่ไม่อนุญาต และ dividers
        import re
        answer = re.sub(r'[━─═\-]{3,}', '', answer)  # ลบ dividers
        answer = re.sub(r'[💊📋⚖️📅⚠️💡🔢🧪⏰🌿]', '', answer)  # ลบ emoji ที่ห้าม

        logger.info(f"✓ Answered usage question from memory products")
        return answer

    except Exception as e:
        logger.error(f"Error answering usage question: {e}", exc_info=True)
        return None

async def handle_natural_conversation(user_id: str, message: str) -> str:
    """Handle natural conversation with context and intent detection"""
    try:
        # 1. Add user message to memory
        await add_to_memory(user_id, "user", message)

        # 2. Get enhanced conversation context (includes summary + products)
        context = await get_enhanced_context(user_id, current_query=message)

        # 3. Check if this is a usage/application question (วิธีใช้/พ่น/ฉีด)
        #    For short ambiguous messages, only route if conversation context involves products
        _is_usage = is_usage_question(message)
        if _is_usage and len(message.strip()) < 20 and not extract_product_name_from_question(message):
            # Short follow-up without product name — check if context has product history
            has_product_context = "สินค้าที่แนะนำ" in context or extract_product_name_from_question(context[-500:] if context else "") is not None
            if not has_product_context:
                _is_usage = False
                logger.info(f"Short follow-up '{message[:30]}' has no product context, skip usage flow")

        if _is_usage:
            logger.info(f"🔧 Detected usage question: {message[:50]}...")
            usage_answer = await answer_usage_question(user_id, message, context)
            if usage_answer:
                # Add assistant response to memory
                await add_to_memory(user_id, "assistant", usage_answer)
                return usage_answer
            # ถ้าไม่มีสินค้าใน memory → ให้ไปใช้ flow ปกติ
            logger.info("No products in memory, falling back to normal flow")

        # 4. Analyze intent and keywords
        keywords = extract_keywords_from_question(message)

        # 4b. Dealer lookup — ถามหาร้านค้า/ตัวแทนจำหน่าย (L1: keyword fast path)
        _is_dealer_q = is_dealer_question(message)

        if _is_dealer_q:
            province, district, subdistrict = await extract_location_llm(message)
            has_explicit_prov = message_has_explicit_province(message)

            # ถ้า user ไม่ได้ระบุจังหวัดชัดเจน → ถามจังหวัดเสมอ
            # (ไม่ trust LLM เดาจังหวัด เพราะชื่อ อ./ต. ซ้ำข้ามจังหวัดได้)
            if not has_explicit_prov:
                if district or subdistrict:
                    # ใช้ static extraction ดึงเฉพาะ district ที่อยู่ใน known data
                    # (LLM อาจ infer district จากจังหวัดผิด เช่น บางกุ้ง → เมืองสมุทรสงคราม)
                    _, s_dist, _ = extract_location(message)
                    save_dist = s_dist  # static district (known data)
                    save_sub = subdistrict  # LLM subdistrict (usually what user said)
                    # ถ้า district == subdistrict → เก็บเป็น subdistrict อย่างเดียว
                    if save_dist and save_sub and save_dist == save_sub:
                        save_dist = None

                    loc_parts = []
                    if save_sub:
                        loc_parts.append(f"ต.{save_sub}")
                    if save_dist:
                        loc_parts.append(f"อ.{save_dist}")
                    if loc_parts:
                        loc_text = " ".join(loc_parts)
                        ask_msg = f"{loc_text} อยู่จังหวัดไหนครับ? บอกชื่อจังหวัดมาได้เลยนะครับ 😊"
                    else:
                        ask_msg = "อยู่จังหวัดไหนครับ? บอกชื่อจังหวัดมาได้เลยนะครับ 😊"
                    ctx_data = {"state": "awaiting_dealer_province"}
                    if save_dist:
                        ctx_data["district"] = save_dist
                    if save_sub:
                        ctx_data["subdistrict"] = save_sub
                    await save_pending_context(user_id, ctx_data)
                    await add_to_memory(user_id, "assistant", ask_msg)
                    return ask_msg
                else:
                    province = None  # ไม่มีอะไรเลย → fallback context

            if not province:
                # ลองดึงจากบทสนทนาก่อนหน้า
                province, district, subdistrict = extract_province_from_context(context)
            if province:
                dealers, fallback_prov, missed_location = await search_dealers_with_fallback(province, district, subdistrict)
                if dealers and not fallback_prov and not missed_location:
                    answer = format_dealer_response(dealers, province)
                elif dealers and missed_location and not fallback_prov:
                    answer = f"ขออภัยครับ ยังไม่พบตัวแทนจำหน่ายใน {missed_location} โดยตรง\n"
                    answer += f"แต่พบตัวแทนในจังหวัด{province} ครับ\n\n"
                    answer += format_dealer_response(dealers, province)
                elif dealers and fallback_prov:
                    answer = f"ขออภัยครับ ยังไม่พบตัวแทนจำหน่ายใน จ.{province} โดยตรง\n"
                    answer += f"แต่มีตัวแทนในจังหวัดใกล้เคียง ({fallback_prov}) ครับ\n\n"
                    answer += format_dealer_response(dealers, fallback_prov)
                else:
                    answer = f"ขออภัยครับ ยังไม่พบตัวแทนจำหน่ายใน{province} ลองติดต่อสอบถามที่เพจม้าบินได้เลยนะครับ 😊"
                await add_to_memory(user_id, "assistant", answer)
                return answer
            else:
                ask_msg = "พี่ม้าบินช่วยหาตัวแทนจำหน่ายให้ได้เลยครับ\nรบกวนบอกจังหวัดหรืออำเภอหน่อยนะครับ? 😊"
                await save_pending_context(user_id, {"state": "awaiting_dealer_province"})
                await add_to_memory(user_id, "assistant", ask_msg)
                return ask_msg

        # 5. Route based on intent

        # 5a. Greeting fast path — no LLM needed
        # Guard: short keywords (ดี, hi ≤2 chars) require very short message (≤8 chars)
        # to avoid false-positive on messages like "ใช้ตัวไหนดี"
        msg_stripped = message.strip().lower()
        _is_greeting = False
        if len(msg_stripped) < 30:
            for _gkw in GREETING_KEYWORDS:
                if _gkw in msg_stripped:
                    if len(_gkw) <= 2 and len(msg_stripped) > 8:
                        continue
                    _is_greeting = True
                    break
        if _is_greeting:
            import random
            greeting_answer = random.choice(GREETINGS)
            logger.info(f"Greeting detected: '{message[:30]}' → instant reply")
            await add_to_memory(user_id, "assistant", greeting_answer)
            return greeting_answer

        # 5b. Classify intent
        is_agri_q = is_agriculture_question(message) or keywords["pests"] or keywords["crops"]
        is_prod_q = is_product_question(message) or keywords["is_product_query"]
        is_fert_q = keywords.get("is_fertilizer_query", False)
        has_product_name = extract_product_name_from_question(message) is not None

        # 5c. RAG-first routing: default to RAG, only skip for clearly non-agriculture
        explicit_match = is_agri_q or is_prod_q or is_fert_q or has_product_name
        is_non_agri = _is_clearly_non_agriculture(message)
        route_to_rag = explicit_match or not is_non_agri

        if route_to_rag:
            logger.info(f"🔍 Routing to RAG ({'explicit' if explicit_match else 'default'}: agri={is_agri_q}, product={is_prod_q}, fertilizer={is_fert_q}, product_name={has_product_name})")

            # Use AgenticRAG if enabled
            if USE_AGENTIC_RAG:
                agentic_rag = await _get_agentic_rag()
                if agentic_rag:
                    logger.info("Using AgenticRAG pipeline")
                    rag_response = await agentic_rag.process(message, context, user_id)

                    # Check if AgenticRAG wants to fallback to general chat
                    if rag_response.answer is None:
                        # DEALER_INQUIRY → route to dealer lookup
                        if rag_response.intent == IntentType.DEALER_INQUIRY:
                            logger.info("AgenticRAG detected DEALER_INQUIRY, routing to dealer lookup")
                            province, district, subdistrict = await extract_location_llm(message)
                            has_explicit_prov = message_has_explicit_province(message)

                            # ถ้า user ไม่ได้ระบุจังหวัดชัดเจน → ถามจังหวัดเสมอ
                            if not has_explicit_prov:
                                if district or subdistrict:
                                    _, s_dist, _ = extract_location(message)
                                    save_dist = s_dist
                                    save_sub = subdistrict
                                    if save_dist and save_sub and save_dist == save_sub:
                                        save_dist = None

                                    loc_parts = []
                                    if save_sub:
                                        loc_parts.append(f"ต.{save_sub}")
                                    if save_dist:
                                        loc_parts.append(f"อ.{save_dist}")
                                    if loc_parts:
                                        loc_text = " ".join(loc_parts)
                                        ask_msg = f"{loc_text} อยู่จังหวัดไหนครับ? บอกชื่อจังหวัดมาได้เลยนะครับ 😊"
                                    else:
                                        ask_msg = "อยู่จังหวัดไหนครับ? บอกชื่อจังหวัดมาได้เลยนะครับ 😊"
                                    ctx_data = {"state": "awaiting_dealer_province"}
                                    if save_dist:
                                        ctx_data["district"] = save_dist
                                    if save_sub:
                                        ctx_data["subdistrict"] = save_sub
                                    await save_pending_context(user_id, ctx_data)
                                    await add_to_memory(user_id, "assistant", ask_msg)
                                    return ask_msg
                                else:
                                    province = None

                            if not province:
                                province, district, subdistrict = extract_province_from_context(context)
                            if province:
                                dealers, fallback_prov, missed_location = await search_dealers_with_fallback(province, district, subdistrict)
                                if dealers and not fallback_prov and not missed_location:
                                    answer = format_dealer_response(dealers, province)
                                elif dealers and missed_location and not fallback_prov:
                                    answer = f"ขออภัยครับ ยังไม่พบตัวแทนจำหน่ายใน {missed_location} โดยตรง\n"
                                    answer += f"แต่พบตัวแทนในจังหวัด{province} ครับ\n\n"
                                    answer += format_dealer_response(dealers, province)
                                elif dealers and fallback_prov:
                                    answer = f"ขออภัยครับ ยังไม่พบตัวแทนจำหน่ายใน จ.{province} โดยตรง\n"
                                    answer += f"แต่มีตัวแทนในจังหวัดใกล้เคียง ({fallback_prov}) ครับ\n\n"
                                    answer += format_dealer_response(dealers, fallback_prov)
                                else:
                                    answer = f"ขออภัยครับ ยังไม่พบตัวแทนจำหน่ายใน{province} ลองติดต่อสอบถามที่เพจม้าบินได้เลยนะครับ 😊"
                                await add_to_memory(user_id, "assistant", answer)
                                return answer
                            else:
                                ask_msg = "พี่ม้าบินช่วยหาตัวแทนจำหน่ายให้ได้เลยครับ\nรบกวนบอกจังหวัดหรืออำเภอหน่อยนะครับ? 😊"
                                await save_pending_context(user_id, {"state": "awaiting_dealer_province"})
                                await add_to_memory(user_id, "assistant", ask_msg)
                                return ask_msg

                        logger.info("AgenticRAG returned None, falling back to general chat")
                        # Fall through to general chat below
                    else:
                        answer = rag_response.answer
                        logger.info(f"AgenticRAG response: confidence={rag_response.confidence:.2f}, grounded={rag_response.is_grounded}")

                        # Track analytics if product recommendation
                        if is_prod_q:
                            from app.dependencies import analytics_tracker
                            if analytics_tracker:
                                product_pattern = r'\d+\.\s+([^\n]+?)(?:\n|$)'
                                product_matches = re.findall(product_pattern, answer)
                                product_names = []
                                for match in product_matches:
                                    clean_name = match.split('\n')[0].strip()
                                    clean_name = clean_name.replace('ชื่อผลิตภัณฑ์:', '').strip()
                                    if clean_name and len(clean_name) > 3:
                                        product_names.append(clean_name)
                                if product_names:
                                    await analytics_tracker.track_product_recommendation(
                                        user_id=user_id,
                                        disease_name="AgenticRAG",
                                        products=product_names[:5]
                                    )
                                    logger.info(f"Tracked {len(product_names)} products from AgenticRAG")

                        # Add assistant response to memory WITH product metadata
                        rag_metadata = {}
                        mentioned_products = [
                            p for p in ICP_PRODUCT_NAMES.keys() if p in answer
                        ]
                        if mentioned_products:
                            rag_metadata["type"] = "product_recommendation"
                            # Enrich from DB so follow-up questions have full data (package_size etc.)
                            enriched_products = []
                            for mp in mentioned_products[:5]:
                                try:
                                    db_rows = await _fetch_product_from_db(mp)
                                    if db_rows:
                                        enriched_products.append(db_rows[0])
                                    else:
                                        enriched_products.append({"product_name": mp})
                                except Exception:
                                    enriched_products.append({"product_name": mp})
                            rag_metadata["products"] = enriched_products
                        await add_to_memory(user_id, "assistant", answer, metadata=rag_metadata)
                        if is_prod_q or is_fert_q:
                            if "หากต้องการหาตัวแทน" not in context:
                                answer += DEALER_SUGGESTION_SUFFIX
                        return answer

            # Fallback to legacy answer_qa_with_vector_search
            logger.info("Using legacy answer_qa_with_vector_search")
            answer = await answer_qa_with_vector_search(message, context)

            # Track analytics if product recommendation
            if is_prod_q:
                from app.dependencies import analytics_tracker
                if analytics_tracker:
                    product_pattern = r'\d+\.\s+([^\n]+?)(?:\n|$)'
                    product_matches = re.findall(product_pattern, answer)
                    product_names = []
                    for match in product_matches:
                        clean_name = match.split('\n')[0].strip()
                        clean_name = clean_name.replace('ชื่อผลิตภัณฑ์:', '').strip()
                        if clean_name and len(clean_name) > 3:
                            product_names.append(clean_name)
                    if product_names:
                        await analytics_tracker.track_product_recommendation(
                            user_id=user_id,
                            disease_name="Q&A",
                            products=product_names[:5]
                        )
                        logger.info(f"Tracked {len(product_names)} products from Q&A")

            # Add assistant response to memory
            await add_to_memory(user_id, "assistant", answer)
            if is_prod_q or is_fert_q:
                if "หากต้องการหาตัวแทน" not in context:
                    answer += DEALER_SUGGESTION_SUFFIX
            return answer

        else:
            # Clearly non-agriculture → safe general chat (neutered, no product/disease expertise)
            logger.info(f"💬 Routing to general chat (non-agri: '{message[:30]}')")

            if not openai_client:
                logger.error("OpenAI client not available for general chat")
                return ERROR_AI_UNAVAILABLE

            try:
                response = await openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": GENERAL_CHAT_PROMPT},
                        {"role": "user", "content": message}
                    ],
                    max_tokens=150,
                    temperature=0.3
                )
                answer = post_process_answer(response.choices[0].message.content)
            except Exception as llm_err:
                logger.error(f"General chat LLM call failed: {llm_err}", exc_info=True)
                return ERROR_GENERIC

            # Add assistant response to memory
            await add_to_memory(user_id, "assistant", answer)
            return answer

    except Exception as e:
        logger.error(f"Error in natural conversation: {e}", exc_info=True)
        return ERROR_GENERIC
