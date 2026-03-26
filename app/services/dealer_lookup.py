"""
Dealer lookup service — ค้นหาตัวแทนจำหน่ายม้าบินจาก Supabase.

Flow:
1. is_dealer_question(msg) → ตรวจว่าผู้ใช้ถามหาร้านค้าหรือไม่
2. extract_location(msg) → ดึงจังหวัด/อำเภอจากข้อความ (3 ชั้น + alias)
3. search_dealers(province, district) → ค้นหาจาก Supabase
4. format_dealer_response(dealers, province) → จัดรูปข้อความตอบกลับ
"""
import json
import logging
import re
from app.dependencies import openai_client, supabase_client
from app.config import LLM_MODEL_DEALER_EXTRACTION
from app.utils.text_processing import strip_thai_diacritics

logger = logging.getLogger(__name__)

# ============================================================================
# Keyword Detection
# ============================================================================

DEALER_KEYWORDS = [
    "ตัวแทนจำหน่าย", "ตัวแทน", "ร้านขาย", "ซื้อที่ไหน", "ซื้อได้ที่ไหน",
    "หาซื้อ", "ติดต่อซื้อ", "ร้านค้า", "dealer", "ใกล้บ้าน", "ใกล้ฉัน",
    "จุดขาย", "สาขา", "ร้านใกล้", "ขายที่ไหน", "ซื้อปุ๋ยม้าบิน",
    "ร้านม้าบิน", "หาร้าน", "ร้านเกษตร",
]


def is_dealer_question(message: str) -> bool:
    """ตรวจว่าข้อความเป็นคำถามหาตัวแทนจำหน่ายหรือไม่"""
    msg = message.lower().strip()
    for kw in DEALER_KEYWORDS:
        if kw in msg:
            return True
    return False


# ============================================================================
# Province / District Data (from CSV — 65 provinces, 276 districts)
# ============================================================================

KNOWN_PROVINCES = [
    "กระบี่", "กาญจนบุรี", "กาฬสินธุ์", "กำแพงเพชร", "ขอนแก่น",
    "จันทบุรี", "ฉะเชิงเทรา", "ชลบุรี", "ชัยนาท", "ชัยภูมิ",
    "ชุมพร", "ตรัง", "ตราด", "ตาก", "นครปฐม",
    "นครราชสีมา", "นครศรีธรรมราช", "นครสวรรค์", "นนทบุรี", "น่าน",
    "บึงกาฬ", "บุรีรัมย์", "ปทุมธานี", "ประจวบคีรีขันธ์", "ปราจีนบุรี",
    "พระนครศรีอยุธยา", "พะเยา", "พังงา", "พัทลุง", "พิจิตร",
    "พิษณุโลก", "มุกดาหาร", "ยโสธร", "ระนอง", "ระยอง",
    "ราชบุรี", "ร้อยเอ็ด", "ลพบุรี", "ลำปาง", "ลำพูน",
    "ศรีสะเกษ", "สกลนคร", "สงขลา", "สตูล", "สระบุรี",
    "สระแก้ว", "สิงห์บุรี", "สุพรรณบุรี", "สุราษฎร์ธานี", "สุรินทร์",
    "สุโขทัย", "หนองคาย", "หนองบัวลำภู", "อำนาจเจริญ", "อุดรธานี",
    "อุตรดิตถ์", "อุทัยธานี", "อุบลราชธานี", "อ่างทอง", "เชียงราย",
    "เชียงใหม่", "เพชรบุรี", "เพชรบูรณ์", "เลย", "แพร่",
]

# 12 จังหวัดที่ไม่มี dealer → จังหวัดใกล้เคียงที่มี dealer
PROVINCES_NO_DEALER = {
    "กรุงเทพมหานคร": ["ปทุมธานี", "นนทบุรี"],
    "นครนายก": ["ปราจีนบุรี", "สระบุรี"],
    "นครพนม": ["สกลนคร", "มุกดาหาร"],
    "ปัตตานี": ["สงขลา"],
    "ภูเก็ต": ["พังงา", "สุราษฎร์ธานี"],
    "มหาสารคาม": ["ขอนแก่น", "ร้อยเอ็ด"],
    "แม่ฮ่องสอน": ["เชียงใหม่"],
    "ยะลา": ["สงขลา"],
    "สมุทรปราการ": ["ชลบุรี", "ฉะเชิงเทรา"],
    "สมุทรสงคราม": ["ราชบุรี", "เพชรบุรี"],
    "สมุทรสาคร": ["นครปฐม", "ราชบุรี"],
    "นราธิวาส": ["สงขลา"],
}
ALL_THAI_PROVINCES = KNOWN_PROVINCES + list(PROVINCES_NO_DEALER.keys())

