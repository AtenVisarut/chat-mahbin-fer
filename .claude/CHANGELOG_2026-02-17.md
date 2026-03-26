# CHANGELOG 2026-02-17

## Dealer Lookup v2 — รองรับ อำเภอ/ตำบล + ถามจังหวัดกลับ

วันนี้ปรับปรุง Dealer Lookup ใหญ่ 5 commits (4 files, +399/-79 lines)
แก้ปัญหา bot เดาจังหวัดผิดเมื่อ user บอกแค่ อำเภอ/ตำบล

---

### Commit `963bf48` — feat: use LLM (gpt-4o-mini) for province extraction

เปลี่ยนจาก static-only extraction เป็น **LLM-first + static fallback**:

- `extract_location_llm()` — ใช้ gpt-4o-mini ระบุจังหวัดจากข้อความ
  - รองรับชื่อเล่น (โคราช, สุราษ), typo, ชื่อย่อ
  - ถ้า LLM error → fallback ไป `extract_location()` (static 3-layer)
- `_find_district_for_province()` — หาอำเภอจากข้อความ กรองเฉพาะจังหวัดที่ LLM ระบุ
- เพิ่ม `LLM_MODEL_DEALER_EXTRACTION` ใน `config.py` (gpt-4o-mini)
- Handler + webhook เรียก `extract_location_llm()` แทน `extract_location()`

---

### Commit `1cf32db` — feat: add nearby province fallback for 12 provinces without dealers

เพิ่ม **PROVINCES_NO_DEALER** mapping สำหรับ 12 จังหวัดที่ไม่มี dealer:

| จังหวัด | Fallback ไป |
|---------|-------------|
| กรุงเทพมหานคร | ปทุมธานี, นนทบุรี |
| สมุทรปราการ | ชลบุรี, ฉะเชิงเทรา |
| ภูเก็ต | พังงา, สุราษฎร์ธานี |
| ฯลฯ (12 จังหวัด) | |

- `search_dealers_with_fallback()` — ถ้า zone fallback ไม่เจอ → ใช้ PROVINCES_NO_DEALER
- Response: "ยังไม่พบตัวแทนใน จ.กรุงเทพฯ แต่มีในจังหวัดใกล้เคียง (ปทุมธานี)"

---

### Commit `acf836f` — fix: dealer lookup understands district/subdistrict without province

**ปัญหา**: "หาร้านที่ อ.ปากช่อง" → LLM return province=null → bot ถามจังหวัดซ้ำ

**แก้ไข 2 จุด**:

1. **LLM prompt** — ถาม province + district (ก่อนถามแค่ province)
   - "ถ้าผู้ใช้บอกชื่ออำเภอ ให้ระบุจังหวัดที่อำเภอนั้นสังกัดด้วย"
   - "ถ้าผู้ใช้บอกชื่อตำบล ให้ระบุจังหวัดและอำเภอที่ตำบลนั้นสังกัด"
   - Static fallback: ถ้า LLM return null → เรียก `extract_location()` (302 อำเภอ mapping)

2. **District-level fallback** — `search_dealers_with_fallback()` return 3-tuple:
   ```
   (dealers, fallback_province, missed_district)
   ```
   - ถ้า อำเภอไม่มี dealer → ลองหาระดับจังหวัด → "อ.XXX ไม่พบ แต่จ.YYY มี"

---

### Commit `fe7ff82` — feat: add subdistrict (ตำบล) search support

**ปัญหา**: "ต.นาด้วง มีร้านไหม" → bot ตอบแค่ระดับอำเภอ ไม่ search ตำบล

**แก้ไข (ทั้ง pipeline)**:

1. **Extraction** — return 3-tuple `(province, district, subdistrict)`
   - `_extract_subdistrict_name()` — ดึงชื่อตำบลจาก ต./ตำบล prefix
   - `_strip_location_prefix()` — ลบ จ./อ./ต. prefix (เดิมไม่มี ต.)
   - LLM prompt ถาม province + district + subdistrict
   - `extract_location()`, `extract_location_llm()`, `extract_province_from_context()` — ทั้งหมด return 3-tuple

