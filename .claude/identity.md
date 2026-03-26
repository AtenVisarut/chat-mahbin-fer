# Claude Identity — Chatbot พี่ม้าบิน (Mahbin-fer)

> ไฟล์นี้ใช้ให้ Claude จำการทำงานข้ามเซสชัน

---

## Project Info
- **ชื่อโปรเจค**: Chatbot พี่ม้าบิน (ที่ปรึกษาปุ๋ย ICP Fertilizer)
- **Stack**: FastAPI + Supabase (sync client) + OpenAI + LINE Messaging API + Facebook Messenger
- **GitHub**: `https://github.com/AtenVisarut/chat-mahbin.git` (origin/main)
- **Deploy**: Railway (auto deploy จาก GitHub)
- **Working Dir**: `C:\รวมProject_Chatbot-ICPL\chatbot_mahbin\Chatbot-Mahbin-fer\`

---

## สิ่งที่ทำวันที่ 2026-02-23

### ปรับปรุง User Tracking — `user_fer(LINE,FACE)` table

**ไฟล์ที่แก้**: `app/services/user_service.py`
**Commit**: `448422b` — pushed to origin/main

#### สิ่งที่เปลี่ยน:

1. **`register_user_fer()`** — ปรับปรุงให้ครบ
   - User ใหม่ → `INSERT` พร้อม `created_at`, `updated_at`
   - User เดิม → `UPDATE` เฉพาะ `display_name` + `updated_at`
   - เพิ่ม `from datetime import datetime, timezone` สำหรับ timestamp

2. **`ensure_user_exists()`** — แก้ให้เรียก `register_user_fer()` ทุกครั้ง
   - **ก่อน**: เรียกเฉพาะ user ใหม่ที่ไม่อยู่ใน `users` table
   - **หลัง**: เรียกทุกครั้ง ทั้ง user ใหม่และ user เดิม
   - ช่วย backfill user เก่าที่อยู่ใน `users` แต่ยังไม่อยู่ใน `user_fer(LINE,FACE)`

#### โครงสร้างตาราง `user_fer(LINE,FACE)` ใน Supabase:

| column | type | nullable | note |
|---|---|---|---|
| id | bigint (identity) | NO | auto-increment |
| created_at | timestamp with time zone | NO | วันที่เข้ามาครั้งแรก |
| line_user_id | text | YES | LINE user ID หรือ `fb:{psid}` |
| display_name | text | YES | ชื่อจาก LINE/FB Profile API |
| updated_at | timestamp with time zone | YES | วันที่ส่งข้อความล่าสุด |

#### ปัญหาที่พบ:
- ตาราง `user_fer(LINE,FACE)` เดิมมีแค่ `id`, `created_at` → ต้อง ALTER TABLE เพิ่ม `line_user_id`, `display_name`, `updated_at`
- `id` เป็น identity column (auto-increment) อยู่แล้ว แต่ `column_default` query ไม่แสดงค่า
- INSERT ตรงจาก SQL สำเร็จ → ปัญหาอยู่ที่ Railway อาจยังไม่ deploy โค้ดใหม่

#### Flow การทำงาน:
```
LINE/FB user ส่งข้อความ
  → webhook.py / facebook_webhook.py
    → ensure_user_exists(user_id)
      → register_user_fer(user_id, display_name)
        → user ใหม่: INSERT (line_user_id, display_name, created_at, updated_at)
        → user เดิม: UPDATE (display_name, updated_at)
```

---

## สิ่งที่ทำก่อนหน้า

### 2026-02-22: User Tracking เบื้องต้น
- เพิ่ม `get_facebook_profile()` — ดึงชื่อ FB ผ่าน Graph API v21.0
- เพิ่ม `register_user_fer()` — insert ลง `user_fer(LINE,FACE)` (เวอร์ชันแรก)
- อัปเดต `ensure_user_exists()` — แยก platform (fb: = Facebook, อื่นๆ = LINE)

### 2026-02-16: Dealer Lookup
- 414 ตัวแทนจำหน่ายในตาราง `dealers`
- Fuzzy province matching + pending context flow

---

## Key Files
- `app/services/user_service.py` — User management, LINE/FB profile, user_fer tracking
- `app/routers/webhook.py` — LINE webhook handler
- `app/routers/facebook_webhook.py` — Facebook webhook handler
- `app/services/chat/handler.py` — Main chat handler (`handle_natural_conversation()`)
- `app/services/dealer_lookup.py` — Dealer lookup service

## Rules
- **ALWAYS push to**: `https://github.com/AtenVisarut/chat-mahbin.git`
- **NEVER push to**: `chatbot-ladda-v2`
- Supabase client เป็น synchronous (ไม่ใช่ async)
- Persona: "พี่ม้าบิน" ผู้ชาย 23 ปี ที่ปรึกษาเกษตร
- Emoji ที่ใช้ได้: 😊 🌱 เท่านั้น
