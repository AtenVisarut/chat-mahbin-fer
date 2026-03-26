# Chatbot พี่ม้าบิน — ICP Fertilizer Advisor

LINE / Facebook Messenger chatbot ที่ปรึกษาด้านปุ๋ยและสารอารักขาพืช สำหรับ ICP Fertilizer

## ฟีเจอร์หลัก

| ฟีเจอร์ | รายละเอียด |
|---------|-----------|
| **Product Q&A** | ถาม-ตอบเรื่องสินค้า ปุ๋ย สารกำจัดศัตรูพืช ด้วย 4-Agent Agentic RAG |
| **Product Recommendation** | แนะนำสินค้าตามโรค/แมลง/วัชพืช ด้วย Vector Search + LLM Re-ranking |
| **Dealer Lookup** | ค้นหาตัวแทนจำหน่าย 414 ร้าน รองรับ fuzzy matching จังหวัด/อำเภอ |
| **Conversation Memory** | จำบริบทสนทนา แยก active topic อัตโนมัติ |
| **Multi-Platform** | รองรับทั้ง LINE และ Facebook Messenger |
| **Analytics Dashboard** | ติดตามสถิติการใช้งาน, โรคที่พบบ่อย, สินค้ายอดนิยม |

## Tech Stack

| เทคโนโลยี | ใช้สำหรับ |
|-----------|----------|
| **FastAPI** | Web framework (async) |
| **OpenAI GPT-4o** | Chat, Intent classification, Re-ranking, Response generation |
| **OpenAI Embeddings** | text-embedding-3-small สำหรับ Vector Search |
| **Supabase** | PostgreSQL + pgvector + Cache + Analytics |
| **LINE Bot SDK** | LINE Messaging API |
| **Facebook Graph API** | Messenger Platform |
| **Railway** | Hosting & Auto Deploy |

## โครงสร้างโปรเจค

```
app/
├── main.py                          # FastAPI app + lifespan
├── config.py                        # Environment variables & LLM model config
├── dependencies.py                  # Supabase, OpenAI, Analytics init
├── models.py                        # Pydantic models
├── prompts.py                       # Persona & prompt templates
│
├── routers/
│   ├── webhook.py                   # LINE webhook handler
│   ├── facebook_webhook.py          # Facebook webhook handler
│   ├── admin.py                     # Admin login & tools
│   ├── dashboard.py                 # Analytics API
│   └── health.py                    # Health check
│
├── services/
│   ├── chat/
│   │   ├── handler.py               # Main chat orchestrator
│   │   └── quick_classifier.py      # Intent classification
│   │
│   ├── product/
│   │   ├── recommendation.py        # Product recommendation engine
│   │   └── registry.py              # Product catalog from DB
│   │
│   ├── rag/                         # 4-Agent Agentic RAG Pipeline
│   │   ├── orchestrator.py          # Pipeline coordinator
│   │   ├── query_understanding_agent.py  # Agent 1: Intent & entity extraction
│   │   ├── retrieval_agent.py       # Agent 2: Vector search + re-rank
│   │   ├── grounding_agent.py       # Agent 3: Citation & hallucination check
│   │   └── response_generator_agent.py  # Agent 4: Answer synthesis
│   │
│   ├── dealer_lookup.py             # Dealer location search
│   ├── memory.py                    # Conversation history + topic detection
│   ├── cache.py                     # Two-layer cache (Memory + Supabase)
│   ├── analytics.py                 # Event tracking & alerts
│   ├── knowledge_base.py            # General knowledge RAG
│   ├── reranker.py                  # LLM-based result ranking
│   ├── user_service.py              # User management (LINE/FB)
│   └── welcome.py                   # Welcome messages
│
└── utils/
    ├── text_processing.py           # Thai text processing & emoji filter
    ├── rate_limiter.py              # Per-user rate limiting
    ├── line/                        # LINE message builders
    └── facebook/                    # Facebook message helpers
```

## การติดตั้ง

```bash
# Clone
git clone https://github.com/AtenVisarut/chat-mahbin-fer.git
cd chat-mahbin-fer

# Virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux

# Dependencies
pip install -r requirements.txt

# Environment variables
cp .env.example .env         # แก้ไขใส่ค่าจริง

# Run
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables

```bash
# Required
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_CHANNEL_SECRET=...
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=...

# Facebook (optional)
FB_PAGE_ACCESS_TOKEN=...
FB_VERIFY_TOKEN=...
FB_APP_SECRET=...

# Admin
ADMIN_USERNAME=...
ADMIN_PASSWORD=...
SECRET_KEY=...
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Service status |
| GET | `/health` | Detailed health check |
| POST | `/webhook` | LINE webhook |
| POST | `/facebook/webhook` | Facebook webhook |
| GET | `/login` | Admin login page |
| GET | `/dashboard` | Analytics dashboard |
| GET | `/api/analytics/dashboard` | Dashboard data (JSON) |
| GET | `/api/analytics/alerts` | Active alerts |

## Deploy (Railway)

1. Push to GitHub
2. เชื่อม Railway กับ repo `chat-mahbin-fer`
3. ตั้ง Environment Variables ใน Railway Dashboard
4. Railway auto deploy เมื่อ push to `main`

## Persona

**พี่ม้าบิน** — ผู้ชาย 23 ปี ที่ปรึกษาเกษตรจาก ICP Fertilizer
Emoji ที่ใช้: 😊 🌱 เท่านั้น

---

**GitHub**: [AtenVisarut/chat-mahbin-fer](https://github.com/AtenVisarut/chat-mahbin-fer)