# ชื่อเล่น / ชื่อย่อจังหวัด → ชื่อเต็ม
PROVINCE_ALIASES = {
    "โคราช": "นครราชสีมา",
    "สุราษ": "สุราษฎร์ธานี",
    "สุราษฎร์": "สุราษฎร์ธานี",
    "อุบล": "อุบลราชธานี",
    "อุดร": "อุดรธานี",
    "นครศรี": "นครศรีธรรมราช",
    "แปดริ้ว": "ฉะเชิงเทรา",
    "ฉะเชิง": "ฉะเชิงเทรา",
    "อยุธยา": "พระนครศรีอยุธยา",
    "กรุงเก่า": "พระนครศรีอยุธยา",
    "ประจวบ": "ประจวบคีรีขันธ์",
    "หนองบัว": "หนองบัวลำภู",
    "ปากน้ำโพ": "นครสวรรค์",
    "กาญจน์": "กาญจนบุรี",
    "พิษณุ": "พิษณุโลก",
    "อำนาจ": "อำนาจเจริญ",
    "ปราจีน": "ปราจีนบุรี",
    "สุพรรณ": "สุพรรณบุรี",
    "จันท์": "จันทบุรี",
    "หาดใหญ่": "สงขลา",
    "สาเกตุ": "ร้อยเอ็ด",
    "กาฬสิน": "กาฬสินธุ์",
    "กรุงเทพ": "กรุงเทพมหานคร",
    "กทม": "กรุงเทพมหานคร",
    "สมุทรปราการ": "สมุทรปราการ",
    "นครนายก": "นครนายก",
}


def _build_province_prefixes() -> dict:
    """Build {prefix: province} for safe prefix-substring matching.

    Generates unique prefixes (min 4 chars) of each province name.
    Short provinces (<=4 chars like ตาก, เลย) are skipped to avoid false positives.
    Only keeps prefixes that map to exactly one province.
    """
    prefix_map: dict[str, list[str]] = {}
    for prov in ALL_THAI_PROVINCES:
        if len(prov) <= 4:
            continue
        for end in range(4, len(prov)):
            prefix = prov[:end]
            prefix_map.setdefault(prefix, []).append(prov)
    return {p: provs[0] for p, provs in prefix_map.items() if len(provs) == 1}


PROVINCE_PREFIXES = _build_province_prefixes()

