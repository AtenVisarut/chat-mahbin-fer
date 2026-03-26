# CHANGELOG 2026-02-16

## Feature: Dealer Lookup (ค้นหาตัวแทนจำหน่าย)

### Commit `5ae0773` — feat: add dealer lookup feature with fuzzy province matching

สร้างระบบค้นหาตัวแทนจำหน่ายม้าบินทั้งหมดจากศูนย์:

**ไฟล์ใหม่:**
- `app/services/dealer_lookup.py` — module หลัก
  - `is_dealer_question()` — keyword detection (L1)
  - `extract_location()` — ดึงจังหวัด/อำเภอ 4 ชั้น fuzzy matching (exact → diacritics-stripped → prefix → SequenceMatcher)
  - `search_dealers()` — query Supabase `dealers` table แยก Dealer / Sub Dealer
  - `format_dealer_response()` — จัดรูปข้อความตอบกลับ
  - `extract_province_from_context()` — ดึงจังหวัดจาก conversation context
  - `search_dealers_with_fallback()` — fallback ไปจังหวัดใกล้เคียง (โซนเดียวกัน)
  - `DEALER_SUGGESTION_SUFFIX` — ข้อความถามกลับต่อท้ายคำตอบปุ๋ย
  - 65 จังหวัด + 276 อำเภอ mapping (จาก CSV ตัวแทนจริง)
- `scripts/setup_dealers_table.sql` — SQL สร้างตาราง `dealers` ใน Supabase
- `scripts/import_dealers.py` — import ข้อมูลจาก CSV เข้า Supabase (414 records)

**ไฟล์ที่แก้:**
- `app/services/chat/handler.py` — เพิ่ม dealer routing ใน `handle_natural_conversation()`
  - L1 keyword check → extract location → search → format response
  - Pending context flow: ถ้าไม่มีจังหวัด → ถาม → รอคำตอบ
  - เพิ่ม `DEALER_SUGGESTION_SUFFIX` ต่อท้ายคำตอบปุ๋ย/สินค้า
- `app/routers/webhook.py` — จัดการ `awaiting_dealer_province` pending context
- `app/prompts.py` — เพิ่ม persona ว่ารู้จักร้านค้าตัวแทน
- `app/services/rag/response_generator_agent.py` — เพิ่ม dealer suggestion ใน RAG response

**Supabase:**
- สร้างตาราง `dealers` — 414 records (Dealer + Sub Dealer ทั่วประเทศ)

---

### Commit `3059309` — fix: extract district alongside province in dealer lookup

แก้ให้ extract อำเภอพร้อมจังหวัดในทุก flow:
- `handler.py` — ส่ง district ไปด้วยตอน search
- `webhook.py` — pending context flow ส่ง district เช่นกัน

---

### Commit `761dc31` — feat: hybrid 3-layer dealer detection with LLM intent classification

ปรับปรุง dealer detection จาก keyword-only เป็น hybrid 3 layers:

| Layer | วิธี | จับได้ |
|-------|------|--------|
| L1: Keywords | `is_dealer_question()` | pattern ชัดเจน เช่น "ร้านค้า", "ซื้อที่ไหน" |
| L3: LLM Intent | `QueryUnderstandingAgent` → `DEALER_INQUIRY` | ทุก pattern เช่น "ใกล้อำเภอคำพราน มีไหม" |

**ปัญหาที่แก้:**
- "ใกล้อำเภอ คำพราน มีไหมครับ" → เดิมไม่ match keyword → ไป RAG → ตอบผิด
- "มีร้านที่จังหวัดลพบุรีไหมคับ" → เดิมไม่ match keyword → ตอบผิด
- ตอนนี้ LLM จับ intent ได้ → route ไป dealer lookup ถูกต้อง

**ไฟล์ที่แก้ (6 ไฟล์):**

1. `app/services/rag/__init__.py`
   - เพิ่ม `DEALER_INQUIRY = "dealer_inquiry"` ใน `IntentType` enum

2. `app/services/rag/query_understanding_agent.py`
   - เพิ่ม `dealer_inquiry` ใน LLM prompt (intent_type list)
   - เพิ่ม 2 ตัวอย่าง: "มีร้านที่จังหวัดลพบุรีไหม", "ใกล้อำเภอคำพราน มีไหม"
   - เพิ่ม `"dealer_inquiry": IntentType.DEALER_INQUIRY` ใน intent mapping

3. `app/services/rag/orchestrator.py`
   - เพิ่ม short-circuit early return สำหรับ `DEALER_INQUIRY` (หลัง GREETING, ก่อน UNKNOWN)
   - Return `answer=None` + `intent=DEALER_INQUIRY` → handler จัดการต่อ

4. `app/services/chat/handler.py`
   - เพิ่ม `from app.services.rag import IntentType`
   - จับ `rag_response.intent == DEALER_INQUIRY` → route ไป dealer lookup
   - ลบ context-aware hack (`_dealer_in_context` / `_msg_has_location`)
   - Deduplicate `DEALER_SUGGESTION_SUFFIX` (ไม่ต่อท้ายซ้ำถ้า context มีอยู่แล้ว)

5. `app/services/dealer_lookup.py`
   - Revert `DEALER_KEYWORDS` กลับเป็นชุดเดิม (ลบ "มีร้าน", "ร้านที่", "ใกล้อำเภอ", "มีตัวแทน")
   - L3 (LLM) จับ pattern เหล่านี้ได้แล้ว ไม่ต้องเพิ่ม keyword

6. `app/routers/webhook.py`
   - ใช้ `search_dealers_with_fallback()` แทน `search_dealers()`
   - เพิ่ม retry logic: ถ้าไม่เจอครั้งแรก → ถามซ้ำ → ครั้งที่ 2 → จบ flow

---

## Flow สรุป (หลังแก้ทั้งหมด)

```
User message เข้ามา
  ↓
[L1] is_dealer_question() → keyword match? → YES → dealer lookup (instant, free)
  ↓ NO
[Route to RAG]
  ↓
QueryUnderstandingAgent (LLM) → intent = DEALER_INQUIRY?
  ↓ YES
Orchestrator short-circuit → answer=None, intent=DEALER_INQUIRY
  ↓
Handler จับ DEALER_INQUIRY → extract_location() → search_dealers_with_fallback()
  ↓
แสดงร้านค้า / ถามจังหวัด / fallback จังหวัดใกล้เคียง
```
