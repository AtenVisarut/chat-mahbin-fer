# Claude Identity — Chatbot พี่ม้าบิน (Mahbin-fer)

> ไฟล์นี้ใช้ให้ Claude จำการทำงานข้ามเซสชัน

---

## Project Info
- **ชื่อโปรเจค**: Chatbot พี่ม้าบิน (ที่ปรึกษาปุ๋ยและสารอารักขาพืช ICP Fertilizer)
- **Stack**: FastAPI + Supabase (sync client) + OpenAI GPT-4o + LINE Messaging API + Facebook Messenger
- **GitHub**: `https://github.com/AtenVisarut/chat-mahbin-fer.git` (origin/main)
- **Deploy**: Railway (auto deploy จาก GitHub)
- **Working Dir**: `C:\รวมProject_Chatbot-ICPL\chatbot_mahbin\Chatbot-Mahbin-fer\`

---

## ระบบนี้ทำอะไร

Chatbot LINE/Facebook สำหรับเกษตรกร ให้คำปรึกษาเรื่อง:

1. **ถาม-ตอบเรื่องสินค้า** — ผู้ใช้ถามเรื่องโรค/แมลง/วัชพืช → Bot แนะนำสินค้า ICP ที่เหมาะสม
2. **แนะนำผลิตภัณฑ์** — ค้นหาจาก Supabase (pgvector) → LLM Re-rank → แสดง Flex Message/Carousel
3. **ค้นหาตัวแทนจำหน่าย** — ถามจังหวัด/อำเภอ → fuzzy matching → แสดงรายชื่อร้านค้า
4. **สนทนาทั่วไป** — ตอบคำถามเกษตรทั่วไปด้วย Knowledge Base + GPT
5. **จำบริบท** — เก็บ conversation memory, แยก active topic อัตโนมัติ

### Flow หลัก
```
User ส่งข้อความ (LINE/FB)
  → webhook.py / facebook_webhook.py
    → ensure_user_exists() — สร้าง/อัปเดต user
    → handle_natural_conversation()
      → quick_classify() — แยก intent (สินค้า/ตัวแทน/ทั่วไป)
      → [สินค้า] → Agentic RAG Pipeline (4 agents) → ตอบพร้อมแหล่งอ้างอิง
      → [ตัวแทน] → dealer_lookup → ถามจังหวัด → แสดงรายชื่อ
      → [ทั่วไป] → GPT + Knowledge Base → ตอบแบบ conversational
    → add_to_memory() — เก็บประวัติ