DISTRICT_TO_PROVINCE = {
    "กบินทร์บุรี": "ปราจีนบุรี", "กมลาไสย": "กาฬสินธุ์", "กระจาย": "ยโสธร",
    "กระบุรี": "ระนอง", "กลางเวียง": "น่าน", "กันจุ": "เพชรบูรณ์",
    "กันตัง": "ตรัง", "กาญจนดิษฐ์": "สุราษฎร์ธานี", "กำแพงแสน": "นครปฐม",
    "กุมภวาปี": "อุดรธานี", "กุยบุรี": "ประจวบคีรีขันธ์", "กุศกร": "อุบลราชธานี",
    "ขันเงิน": "ชุมพร", "ขาณุวรลักษบุรี": "กำแพงเพชร", "ขามสะแกแสง": "นครราชสีมา",
    "ขุขันธ์": "ศรีสะเกษ", "คลองขลุง": "กำแพงเพชร", "คลองท่อม": "กระบี่",
    "คลองลาน": "กำแพงเพชร", "ควนกรด": "นครศรีธรรมราช", "คำพราน": "สระบุรี",
    "คำใหญ่": "กาฬสินธุ์", "คีรีมาศ": "สุโขทัย", "คีรีรัฐนิคม": "สุราษฎร์ธานี",
    "งาว": "ลำปาง", "งิ้วด่อน": "สกลนคร", "จอมประทัด": "ราชบุรี",
    "ชะอวด": "นครศรีธรรมราช", "ชัยบุรี": "สุราษฎร์ธานี", "ชุมพล": "พัทลุง",
    "ชุมแพ": "ขอนแก่น", "ชุมแสง": "นครสวรรค์", "ซับสนุ่น": "สระบุรี",
    "ดงเจริญ": "พิจิตร", "ดอนยาง": "ชุมพร", "ดอนเจดีย์": "สุพรรณบุรี",
    "ด่านขุนทด": "นครราชสีมา", "ด่านช้าง": "สุพรรณบุรี", "ตลาด": "สุราษฎร์ธานี",
    "ตลาดน้อย": "สระบุรี", "ตะพานหิน": "พิจิตร", "ตะเครียะ": "สงขลา",
    "ตากฟ้า": "นครสวรรค์", "ตาคลี": "นครสวรรค์", "ทรายทองวัฒนา": "กำแพงเพชร",
    "ทองมงคล": "ประจวบคีรีขันธ์", "ทับคล้อ": "พิจิตร", "ทับสะแก": "ประจวบคีรีขันธ์",
    "ทุ่งกระตาดพัฒนา": "บุรีรัมย์", "ทุ่งหว้า": "สตูล", "ทุ่งฮั้ว": "ลำปาง",
    "ทุ่งเสลี่ยม": "สุโขทัย", "ท่าขนุน": "กาญจนบุรี", "ท่าข้าม": "เพชรบูรณ์",
    "ท่าชนะ": "สุราษฎร์ธานี", "ท่าตะเกียบ": "ฉะเชิงเทรา", "ท่าตะโก": "นครสวรรค์",
    "ท่าตูม": "สุรินทร์", "ท่ามะกา": "กาญจนบุรี", "ท่าม่วง": "กาญจนบุรี",
    "ท่าวังทอง": "พะเยา", "ท่าสองยาง": "ตาก", "ท่าอิฐ": "อุตรดิตถ์",
    "ท่าเรือ": "กาญจนบุรี", "ท่าแซะ": "ชุมพร", "ท้องลำเจียก": "นครศรีธรรมราช",
    "ธาตุ": "เลย", "ธารเกษม": "สระบุรี", "นครชัยศรี": "นครปฐม",
    "นครชุม": "กำแพงเพชร", "นครไทย": "พิษณุโลก", "นากลาง": "หนองบัวลำภู",
    "นาซำ": "เพชรบูรณ์", "นาด้วง": "เลย", "นาบินหลา": "ตรัง",
    "นาเหล่า": "หนองบัวลำภู", "นาโยง": "ตรัง", "นำ้โสม": "อุดรธานี",
    "นิคม": "บุรีรัมย์", "นิคมลำนารายณ์": "ลพบุรี", "น้ำเกลี้ยง": "ศรีสะเกษ",
    "บางกระทุ่ม": "พิษณุโลก", "บางกุ้ง": "สุราษฎร์ธานี", "บางขัน": "นครศรีธรรมราช",
    "บางงาม": "สุพรรณบุรี", "บางซ้าย": "พระนครศรีอยุธยา", "บางนอน": "ระนอง",
    "บางน้ำเปรี้ยว": "ฉะเชิงเทรา", "บางภาษี": "นครปฐม", "บางมูลนาก": "พิจิตร",
    "บางระกำ": "พิษณุโลก", "บางเลน": "สุพรรณบุรี", "บางแลน": "นครปฐม",
    "บางไทร": "พังงา", "บึงบา": "ปทุมธานี", "บึงสามพัน": "เพชรบูรณ์",
    "บ่อกรุ": "สุพรรณบุรี", "บ่อพลอย": "กาญจนบุรี", "บ้านกรวด": "บุรีรัมย์",
    "บ้านกลาง": "แพร่", "บ้านกล้วย": "สุโขทัย", "บ้านดู่": "เชียงราย",
    "บ้านด่านลานหอย": "สุโขทัย", "บ้านผือ": "อุดรธานี", "บ้านฝาง": "ขอนแก่น",
    "บ้านพลวง": "สุรินทร์", "บ้านสร้าง": "ปราจีนบุรี", "บ้านหมี่": "ลพบุรี",
    "บ้านเหลื่อม": "นครราชสีมา", "บ้านโป่ง": "ราชบุรี", "ปทุมราชวงศา": "ยโสธร",
    "ปรางค์กู่": "ศรีสะเกษ", "ปะเหลียน": "ตรัง", "ปักธงชัย": "นครราชสีมา",
    "ปากช่อง": "นครราชสีมา", "ปากท่า": "พระนครศรีอยุธยา", "ปากน้ำ": "ระนอง",
    "ปากพนัง": "นครศรีธรรมราช", "ปากพะยูน": "พัทลุง", "ปางศิลาทอง": "กำแพงเพชร",
    "ป่าคาหลวง": "น่าน", "ผาขาว": "เลย", "พนม": "สุราษฎร์ธานี",
    "พนมทวน": "กาญจนบุรี", "พบพระ": "ตาก", "พยุหะ": "นครสวรรค์",
    "พรหมพิราม": "พิษณุโลก", "พระแสง": "สุราษฎร์ธานี", "พรานกระต่าย": "กำแพงเพชร",
    "พรเจริญ": "บึงกาฬ", "พะโต๊ะ": "ชุมพร", "พัฒนานิคม": "ลพบุรี",
    "พิชัย": "อุตรดิตถ์", "พุนพิน": "สุราษฎร์ธานี", "ฟ้าฮ่าม": "เชียงใหม่",
    "ภูสิงห์": "ศรีสะเกษ", "มะขาม": "จันทบุรี", "มุกดาหาร": "มุกดาหาร",
    "รัตนวาปี": "หนองคาย", "รัษฎา": "นครศรีธรรมราช", "ร่อนพิบูลย์": "นครศรีธรรมราช",
    "ละหาน": "ชัยภูมิ", "ละแม": "ชุมพร", "ลาดบัวหลวง": "พระนครศรีอยุธยา",
    "ลานกระบือ": "กำแพงเพชร", "ลำทับ": "กระบี่", "ลำนารายณ์": "ลพบุรี",
    "ลำลูกกา": "ปทุมธานี", "วงฆ้อง": "พิษณุโลก", "วชิรบารมี": "พิจิตร",
    "วังกระแจะ": "ตราด", "วังกะพี้": "อุตรดิตถ์", "วังจันทร์": "เพชรบุรี",
    "วังตะกอ": "ชุมพร", "วังทรายพูน": "พิจิตร", "วังยาง": "สุพรรณบุรี",
    "วังวิเศษ": "ตรัง", "วังเจ้า": "ตาก", "วังเหนือ": "ลำปาง",
    "วารินชำราบ": "อุบลราชธานี", "วิภาวดี": "สุราษฎร์ธานี", "วิเชียรบุรี": "เพชรบูรณ์",
    "ศรีธาตุ": "อุดรธานี", "ศรีนคร": "สุโขทัย", "ศรีประจันต์": "สุพรรณบุรี",
    "ศรีมหาโพธิ": "ปราจีนบุรี", "ศรีรัตนะ": "ศรีสะเกษ", "ศรีวิไล": "บึงกาฬ",
    "ศรีสัชนาลัย": "สุโขทัย", "ศรีสำราญ": "อุดรธานี", "ศรีสำโรง": "สุโขทัย",
    "ศรีสุทโธ": "อุดรธานี", "ศรีเทพ": "เพชรบูรณ์", "ศีขรภูมิ": "สุรินทร์",
    "สมอแข": "พิษณุโลก", "สรรคบุรี": "ชัยนาท", "สระแก้ว": "สระแก้ว",
    "สระโบสถ์": "ลพบุรี", "สวรรคโลก": "สุโขทัย", "สวี": "ชุมพร",
    "สองพี่น้อง": "สุพรรณบุรี", "สังขะ": "สุรินทร์", "สันกำแพง": "เชียงใหม่",
    "สันติสุข": "น่าน", "สามง่าม": "พิจิตร", "สามเมือง": "พระนครศรีอยุธยา",
    "สามโก้": "อ่างทอง", "สามโคก": "ปทุมธานี", "สิงห์": "สิงห์บุรี",
    "สิชล": "นครศรีธรรมราช", "สิเกา": "ตรัง", "สีคิ้ว": "นครราชสีมา",
    "หนองกระเจ็ด": "เพชรบุรี", "หนองกุ่ม": "กาญจนบุรี", "หนองฉาง": "อุทัยธานี",
    "หนองบัว": "นครสวรรค์", "หนองปลาหมอ": "ราชบุรี", "หนองม่วง": "ลพบุรี",
    "หนองสาหร่าย": "นครราชสีมา", "หนองหญ้าไซ": "สุพรรณบุรี", "หนองหาน": "อุดรธานี",
    "หนองหิน": "เลย", "หนองเสือ": "ปทุมธานี", "หนองไขว่": "เพชรบูรณ์",
    "หนองไผ่ล้อม": "สุรินทร์", "หลักช้าง": "นครศรีธรรมราช", "หล่มเก่า": "เพชรบูรณ์",
    "หันคา": "ชัยนาท", "หัวตะพาน": "อำนาจเจริญ", "หัวไทร": "นครศรีธรรมราช",
    "ห้วยทับมอญ": "ระยอง", "อิปัน": "สุราษฎร์ธานี", "อุดมทรัพย์": "นครราชสีมา",
    "อู่ทอง": "สุพรรณบุรี", "อ่าวน้อย": "ประจวบคีรีขันธ์", "อ่าวลึก": "กระบี่",
    "เขาคันทรง": "ชลบุรี", "เขาบางแกรก": "อุทัยธานี", "เขาพนม": "กระบี่",
    "เคียนซา": "สุราษฎร์ธานี", "เฉลิมพระเกียรติ": "นครศรีธรรมราช",
    "เชียงทอง": "ตาก", "เชียงบาน": "พะเยา", "เดิมบาง": "สุพรรณบุรี",
    "เดิมบางนางบวช": "สุพรรณบุรี", "เตาปูน": "สระบุรี", "เถิน": "ลำปาง",
    "เทพสถิต": "ชัยภูมิ", "เทพารักษ์": "นครราชสีมา", "เฝ้าไร่": "หนองคาย",
    "เมือง": "สตูล", "เมืองขอนแก่น": "ขอนแก่น", "เมืองฉะเชิงเทรา": "ฉะเชิงเทรา",
    "เมืองชัยนาท": "ชัยนาท", "เมืองชัยภูมิ": "ชัยภูมิ",
    "เมืองนครราชสีมา": "นครราชสีมา", "เมืองนครศรีธรรมราช": "นครศรีธรรมราช",
    "เมืองน่าน": "น่าน", "เมืองบุรีรัมย์": "บุรีรัมย์",
    "เมืองปราจีนบุรี": "ปราจีนบุรี", "เมืองพิจิตร": "พิจิตร",
    "เมืองยโสธร": "ยโสธร", "เมืองลพบุรี": "ลพบุรี",
    "เมืองสวรรคโลก": "สุโขทัย", "เมืองสุโขทัย": "สุโขทัย",
    "เมืองหนองบัวลำภู": "หนองบัวลำภู", "เมืองอำนาจเจริญ": "อำนาจเจริญ",
    "เมืองอุดรธานี": "อุดรธานี", "เมืองใต้": "ศรีสะเกษ",
    "เลาขวัญ": "กาญจนบุรี", "เลิงนกทา": "ยโสธร", "เวียงสระ": "สุราษฎร์ธานี",
    "เสลภูมิ": "ร้อยเอ็ด", "เหนือคลอง": "ตรัง", "เหล่ายาว": "ลำพูน",
    "แม่ระมาด": "ตาก", "แม่สอด": "ตาก", "แม่สาย": "เชียงราย",
    "แม่เปิน": "นครสวรรค์", "โคกงาม": "เลย", "โคกสำโรง": "ลพบุรี",
    "โคกสูง": "สระแก้ว", "โชคชัย": "นครราชสีมา", "โซ่พิสัย": "บึงกาฬ",
    "โนนแดง": "นครราชสีมา", "โนนไทย": "นครราชสีมา", "โพทะเล": "พิจิตร",
    "โพธิ์ประทับช้าง": "พิจิตร", "โพรงอากาศ": "ฉะเชิงเทรา", "โสน": "ศรีสะเกษ",
    "ในเมือง": "นครราชสีมา", "ไชยวาน": "อุดรธานี", "ไทรงาม": "กำแพงเพชร",
    "ไทรน้อย": "นนทบุรี", "ไทรโยค": "กาญจนบุรี", "ไพรบึง": "ศรีสะเกษ",
}