2. **Search** — `search_dealers()` เพิ่ม `subdistrict` parameter
   - Filter ด้วย `subdistrict` column ใน Supabase (414 ร้านมี subdistrict ทั้งหมด, 353 unique)

3. **Fallback chain** ใหม่:
   ```
   subdistrict → district → province → zone → nearby
   ```
   - Return `(dealers, fallback_prov, missed_location)` — missed_location มี prefix "ต.XXX" หรือ "อ.XXX"

4. **format_dealer_response()** — แสดง `อ.XXX ต.YYY` ในรายการร้าน (เดิมแสดงแค่ อ.)

---

### Commit `c3b7e45` — fix: ask province when user mentions only district/subdistrict

**ปัญหาหลัก** (จาก screenshot):
```
User: "ในบางเลนมีไหม"
Bot: guessed สมุทรปราการ (ผิด!) → fallback ชลบุรี ❌
```

**แก้ไข**: ถ้า user บอกแค่ อ./ต. โดยไม่บอกจังหวัด → **ถามจังหวัดกลับ** แทนเดา

1. **`message_has_explicit_province()`** — ตรวจว่าข้อความมีชื่อจังหวัดชัดเจน
   - Check: ALL_THAI_PROVINCES (77 จังหวัด), PROVINCE_ALIASES, diacritics-stripped, prefixes
   - ไม่รวม DISTRICT_TO_PROVINCE (ไม่ infer จากอำเภอ)

2. **Handler flow ใหม่**:
   ```
   ถ้า has_explicit_province = False:
     ถ้ามี district/subdistrict:
       → "อ.บางเลน อยู่จังหวัดไหนครับ?" + save district/subdistrict
     ถ้าไม่มีอะไรเลย:
       → "รบกวนบอกจังหวัดหรืออำเภอหน่อยนะครับ?"
   ถ้า has_explicit_province = True:
       → search ตรงเลย
   ```

3. **Webhook pending context merge** — เมื่อ user ตอบจังหวัด → merge กับ saved district/subdistrict

4. **เพิ่ม aliases**: กรุงเทพ, กทม → กรุงเทพมหานคร
5. **Prefix builder**: ใช้ ALL_THAI_PROVINCES แทน KNOWN_PROVINCES (รวม 12 จังหวัดไม่มี dealer)

---

## Flow สรุป (หลังแก้ทั้งหมด)

```
User: "อ.บางเลน มีร้านไหม"
  │
  ▼
extract_location_llm() → province=นครปฐม, district=บางเลน
message_has_explicit_province() → False (ไม่มีชื่อจังหวัดในข้อความ)
  │
  ▼
Bot: "อ.บางเลน อยู่จังหวัดไหนครับ?" (save district=บางเลน)
  │
  ▼
User: "นครปฐม"
  │
  ▼
extract_location_llm("นครปฐม") → province=นครปฐม
merge: district=บางเลน (from saved context)
search_dealers("นครปฐม", "บางเลน") → 3 ร้าน ✅
```

```
User: "หาร้านม้าบินที่ขอนแก่น"
  │
  ▼
message_has_explicit_province() → True ("ขอนแก่น" found)
  │
  ▼
search_dealers("ขอนแก่น") → 5 ร้าน ✅ (search ตรง ไม่ต้องถาม)
```

---

## ไฟล์ที่แก้วันนี้

| ไฟล์ | สิ่งที่เปลี่ยน |
|------|--------------|
| `app/config.py` | เพิ่ม `LLM_MODEL_DEALER_EXTRACTION` |
| `app/services/dealer_lookup.py` | LLM extraction, subdistrict support, explicit province check, fallback chain, format with ต. |
| `app/services/chat/handler.py` | 3-tuple unpack, ask-province flow, missed_location handling (L1 + AgenticRAG) |
| `app/routers/webhook.py` | 3-tuple unpack, merge saved district/subdistrict from pending context |

**Total: 4 files, +399 lines, -79 lines, 5 commits**