```

### Agentic RAG Pipeline (4 Agents)
```
Agent 1: Query Understanding  → แยก intent, ดึง entity (โรค/แมลง/พืช)
Agent 2: Retrieval             → Vector search (pgvector) + LLM Re-rank
Agent 3: Grounding             → ตรวจ citation, ป้องกัน hallucination
Agent 4: Response Generator    → สร้างคำตอบภาษาไทย + confidence score
```

---

## Key Files & หน้าที่

### Core (เขียนสำหรับโปรเจคนี้)
| ไฟล์ | หน้าที่ |
|------|--------|
| `app/main.py` | FastAPI app, lifespan, middleware |
| `app/config.py` | ENV vars, LLM model config ทั้งหมด |
| `app/dependencies.py` | Init Supabase, OpenAI, Analytics |
| `app/prompts.py` | Persona พี่ม้าบิน, prompt templates, keywords |
| `app/routers/webhook.py` | LINE webhook — รับข้อความ/รูป/location |
| `app/routers/facebook_webhook.py` | Facebook Messenger webhook |
| `app/routers/admin.py` | Admin login, regenerate embeddings |
| `app/routers/dashboard.py` | Analytics dashboard API |
| `app/services/chat/handler.py` | **Main orchestrator** — routing ทุก intent |
| `app/services/chat/quick_classifier.py` | Intent classification (GPT-based) |
| `app/services/product/recommendation.py` | Product matching, disease→product mapping |
| `app/services/product/registry.py` | Load product catalog จาก Supabase |
| `app/services/rag/orchestrator.py` | 4-Agent RAG pipeline coordinator |
| `app/services/rag/query_understanding_agent.py` | Agent 1: Intent & entity extraction |
| `app/services/rag/retrieval_agent.py` | Agent 2: Vector search + re-rank |
| `app/services/rag/grounding_agent.py` | Agent 3: Citation check |
| `app/services/rag/response_generator_agent.py` | Agent 4: Answer synthesis |
| `app/services/dealer_lookup.py` | ค้นหาตัวแทนจำหน่าย (414 ร้าน) |
| `app/services/memory.py` | Conversation history + topic detection |
| `app/services/cache.py` | Two-layer cache (Memory L1 + Supabase L2) |
| `app/services/analytics.py` | Event tracking & alert system |
| `app/services/user_service.py` | User management, LINE/FB profile, user_fer |
| `app/services/knowledge_base.py` | General knowledge RAG fallback |
| `app/services/reranker.py` | LLM-based cross-encoder ranking |
| `app/utils/text_processing.py` | Thai diacritics matching, emoji filter, post-process |
| `app/utils/line/flex_messages.py` | LINE Flex Message builders |
| `app/utils/line/helpers.py` | LINE reply/push helpers |
| `app/utils/facebook/helpers.py` | Facebook Send API helpers |

### ไฟล์ที่มาจากโปรเจคเก่า (Chatbot-ladda) — ยังไม่ได้ปรับ
| ไฟล์ | สถานะ | หมายเหตุ |
|------|--------|----------|
| `templates/login.html` | ใช้งานอยู่ | HTML login page — ยังใช้ชื่อ/style เก่า |
| `templates/dashboard.html` | ใช้งานอยู่ | HTML dashboard — ยังใช้ style เก่า |
| `scripts/*` | ใช้เป็น utility | 20+ scripts สำหรับ migration/import — หลายตัวอ้างอิง table เก่า |
| `migrations/*` | ใช้เป็น reference | SQL migrations — บางตัวอ้างอิง schema เก่า (LIFF, registration) |
| `api/index.py` | ไม่ได้ใช้ | Vercel serverless entry point — ไม่เกี่ยวกับ Railway |
| `Dockerfile` | ไม่ได้ใช้ | Railway ใช้ Nixpacks ไม่ใช้ Dockerfile |
| `app/services/redis_cache.py` | ไม่ได้ใช้ | Redis/Upstash wrapper — config มีแต่ไม่ได้ integrate |
| `app/models.py` | ใช้น้อยมาก | Pydantic models — แทบไม่ได้ใช้ |

---

## Supabase Tables

| Table | ใช้สำหรับ |
|-------|----------|
| `mahbin_npk` | Product catalog + embeddings (pgvector) |
| `dealers` | ตัวแทนจำหน่าย 414 ร้าน |
| `users` | User profiles (LINE/FB) |
| `user_fer(LINE,FACE)` | User tracking แยก — created_at, updated_at |
| `conversation_memory` | ประวัติสนทนา |
| `cache` | L2 cache (key-value + TTL) |
| `analytics_events` | Event tracking |
| `analytics_alerts` | Alert records |
| `knowledge_base` | General knowledge documents + embeddings |

---

## สิ่งที่ทำล่าสุด

### 2026-03-26: Dead Code Cleanup + Repo Migration
- ลบ dead code 213 บรรทัด (functions ที่ไม่ถูกเรียกใช้)
- ย้าย repo จาก `chat-mahbin.git` → `chat-mahbin-fer.git`
- เริ่ม git history ใหม่เป็น commit แรก
- เขียน README ใหม่ให้ตรงกับ project จริง

### 2026-02-23: User Tracking
- ปรับปรุง `register_user_fer()` — upsert ลง `user_fer(LINE,FACE)`
- แก้ `ensure_user_exists()` — เรียก register ทุกครั้ง (backfill user เก่า)

### 2026-02-16: Dealer Lookup
- 414 ตัวแทนจำหน่ายในตาราง `dealers`
- Fuzzy province matching + pending context flow

---

## Rules
- **ALWAYS push to**: `https://github.com/AtenVisarut/chat-mahbin-fer.git`
- **NEVER push to**: `chatbot-ladda-v2` หรือ `chat-mahbin.git` (repo เก่า)
- Supabase client เป็น synchronous (ไม่ใช่ async)
- Persona: "พี่ม้าบิน" ผู้ชาย 23 ปี ที่ปรึกษาเกษตร
- Emoji ที่ใช้ได้: 😊 🌱 เท่านั้น