_PROVINCES_STRIPPED = {strip_thai_diacritics(p): p for p in KNOWN_PROVINCES}
_DISTRICTS_STRIPPED = {strip_thai_diacritics(d): d for d in DISTRICT_TO_PROVINCE}


# ============================================================================
# Location Extraction (3-layer + alias matching)
# ============================================================================

def _strip_location_prefix(text: str) -> str:
    """ลบ จ. / จังหวัด / อ. / อำเภอ / ต. / ตำบล ออก"""
    text = re.sub(r'(^|\s)(จ\.|จังหวัด|อ\.|อำเภอ|ต\.|ตำบล)\s*', ' ', text)
    return text.strip()


def _extract_subdistrict_name(message: str) -> str | None:
    """ดึงชื่อตำบลจาก ต./ตำบล prefix ในข้อความ"""
    m = re.search(r'(?:ต\.|ตำบล)\s*(\S+)', message)
    return m.group(1) if m else None


def _find_district_in_msg(msg: str, msg_stripped: str) -> str:
    """ค้นหาชื่ออำเภอในข้อความ (exact → diacritics-stripped)"""
    for dist in DISTRICT_TO_PROVINCE:
        if dist in msg:
            return dist
    for stripped, original in _DISTRICTS_STRIPPED.items():
        if stripped in msg_stripped:
            return original
    return None


def extract_location(message: str) -> tuple:
    """ดึงจังหวัด + อำเภอ + ตำบล จากข้อความ (3 ชั้น matching + alias)

    Layers:
      1. Exact match (longest-first)
      1.5. Alias match (ชื่อเล่น/ชื่อย่อ)
      2. Diacritics-stripped match (longest-first)
      3. Prefix-substring match (ใช้ PROVINCE_PREFIXES, ไม่พึ่ง word split)

    Returns:
        (province, district, subdistrict) — เป็น str หรือ None
    """
    # ไม่ใช้ regex ดึง subdistrict — ใช้ LLM เป็นหลัก (regex จับเกินเช่น "สนามแย้มีไหมคับ")
    found_subdistrict = None

    msg = _strip_location_prefix(message)
    msg_stripped = strip_thai_diacritics(msg)
    found_province = None

    # --- ชั้น 1: Exact match (longest-first เพื่อ match ชื่อยาวก่อน) ---
    for prov in sorted(KNOWN_PROVINCES, key=len, reverse=True):
        if prov in msg:
            found_province = prov
            break

    # --- ชั้น 1.5: Alias match (ชื่อเล่น/ชื่อย่อ, longest-first) ---
    if not found_province:
        for alias in sorted(PROVINCE_ALIASES, key=len, reverse=True):
            if alias in msg:
                found_province = PROVINCE_ALIASES[alias]
                break

    # --- ชั้น 2: Diacritics-stripped match (longest-first) ---
    if not found_province:
        for stripped in sorted(_PROVINCES_STRIPPED, key=len, reverse=True):
            if stripped in msg_stripped:
                found_province = _PROVINCES_STRIPPED[stripped]
                break

    # --- ชั้น 3: Prefix-substring match (ใช้ `prefix in msg` ไม่พึ่ง split) ---
    if not found_province:
        best_prefix = ""
        for prefix, prov in PROVINCE_PREFIXES.items():
            if prefix in msg and len(prefix) > len(best_prefix):
                best_prefix = prefix
                found_province = prov

    # --- District lookup (ทำเสมอ ไม่ว่าจะเจอ province หรือยัง) ---
    found_district = _find_district_in_msg(msg, msg_stripped)

    if found_province:
        return (found_province, found_district, found_subdistrict)

    # ถ้าไม่เจอจังหวัด แต่เจอ district → ดึงจังหวัดจาก district
    if found_district:
        return (DISTRICT_TO_PROVINCE[found_district], found_district, found_subdistrict)

    return (None, None, None)


# ============================================================================
# Explicit Province Detection
# ============================================================================

def message_has_explicit_province(message: str) -> bool:
    """ตรวจว่าข้อความมีชื่อจังหวัดระบุชัดเจน (ไม่ใช่ infer จากอำเภอ/ตำบล)

    ใช้เพื่อตัดสินใจว่าควร search เลย หรือถามจังหวัดก่อน
    """
    msg = _strip_location_prefix(message)
    msg_stripped = strip_thai_diacritics(msg)

    # Check exact province names (65 + 12 = 77 จังหวัด)
    for prov in ALL_THAI_PROVINCES:
        if prov in msg:
            return True

    # Check aliases (โคราช, สุราษ, อุบล, etc.)
    for alias in PROVINCE_ALIASES:
        if alias in msg:
            return True

    # Check diacritics-stripped
    for stripped_prov in _PROVINCES_STRIPPED:
        if stripped_prov in msg_stripped:
            return True

    # Check province prefixes (4+ char unique prefixes)
    for prefix in PROVINCE_PREFIXES:
        if prefix in msg:
            return True

    return False


# ============================================================================
# LLM-based Province Extraction (gpt-4o-mini)
# ============================================================================

async def extract_location_llm(message: str) -> tuple:
    """ใช้ LLM (gpt-4o-mini) ระบุจังหวัด + อำเภอ + ตำบล จากข้อความ user

    Step 1: LLM extract province + district + subdistrict
    Step 2: Static filter district ภายในจังหวัดที่ได้
    Fallback: ถ้า LLM return (None, None, None) → ลอง static extract_location()
    Fallback: ถ้า LLM error → ใช้ static extract_location()
    """
    if not openai_client:
        return extract_location(message)

    try:
        provinces_list = ", ".join(ALL_THAI_PROVINCES)
        prompt = f"""จากข้อความ: "{message}"

ช่วยระบุว่าผู้ใช้หมายถึงจังหวัดอะไร อำเภออะไร และตำบลอะไร

จังหวัดที่มีในระบบ:
{provinces_list}

ตอบเป็น JSON เท่านั้น:
{{"province": "ชื่อจังหวัดเต็มจากรายชื่อด้านบน หรือ null", "district": "ชื่ออำเภอ หรือ null", "subdistrict": "ชื่อตำบล หรือ null"}}

กฎ:
- ต้องเลือกจังหวัดจากรายชื่อด้านบนเท่านั้น ห้ามสร้างชื่อเอง
- ถ้าผู้ใช้บอกชื่ออำเภอ ให้ระบุจังหวัดที่อำเภอนั้นสังกัดด้วย
- ถ้าผู้ใช้บอกชื่อตำบล ให้ระบุจังหวัด อำเภอ และตำบลที่ตำบลนั้นสังกัด
- ถ้าผู้ใช้พูดถึง ต. หรือ ตำบล ให้ใส่ใน subdistrict
- รองรับชื่อเล่น เช่น โคราช→นครราชสีมา, สุราษ→สุราษฎร์ธานี
- รองรับ typo เช่น นคราชสีมา→นครราชสีมา
- ถ้าไม่มีการกล่าวถึงสถานที่เลย ตอบ null ทั้งหมด"""

        response = await openai_client.chat.completions.create(
            model=LLM_MODEL_DEALER_EXTRACTION,
            messages=[
                {"role": "system", "content": "คุณเป็นผู้ช่วยระบุชื่อจังหวัด อำเภอ และตำบลในประเทศไทย ตอบเป็น JSON เท่านั้น"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_completion_tokens=150
        )

        # Parse JSON response (strip markdown code fences if present)
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)
        province = result.get("province")
        llm_district = result.get("district")
        llm_subdistrict = result.get("subdistrict")

        # Strip อำเภอ/ตำบล prefixes (LLM อาจใส่มา เช่น "อำเภอเมืองลพบุรี" → "เมืองลพบุรี")
        if llm_district:
            llm_district = re.sub(r'^(อำเภอ|อ\.)\s*', '', llm_district).strip()
        if llm_subdistrict:
            llm_subdistrict = re.sub(r'^(ตำบล|ต\.)\s*', '', llm_subdistrict).strip()

        # Validate: ต้องอยู่ใน ALL_THAI_PROVINCES (65 มี dealer + 12 ไม่มี)
        if province and province not in ALL_THAI_PROVINCES:
            logger.warning(f"LLM returned unknown province: {province}")
            province = None

        # Step 2: Static district matching ภายในจังหวัดที่ได้
        district = None
        if province:
            district = _find_district_for_province(message, province)
            # ถ้า static ไม่เจอ district แต่ LLM ให้มา → ใช้ของ LLM
            if not district and llm_district:
                district = llm_district

        # Subdistrict: ใช้ LLM value อย่างเดียว (ไม่ fallback regex — จับเกิน)
        subdistrict = llm_subdistrict

        # Fallback: LLM ไม่เจอ province → ลอง static extraction
        # แต่เก็บ LLM district/subdistrict ไว้ถ้า static ไม่เจอ
        if not province:
            static_prov, static_dist, static_sub = extract_location(message)
            if not static_dist and llm_district:
                static_dist = llm_district
            if not static_sub and llm_subdistrict:
                static_sub = llm_subdistrict
            return (static_prov, static_dist, static_sub)

        return (province, district, subdistrict)

    except Exception as e:
        logger.error(f"LLM province extraction failed: {e}")
        return extract_location(message)


def _find_district_for_province(message: str, province: str) -> str | None:
    """หาอำเภอจากข้อความ โดยกรองเฉพาะอำเภอในจังหวัดที่ระบุ"""
    msg = _strip_location_prefix(message)
    # กรอง districts ที่อยู่ในจังหวัดเดียวกัน
    province_districts = [d for d, p in DISTRICT_TO_PROVINCE.items() if p == province]
    # เรียงยาวก่อน เพื่อ match ชื่อยาวก่อนชื่อสั้น
    for dist in sorted(province_districts, key=len, reverse=True):
        if dist in msg:
            return dist
    # ลอง diacritics-stripped
    msg_stripped = strip_thai_diacritics(msg)
    for dist in province_districts:
        if strip_thai_diacritics(dist) in msg_stripped:
            return dist
    return None


# ============================================================================
# Supabase Search
# ============================================================================

async def search_dealers(province: str, district: str = None,
                        subdistrict: str = None,
                        max_dealer: int = 5, max_sub: int = 5) -> list:
    """ค้นหาตัวแทนจำหน่ายจาก Supabase — แยก query Dealer / Sub Dealer"""
    if not supabase_client:
        logger.error("Supabase client not available for dealer search")
        return []

    try:
        results = []
        for dtype, lim in [("Dealer", max_dealer), ("Sub Dealer", max_sub)]:
            query = supabase_client.table("dealers") \
                .select("dealer_name, zone, province, district, subdistrict, phone, dealer_type") \
                .ilike("province", f"%{province}%") \
                .eq("dealer_type", dtype)

            if district:
                query = query.ilike("district", f"%{district}%")

            if subdistrict:
                query = query.ilike("subdistrict", f"%{subdistrict}%")

            query = query.limit(lim)
            result = query.execute()
            results.extend(result.data or [])

        return results

    except Exception as e:
        logger.error(f"Error searching dealers: {e}", exc_info=True)
        return []


# ============================================================================
# Response Formatting
# ============================================================================

def _format_dealer_location(d: dict) -> str:
    """จัดรูปที่ตั้ง dealer: อ.XXX ต.YYY"""
    district = d.get("district") or "-"
    subdistrict = d.get("subdistrict")
    if subdistrict:
        return f"อ.{district} ต.{subdistrict}"
    return f"อ.{district}"


def format_dealer_response(dealers: list, province: str) -> str:
    """จัดรูปข้อความตอบกลับแสดงรายชื่อตัวแทน"""
    main_dealers = [d for d in dealers if d.get("dealer_type") == "Dealer"]
    sub_dealers = [d for d in dealers if d.get("dealer_type") == "Sub Dealer"]

    lines = [f"ตัวแทนจำหน่ายม้าบินใน จ.{province} 🌱"]
    lines.append("")

    if main_dealers:
        lines.append("ตัวแทนหลัก (Dealer):")
        for i, d in enumerate(main_dealers, 1):
            name = d.get("dealer_name", "-")
            location = _format_dealer_location(d)
            phone = d.get("phone") or "-"
            lines.append(f"{i}. {name}")
            lines.append(f"   {location} | โทร {phone}")
        lines.append("")

    if sub_dealers:
        lines.append("ตัวแทนย่อย (Sub Dealer):")
        for i, d in enumerate(sub_dealers, 1):
            name = d.get("dealer_name", "-")
            location = _format_dealer_location(d)
            phone = d.get("phone") or "-"
            lines.append(f"{i}. {name}")
            lines.append(f"   {location} | โทร {phone}")
        lines.append("")

    lines.append("ติดต่อสอบถามรายละเอียดได้เลยนะครับ 😊")

    return "\n".join(lines)


# ============================================================================
# Province from Conversation Context
# ============================================================================

def extract_province_from_context(context: str) -> tuple:
    """ดึงจังหวัด/อำเภอ/ตำบลจาก conversation context (ข้อความล่าสุดก่อน)"""
    if not context:
        return (None, None, None)
    lines = context.strip().split('\n')
    for line in reversed(lines):
        province, district, subdistrict = extract_location(line)
        if province:
            return (province, district, subdistrict)
    return (None, None, None)


# ============================================================================
# Fallback Search — แนะนำจังหวัดในโซนเดียวกัน
# ============================================================================

async def search_dealers_with_fallback(province: str, district: str = None,
                                      subdistrict: str = None) -> tuple:
    """ค้นหา dealer พร้อม fallback (subdistrict → district → province → zone → nearby)

    Returns: (dealers, fallback_province, missed_location)
      - เจอตรง → (dealers, None, None)
      - ตำบลไม่มี แต่อำเภอ/จังหวัดมี → (dealers, None, "ต.XXX")
      - อำเภอไม่มี แต่จังหวัดมี → (dealers, None, "อ.XXX")
      - จังหวัดไม่มี แต่ใกล้เคียงมี → (dealers, nearby_province, None)
      - ไม่เจอเลย → ([], None, None)
    """
    # Step 1: ค้นหาตรงๆ (province + district + subdistrict)
    dealers = await search_dealers(province, district, subdistrict)
    if dealers:
        return (dealers, None, None)

    # Step 1.5: Subdistrict fallback — ถ้ามี subdistrict แต่ไม่เจอ → ลองหาแค่ district
    if subdistrict:
        dealers = await search_dealers(province, district)
        if dealers:
            return (dealers, None, f"ต.{subdistrict}")

    # Step 2: District fallback — ถ้ามี district แต่ไม่เจอ → ลองหาแค่จังหวัด
    if district:
        dealers = await search_dealers(province)
        if dealers:
            return (dealers, None, f"อ.{district}")

    # Step 3: Zone fallback — ค้นหาจังหวัดอื่นในโซนเดียวกัน
    if not supabase_client:
        return ([], None, None)

    try:
        zone_result = supabase_client.table("dealers") \
            .select("zone") \
            .ilike("province", f"%{province}%") \
            .limit(1) \
            .execute()

        if not zone_result.data:
            # Step 4: ใช้ PROVINCES_NO_DEALER mapping
            if province in PROVINCES_NO_DEALER:
                for nearby_prov in PROVINCES_NO_DEALER[province]:
                    nearby_dealers = await search_dealers(nearby_prov)
                    if nearby_dealers:
                        return (nearby_dealers, nearby_prov, None)
            return ([], None, None)

        zone = zone_result.data[0].get("zone")
        if not zone:
            return ([], None, None)

        nearby = supabase_client.table("dealers") \
            .select("dealer_name, province, district, phone, dealer_type") \
            .eq("zone", zone) \
            .neq("province", province) \
            .limit(5) \
            .execute()

        if nearby.data:
            nearby_province = nearby.data[0].get("province", "")
            return (nearby.data, nearby_province, None)
    except Exception as e:
        logger.error(f"Fallback search error: {e}")

    # Step 4: ใช้ PROVINCES_NO_DEALER mapping (ถ้า zone fallback error)
    if province in PROVINCES_NO_DEALER:
        try:
            for nearby_prov in PROVINCES_NO_DEALER[province]:
                nearby_dealers = await search_dealers(nearby_prov)
                if nearby_dealers:
                    return (nearby_dealers, nearby_prov, None)
        except Exception as e:
            logger.error(f"PROVINCES_NO_DEALER fallback error: {e}")

    return ([], None, None)


# ============================================================================
# Suggestion Suffix
# ============================================================================

# ข้อความถามกลับต่อท้ายคำตอบปุ๋ย/สินค้า
DEALER_SUGGESTION_SUFFIX = "\n\nหากต้องการหาตัวแทนจำหน่ายม้าบินใกล้บ้าน บอกจังหวัดมาได้เลยนะครับ 😊"
